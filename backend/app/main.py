import os
import re
from uuid import UUID
from datetime import date, timedelta, datetime
import json
from sqlalchemy import text

from fastapi import FastAPI, Depends, HTTPException, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging
from sqlalchemy import func
from sqlmodel import Session, SQLModel, create_engine, select
from dataclasses import replace
from geoalchemy2.shape import to_shape
from datetime import date as date_type
from pydantic import BaseModel, Field
from app.geocoding import geocode_address, geocode_la
from app.conditions import fetch_conditions
from app.directions import directions_for, walk_path, to_start
from app.activity_import import parse_activity, match_route, ImportProblem
import base64
from zoneinfo import ZoneInfo
from typing import List, Literal, Optional
from app.models import User, Checkin, Route, Injury, Run, Club, ClubSchedule, FavoriteRoute, Recommendation, RunGroup, RunGroupMember
from app.scoring.group_picks import Member, group_recommend
from app.scoring.engine import haversine_km as _hav
from app.scoring.converters import route_start
from app.auth import hash_password, verify_password, make_token, read_token, make_link_token, read_link_token
import hashlib
from app.emails import send_welcome_email, send_verify_email, send_reset_email, APP_URL

from app.scoring.engine import recommend, diversify, heat_distance_factor, readiness, long_but_gentle
LONG_ROUGH_NOTE = "This is long for how you feel today. Run it easy, and cut it short if you need to"
from app.scoring.converters import (
    build_user_profile, build_daily_checkin,
    build_recent_runs, build_route_candidates,
)
from app.scoring.route_combiner import generate_combined_routes
from app.scoring.fallbacks import (needs_gentler, add_gentler, GENTLE_EXTRA_KM, GENTLE_NOTE,
                                  wants_challenge, add_challenge, CHALLENGE_NOTE,
                                  drop_weak, match_pct, weak_match_note, LOW_MATCH_PCT)
from app.scoring.engine import build_personal_context, DailyCheckin, normalize_body_part, LOWER_BODY_PARTS
from app.scoring.groups import GroupSession, RunnerToday, match_groups, best_for_today, KM_PER_MI

# Set DATABASE_URL on Railway; falls back to the local Docker database.
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")
if DATABASE_URL.startswith("postgres://"):          # some hosts use the old scheme name
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
engine = create_engine(DATABASE_URL)

app = FastAPI()


class CatchErrors(BaseHTTPMiddleware):
    """Turn unexpected crashes into a normal JSON 500. Registered before CORS
    so CORS wraps it: without this, a crash returns a response with no CORS
    headers and the browser only shows "Load failed"."""
    async def dispatch(self, request, call_next):
        try:
            return await call_next(request)
        except Exception:
            logging.exception("Unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse(status_code=500,
                                content={"detail": "Something went wrong on our end. Please try again."})


app.add_middleware(CatchErrors)
app.add_middleware(
    CORSMiddleware,
    # FRONTEND_ORIGINS on Railway: your Vercel URL(s), comma-separated
    allow_origins=[o.strip() for o in os.environ.get("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if o.strip()],
    allow_origin_regex=os.environ.get("FRONTEND_ORIGIN_REGEX") or None,   # e.g. Vercel preview links
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def add_new_columns():
    """create_all() won't add columns to tables that already exist, so add
    any new ones here. IF NOT EXISTS makes this safe to run every startup."""
    # new tables (no-op if they exist)
    SQLModel.metadata.create_all(engine, tables=[RunGroup.__table__, RunGroupMember.__table__])
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE checkin ADD COLUMN IF NOT EXISTS run_time VARCHAR"))
        conn.execute(text("ALTER TABLE checkin ADD COLUMN IF NOT EXISTS available_minutes FLOAT"))
        conn.execute(text("ALTER TABLE checkin ADD COLUMN IF NOT EXISTS mood VARCHAR"))
        conn.execute(text("ALTER TABLE checkin ADD COLUMN IF NOT EXISTS run_intent VARCHAR"))
        conn.execute(text("ALTER TABLE club ADD COLUMN IF NOT EXISTS latitude FLOAT"))
        conn.execute(text("ALTER TABLE club ADD COLUMN IF NOT EXISTS longitude FLOAT"))
        conn.execute(text("ALTER TABLE clubschedule ADD COLUMN IF NOT EXISTS distance_mi FLOAT"))
        conn.execute(text("ALTER TABLE clubschedule ADD COLUMN IF NOT EXISTS run_type VARCHAR"))
        conn.execute(text("ALTER TABLE clubschedule ADD COLUMN IF NOT EXISTS surface VARCHAR"))
        conn.execute(text("ALTER TABLE club ADD COLUMN IF NOT EXISTS source_url VARCHAR"))
        conn.execute(text("ALTER TABLE club ADD COLUMN IF NOT EXISTS verified_on DATE"))
        conn.execute(text("ALTER TABLE club ADD COLUMN IF NOT EXISTS notes VARCHAR"))
        for col, typ in [("duration_s", "FLOAT"), ("elevation_gain_m", "FLOAT"), ("avg_heart_rate", "FLOAT"),
                         ("max_heart_rate", "FLOAT"), ("source", "VARCHAR"),
                         ("recommendation_id", "UUID"), ("pick_fit", "VARCHAR")]:
            conn.execute(text(f"ALTER TABLE run ADD COLUMN IF NOT EXISTS {col} {typ}"))
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS nickname VARCHAR"))
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS hidden BOOLEAN DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE checkin ADD COLUMN IF NOT EXISTS hills_pref VARCHAR"))
        conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS usual_pace_min_km FLOAT'))
        conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE'))
        conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP'))
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS elevation_loss_m FLOAT"))
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS shade_pct FLOAT"))
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS scenic_pct FLOAT"))
        # recommendation logging
        conn.execute(text("ALTER TABLE recommendation ALTER COLUMN route_id DROP NOT NULL"))
        for col, typ in [("checkin_id", "UUID"), ("rank", "INTEGER"), ("route_name", "VARCHAR"),
                         ("shown_at", "TIMESTAMP"), ("run_id", "UUID")]:
            conn.execute(text(f"ALTER TABLE recommendation ADD COLUMN IF NOT EXISTS {col} {typ}"))


MAX_DISTANCE_KM = 15  # only consider routes within this radius of the user's home


def get_session():
    with Session(engine) as session:
        yield session


# --- who is calling ----------------------------------------------------------

def current_user(authorization: Optional[str] = Header(None)) -> UUID:
    """The logged-in user, from the "Authorization: Bearer <token>" header."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Please log in.")
    user_id = read_token(authorization[7:].strip())
    if user_id is None:
        raise HTTPException(status_code=401, detail="Your session expired. Please log in again.")
    return user_id


def require_self(user_id: UUID, me: UUID = Depends(current_user)) -> UUID:
    """For endpoints with a user_id in the URL: only that user may call them."""
    check_self(user_id, me)
    return me


def check_self(user_id: UUID, me: UUID) -> None:
    if user_id != me:
        raise HTTPException(status_code=403, detail="That isn't your account.")


ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}


GENERATED_SUFFIX = re.compile(r"\s+-\s+\d+(\.\d+)?\s*km\s+(north|south|east|west)$", re.IGNORECASE)
GENERATED_KIND = [
    (" trail out-and-back", " Out-and-Back"),
    (" trail loop", " Trail Loop"),
    (" road loop", " Loop"),
]


DIRECTION_WORD = {"north": "North", "south": "South", "east": "East", "west": "West"}


def display_name(name: str) -> str:
    """Friendly card title. Generated routes are stored as e.g.
    'Occidental College road loop - 8 km south' (the scripts rely on that
    pattern to find and replace their own routes), but the card already
    shows distance and surface, so show 'Occidental College Loop'.
    Combined routes ('A + B') are cleaned part by part."""
    parts = []
    for part in name.split(" + "):
        m = GENERATED_SUFFIX.search(part)
        direction = DIRECTION_WORD.get(m.group(2).lower(), "") if m else ""
        part = GENERATED_SUFFIX.sub("", part)
        for old, new in GENERATED_KIND:
            if part.endswith(old):
                # keep the direction so loops from the same start stay distinct:
                # "Occidental College road loop - 8 km south" -> "Occidental College South Loop"
                part = part[: -len(old)] + (f" {direction}" if direction else "") + new
                break
        parts.append(part)
    return " + ".join(parts)


@app.get("/recommendations/{user_id}")
def get_recommendations(user_id: UUID, session: Session = Depends(get_session),
        _me: UUID = Depends(require_self),
        lat: Optional[float] = None, lon: Optional[float] = None):
    """lat/lon = the runner's current location (from the phone/browser). When it's
    missing (location not allowed), everything uses the home address from signup."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    checkin = session.exec(
        select(Checkin)
        .where(Checkin.user_id == user_id, Checkin.checkin_date == date.today())
        .order_by(Checkin.created_at.desc())
    ).first()
    if not checkin:
        raise HTTPException(status_code=404, detail="No checkin for today")

    effective_radius_km = checkin.willing_to_drive_km if checkin.willing_to_drive_km else MAX_DISTANCE_KM

    # where the run starts from: current location if we have a sensible one, else home
    use_here = lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180
    origin_lat, origin_lon = (lat, lon) if use_here else (user.latitude, user.longitude)
    origin_source = "current" if use_here else "home"

    routes_query = text("""
        SELECT id FROM route
        WHERE NOT COALESCE(hidden, FALSE) AND ST_DWithin(
            ST_StartPoint(gps_path)::geography,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :max_distance_m
        )
    """)
    nearby_route_ids = session.exec(
        routes_query,
        params={
            "lon": origin_lon,
            "lat": origin_lat,
            "max_distance_m": effective_radius_km * 1000,
        },
    ).all()
    nearby_ids = [row[0] for row in nearby_route_ids]

    routes = session.exec(select(Route).where(Route.id.in_(nearby_ids))).all()

    # Travel limit is a hard rule. If fewer than 3 routes start inside it, add the
    # closest ones (any distance away) so there are always 3 picks to compare.
    if len(routes) < 3:
        routes = list(routes) + closest_routes(session, origin_lat, origin_lon, {str(r.id) for r in routes}, 12)

    if not routes:
        raise HTTPException(
            status_code=404,
            detail=f"No routes found within {effective_radius_km:.0f}km of your location",
        )

    user_profile = build_user_profile(session, user)
    user_profile.home_lat, user_profile.home_lon = origin_lat, origin_lon   # closeness = from where they are
    daily_checkin = build_daily_checkin(checkin)
    daily_checkin.conditions = fetch_conditions(origin_lat, origin_lon, checkin.run_time or "now")
    recent_runs = build_recent_runs(session, user_id)
    candidates = build_route_candidates(routes)

    results = recommend(user_profile, daily_checkin, recent_runs, candidates)

    route_by_id = {str(route.id): route for route in routes}
    real_route_ids = set(route_by_id)

    # If the best result isn't a great distance match (or there's a target
    # distance nothing scored well against), also try combining routes into
    # synthetic longer options and merge them into the same ranking so the
    # best overall candidates (real or combined) win the top spots.
    best_is_weak_match = (not results) or (
        checkin.planned_distance_km and not results[0].distance_matched
    )
    if best_is_weak_match and checkin.planned_distance_km:
        heat_cut, _ = heat_distance_factor(daily_checkin.conditions)
        combined_routes = generate_combined_routes(routes, checkin.planned_distance_km * heat_cut)
        if combined_routes:
            combined_candidates = build_route_candidates(combined_routes)
            combined_results = recommend(user_profile, daily_checkin, recent_runs, combined_candidates)
            for cr in combined_routes:
                route_by_id[str(cr.id)] = cr

            results = diversify(results + combined_results, 3,
                                surface_requested=bool(checkin.surface_preference))

    # rough day and nothing nearby but Hard routes: look a little farther for gentler ones
    if needs_gentler(results, user_profile, daily_checkin, recent_runs):
        wider_ids = [row[0] for row in session.exec(routes_query, params={
            "lon": origin_lon, "lat": origin_lat,
            "max_distance_m": (effective_radius_km + GENTLE_EXTRA_KM) * 1000,
        }).all()]
        extra = [r for r in session.exec(select(Route).where(Route.id.in_(wider_ids))).all()
                 if str(r.id) not in route_by_id]
        if extra:
            results = add_gentler(results, user_profile, daily_checkin, recent_runs,
                                  build_route_candidates(extra))
            for r in extra:
                route_by_id[str(r.id)] = r
            real_route_ids |= {str(r.id) for r in extra}

    # fresh day and nothing Hard in the picks: offer one Hard run as the stretch option
    if wants_challenge(results, user_profile, daily_checkin, recent_runs):
        results = add_challenge(results, user_profile, daily_checkin, recent_runs, candidates)
    # always show the best option; drop extra picks that are poor fits far behind it
    # always 3 picks (study comparisons need the same number every time): if anything
    # above left fewer, fill with the best of the closest routes not shown yet
    if len(results) < 3:
        shown = {r.route.id for r in results}
        more = [r for r in closest_routes(session, origin_lat, origin_lon, shown | set(route_by_id), 40)]
        if more:
            extra = recommend(user_profile, daily_checkin, recent_runs, build_route_candidates(more), top_n=3,
                              gate=False)
            for r in more:
                route_by_id[str(r.id)] = r
            real_route_ids |= {str(r.id) for r in more}
            results = results + [e for e in extra if e.route.id not in shown][:3 - len(results)]

    rough_today = readiness(user_profile, daily_checkin, recent_runs) < 0.45

    # log exactly what was shown for this check-in (a refresh replaces it)
    # (picks that already have a run logged against them are kept)
    for old_rec in session.exec(select(Recommendation).where(Recommendation.checkin_id == checkin.id,
                                                             Recommendation.run_id.is_(None))).all():
        session.delete(old_rec)
    rec_ids = []
    now = datetime.utcnow()
    for rank, r in enumerate(results, start=1):
        rec = Recommendation(
            user_id=user.id,
            route_id=UUID(r.route.id) if r.route.id in real_route_ids else None,
            rec_date=date.today(),
            score=r.score,
            reasoning="; ".join(r.reasons)[:1000],
            checkin_id=checkin.id,
            rank=rank,
            route_name=display_name(r.route.name),
            shown_at=now,
        )
        session.add(rec)
        rec_ids.append(str(rec.id))
    session.commit()

    response = [
        {
            "recommendation_id": rec_ids[i],
            "rank": i + 1,
            # combined routes are synthetic (not in the route table), so they get
            # no id - logging a run on one just records distance/pace
            "route_id": r.route.id if r.route.id in real_route_ids else None,
            "route_name": display_name(r.route.name),
            "score": r.score,
            "score_breakdown": r.breakdown,
            "estimated_minutes": r.estimated_minutes,
            "run_format": r.run_format,
            "repeat_count": r.repeat_count,
            "effective_distance_km": round(r.effective_distance_km, 2),
            "reasons": r.reasons,
            "notice": GENTLE_NOTE if GENTLE_NOTE in r.reasons else
                CHALLENGE_NOTE if CHALLENGE_NOTE in r.reasons else
                (f"To fit your time, run {r.turnaround_km * 0.621371:.1f} mi out along this route, then turn back"
                 if checkin.available_minutes else
                 f"For a short run, go {r.turnaround_km * 0.621371:.1f} mi out along this route, then turn back")
                if r.turnaround_km else
                LONG_ROUGH_NOTE if rough_today and long_but_gentle(r.effective_distance_km, r.run_gain_m or 0) else
                weak_match_note(r) if match_pct(r) < LOW_MATCH_PCT else None,
            "distance_km": r.route.distance_km,
            "elevation_gain_m": r.run_gain_m if r.run_gain_m is not None
                                else run_climb_m(route_by_id[r.route.id], r.run_format, r.repeat_count),
            # run from home: the streets from home to the start, drawn on the card
            **approach_fields((origin_lat, origin_lon), r),
            "origin_source": origin_source,
            "difficulty": r.difficulty,
            # a long, flat run is "Hard" by length only: say so instead of just "Hard"
            "difficulty_label": "Long, gentle" if r.difficulty == "hard"
                and long_but_gentle(r.effective_distance_km, r.run_gain_m or 0) else r.difficulty,
            "surface_type": r.route.surface_type,
            # facts for "Why this route"
            "target_km": round(r.target_km, 2) if r.target_km else None,
            "shade_pct": getattr(r.route, "shade", None),
            "scenic_pct": getattr(r.route, "scenic_pct", None),
            "days_since_run": recent_runs.days_since_last_run_by_route_id.get(r.route.id),
            "your_rating": recent_runs.avg_rating_by_route_id.get(r.route.id),
            "feels_like_f": getattr(daily_checkin.conditions, "feels_like_f", None)
                            or getattr(daily_checkin.conditions, "temp_f", None),
            "turnaround_km": r.turnaround_km,
            "perfect_points": r.perfect_points,        # match % = (score - 100) / this
            # a short-on-time run goes partway along the route and back: draw only that part
            "path": first_part([
                [lat, lon]
                for lon, lat in (
                    route_by_id[r.route.id].coords
                    if hasattr(route_by_id[r.route.id], "coords")
                    else to_shape(route_by_id[r.route.id].gps_path).coords
                )
            ], r.turnaround_km),
        }
        for i, r in enumerate(results)
    ]
    return unique_titles(response)


def closest_routes(session, lat, lon, exclude: set, n: int) -> list:
    """The n visible routes starting closest to (lat, lon), any distance away."""
    rows = session.exec(text("""
        SELECT id FROM route WHERE NOT COALESCE(hidden, FALSE)
        ORDER BY ST_Distance(ST_StartPoint(gps_path)::geography,
                             ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
        LIMIT :n
    """), params={"lon": lon, "lat": lat, "n": n + len(exclude)}).all()
    ids = [r[0] for r in rows if str(r[0]) not in exclude][:n]
    return session.exec(select(Route).where(Route.id.in_(ids))).all() if ids else []


def first_part(path: list, km) -> list:
    """The path up to km along it (the turnaround point); the whole path when km is None."""
    if not km:
        return path
    out, done = [path[0]], 0.0
    for a, b in zip(path, path[1:]):
        step = _hav(a[0], a[1], b[0], b[1])
        if done + step >= km:
            t = (km - done) / step if step else 0
            out.append([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t])
            return out
        out.append(b)
        done += step
    return out


def approach_fields(origin, r) -> dict:
    """The way from the runner (current location, or home) to the start of the route.
    approach_km > 0 = close enough that it's run as part of today's run;
    otherwise travel_km is how far away the start is (they get there first)."""
    if origin[0] is None or r.route.start_lat is None:
        return {"approach_km": 0, "approach_path": [], "travel_km": None}
    path, metres = walk_path(origin, (r.route.start_lat, r.route.start_lon))
    return {"approach_km": round(getattr(r, "approach_km", 0) or 0, 2),
            "approach_path": [[a, b] for a, b in path],
            "travel_km": round(metres / 1000, 2),
            "home": [origin[0], origin[1]]}


def run_climb_m(route, run_format: str, repeat_count: int) -> float:
    """Climb for the run as recommended, not just the stored path:
    out-and-back = the climb out + the climb back (what you descended going out),
    repeated loop = one lap's climb x laps."""
    gain = route.elevation_gain_m or 0.0
    if run_format == "out_and_back":
        loss = getattr(route, "elevation_loss_m", None)
        return round(gain + (loss if loss is not None else gain), 1)
    if run_format == "repeat":
        return round(gain * max(1, repeat_count or 1), 1)
    return round(gain, 1)


def unique_titles(cards: list) -> list:
    """Never show two picks with the same title: tell look-alikes apart by
    length ("Short" / "Long", or "Short" / "Medium" / "Long") - never by a
    distance, which the card already shows."""
    groups = {}
    for c in cards:
        groups.setdefault(c["route_name"], []).append(c)
    for name, same in groups.items():
        if len(same) < 2:
            continue
        same.sort(key=lambda c: c["distance_km"])
        labels = ["Short", "Long"] if len(same) == 2 else ["Short", "Medium", "Long"]
        for c, lab in zip(same, labels):
            c["route_name"] = f"{name} ({lab})"
        for c in same[len(labels):]:
            c["route_name"] = f"{name} (Long)"
    return cards

class InjuryInput(BaseModel):
    body_part: str
    severity: str
    reported_at: date_type


class SignupRequest(BaseModel):
    full_name: str
    email: str
    password: str
    phone_number: Optional[str] = None
    date_of_birth: Optional[date_type] = None
    address: str
    fitness_level: str
    goal: str
    weekly_mileage_avg: float
    usual_pace_min_mile: Optional[float] = Field(default=None, ge=4, le=20)  # easy pace, minutes per mile
    injuries: List[InjuryInput] = []
    club_join_code: Optional[str] = None


SIGNUP_COVERAGE_RADIUS_KM = 15  # need routes within ~9 mi of home for useful picks


class AreaCheck(BaseModel):
    address: str


def check_coverage(session: Session, address: str):
    """Geocode inside LA and make sure Pathos has routes near it.
    Returns (lat, lon, label, route_count) or raises a 400 with a plain message."""
    try:
        lat, lon, label = geocode_la(address)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=503, detail="Couldn't look up that location right now. Try again in a moment.")
    count = session.exec(
        text("""
            SELECT COUNT(*) FROM route
            WHERE NOT COALESCE(hidden, FALSE) AND ST_DWithin(
                ST_StartPoint(gps_path)::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :max_distance_m
            )
        """),
        params={"lon": lon, "lat": lat, "max_distance_m": SIGNUP_COVERAGE_RADIUS_KM * 1000},
    ).first()[0]
    if count == 0:
        raise HTTPException(
            status_code=400,
            detail=(f"Found {label}, but Pathos doesn't have routes near there yet. It currently covers "
                    f"northeast LA, Glendale, Burbank, Pasadena and nearby areas."),
        )
    return lat, lon, label, count


@app.post("/check-area")
def check_area(payload: AreaCheck, session: Session = Depends(get_session)):
    """Signup step 2: confirm the location before moving on."""
    lat, lon, label, count = check_coverage(session, payload.address)
    return {"label": label, "lat": lat, "lon": lon, "routes_nearby": count}


@app.post("/signup")
def signup(payload: SignupRequest, background: BackgroundTasks, session: Session = Depends(get_session)):
    payload.email = payload.email.strip().lower()
    if session.exec(select(User).where(func.lower(User.email) == payload.email)).first():
        raise HTTPException(status_code=400, detail="An account with that email already exists. Log in instead.")
    lat, lon, _label, _count = check_coverage(session, payload.address)

    club_id = None
    if payload.club_join_code:
        club = session.exec(
            select(Club).where(Club.join_code == payload.club_join_code)
        ).first()
        if not club:
            raise HTTPException(status_code=400, detail="Invalid club join code")
        club_id = club.id

    user = User(
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        phone_number=payload.phone_number,
        date_of_birth=payload.date_of_birth,
        fitness_level=payload.fitness_level,
        weekly_mileage_avg=payload.weekly_mileage_avg,
        usual_pace_min_km=(payload.usual_pace_min_mile / 1.60934) if payload.usual_pace_min_mile else None,
        address=payload.address,
        latitude=lat,
        longitude=lon,
        goal=payload.goal,
        club_id=club_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    for injury in payload.injuries:
        session.add(Injury(
            user_id=user.id,
            body_part=injury.body_part,
            severity=injury.severity,
            reported_at=injury.reported_at,
        ))
    session.commit()

    # welcome email goes out after the response, so signup stays fast
    background.add_task(send_welcome_email, user.email, user.full_name, verify_link(user))

    return {"user_id": str(user.id), "token": make_token(user.id)}

class CheckinRequest(BaseModel):
    user_id: UUID
    energy_score: int
    sleep_hours: Optional[float] = None
    sleep_quality: Optional[int] = None
    sore_body_parts: List[str] = []
    wants_adventure: bool = False
    wants_scenic: bool = False
    surface_preference: Optional[Literal["trail", "road"]] = None
    mood_note: Optional[str] = None
    planned_distance_miles: Optional[float] = None
    willing_to_drive_miles: Optional[float] = None
    run_time: Optional[Literal["now", "morning", "midday", "evening",
                               "tomorrow_morning", "tomorrow_midday", "tomorrow_evening"]] = None
    available_minutes: Optional[float] = None
    mood: Optional[Literal["stressed", "flat", "good", "restless", "low"]] = None
    run_intent: Optional[Literal["easy", "workout", "long", "explore"]] = None
    hills_pref: Optional[Literal["avoid", "want"]] = None


@app.get("/checkins/{user_id}/last")
def last_checkin(user_id: UUID, session: Session = Depends(get_session),
        _me: UUID = Depends(require_self)):
    """The most recent check-in from an earlier day, for "Same as yesterday"."""
    c = session.exec(
        select(Checkin)
        .where(Checkin.user_id == user_id, Checkin.checkin_date < date_type.today())
        .order_by(Checkin.checkin_date.desc(), Checkin.created_at.desc())
    ).first()
    if not c:
        return None
    return {
        "checkin_date": c.checkin_date.isoformat(),
        "days_ago": (date_type.today() - c.checkin_date).days,
        "energy_score": c.energy_score,
        "sleep_hours": c.sleep_hours,
        "sleep_quality": c.sleep_quality,
        "sore_body_parts": json.loads(c.sore_body_parts or "[]"),
        "mood": c.mood,
        "run_intent": c.run_intent,
        "planned_distance_miles": round(c.planned_distance_km / 1.60934, 1) if c.planned_distance_km else None,
        "available_minutes": c.available_minutes,
        "willing_to_drive_miles": round(c.willing_to_drive_km / 1.60934, 1) if c.willing_to_drive_km else None,
        "surface_preference": c.surface_preference,
        "wants_scenic": c.wants_scenic,
        "run_time": c.run_time,
        "hills_pref": c.hills_pref,
    }


@app.post("/checkins")
def create_checkin(payload: CheckinRequest, session: Session = Depends(get_session),
        me: UUID = Depends(current_user)):
    check_self(payload.user_id, me)
    checkin = Checkin(
        user_id=payload.user_id,
        checkin_date=date_type.today(),
        energy_score=payload.energy_score,
        sleep_hours=payload.sleep_hours,
        sleep_quality=payload.sleep_quality,
        sore_body_parts=json.dumps(payload.sore_body_parts),
        planned_distance_km=(payload.planned_distance_miles * 1.60934) if payload.planned_distance_miles else None,
        willing_to_drive_km=(payload.willing_to_drive_miles * 1.60934) if payload.willing_to_drive_miles else None,
        wants_adventure=payload.wants_adventure,
        wants_scenic=payload.wants_scenic,
        surface_preference=payload.surface_preference,
        mood_note=(payload.mood_note or "").strip() or None,
        run_time=payload.run_time,
        available_minutes=payload.available_minutes,
        mood=payload.mood,
        run_intent=payload.run_intent,
        hills_pref=payload.hills_pref,
    )
    session.add(checkin)
    session.commit()
    session.refresh(checkin)
    return {"checkin_id": str(checkin.id)}

class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/login")
def login(payload: LoginRequest, session: Session = Depends(get_session)):
    email = payload.email.strip().lower()
    user = session.exec(select(User).where(func.lower(User.email) == email)).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"user_id": str(user.id), "token": make_token(user.id)}

class RunRequest(BaseModel):
    user_id: UUID
    route_id: Optional[UUID] = None
    distance_km: float
    pace_min_km: float
    rating: Optional[int] = None
    post_run_soreness: Optional[int] = None
    run_date: Optional[date_type] = None          # defaults to today; set from imported files
    duration_s: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    avg_heart_rate: Optional[float] = None
    max_heart_rate: Optional[float] = None
    source: Optional[str] = None
    recommendation_id: Optional[UUID] = None
    pick_fit: Optional[Literal["yes", "sort_of", "no"]] = None


@app.post("/runs")
def log_run(payload: RunRequest, session: Session = Depends(get_session),
        me: UUID = Depends(current_user)):
    check_self(payload.user_id, me)
    run = Run(
        user_id=payload.user_id,
        route_id=payload.route_id,
        run_date=payload.run_date or date_type.today(),
        distance_km=payload.distance_km,
        pace_min_km=payload.pace_min_km,
        rating=payload.rating,
        post_run_soreness=payload.post_run_soreness,
        duration_s=payload.duration_s,
        elevation_gain_m=payload.elevation_gain_m,
        avg_heart_rate=payload.avg_heart_rate,
        max_heart_rate=payload.max_heart_rate,
        source=payload.source or "manual",
        pick_fit=payload.pick_fit,
    )

    # link the run to the recommendation it came from. If the app didn't say,
    # match it to a route recommended to this user in the last 2 days.
    rec = session.get(Recommendation, payload.recommendation_id) if payload.recommendation_id else None
    if rec is None and payload.route_id:
        rec = session.exec(
            select(Recommendation)
            .where(Recommendation.user_id == payload.user_id,
                   Recommendation.route_id == payload.route_id,
                   Recommendation.rec_date >= run.run_date - timedelta(days=2))
            .order_by(Recommendation.shown_at.desc())
        ).first()
    if rec is not None and rec.user_id == payload.user_id:
        run.recommendation_id = rec.id

    session.add(run)
    session.commit()
    session.refresh(run)
    if rec is not None and rec.user_id == payload.user_id:
        rec.accepted = True
        rec.run_id = run.id
        session.add(rec)
        session.commit()
    return {"run_id": str(run.id)}


MAX_IMPORT_BYTES = 15 * 1024 * 1024
LOCAL_TZ = ZoneInfo("America/Los_Angeles")


class ImportRunRequest(BaseModel):
    user_id: UUID
    filename: str
    data_base64: str          # the file's bytes, base64-encoded by the browser


@app.post("/runs/import")
def import_run_file(payload: ImportRunRequest, session: Session = Depends(get_session),
        me: UUID = Depends(current_user)):
    """Read a GPX / TCX / FIT export and return what it contains, plus the
    Pathos route it matches (if any). Doesn't save anything: the Log a run
    form is filled in and the user confirms."""
    check_self(payload.user_id, me)
    try:
        data = base64.b64decode(payload.data_base64, validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Couldn't read the uploaded file.")
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=400, detail="That file is too large (15 MB max).")
    try:
        summary = parse_activity(payload.filename, data)
    except ImportProblem as e:
        raise HTTPException(status_code=400, detail=str(e))

    # match against routes near where the run started
    match = None
    track = [(p.lat, p.lon) for p in summary.points]
    if len(track) >= 5:
        start_lat, start_lon = track[0]
        nearby = session.exec(
            text("""
                SELECT id FROM route
                WHERE NOT COALESCE(hidden, FALSE) AND ST_DWithin(gps_path::geography,
                                 ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 1500)
            """),
            params={"lon": start_lon, "lat": start_lat},
        ).all()
        ids = [row[0] for row in nearby]
        if ids:
            candidates = []
            for r in session.exec(select(Route).where(Route.id.in_(ids))).all():
                path = [(lat, lon) for lon, lat in to_shape(r.gps_path).coords]
                candidates.append((str(r.id), display_name(r.nickname or r.name), path))
            match = match_route(track, candidates)

    start = summary.start_time
    local_start = start.astimezone(LOCAL_TZ) if start else None
    return {
        "source": summary.source_format,
        "run_date": local_start.date().isoformat() if local_start else None,
        "start_time": local_start.isoformat(timespec="minutes") if local_start else None,
        "distance_km": round(summary.distance_m / 1000, 3),
        "duration_s": summary.duration_s,
        "elevation_gain_m": summary.elevation_gain_m,
        "avg_heart_rate": summary.avg_hr,
        "max_heart_rate": summary.max_hr,
        "point_count": len(summary.points),
        "matched_route": match,
    }


@app.get("/research/summary")
def research_summary(user_id: Optional[UUID] = None, session: Session = Depends(get_session),
                     me: UUID = Depends(current_user)):
    """How the recommendations are doing: of check-ins that got picks, how
    often a run followed, which rank was run, and whether it fit.
    Pass ?user_id=... for one runner; leave it off for everyone
    (everyone needs your email in ADMIN_EMAILS)."""
    if user_id != me:
        caller = session.get(User, me)
        if not caller or (caller.email or "").lower() not in ADMIN_EMAILS:
            raise HTTPException(status_code=403, detail="Only admins can see other runners' numbers.")
    q = select(Recommendation).where(Recommendation.checkin_id.is_not(None))
    if user_id:
        q = q.where(Recommendation.user_id == user_id)
    recs = session.exec(q).all()
    checkins = {r.checkin_id for r in recs}
    ran_rank = {}
    for r in recs:
        if r.run_id:
            ran_rank[r.checkin_id] = min(ran_rank.get(r.checkin_id, 99), r.rank or 99)

    rq = select(Run).where(Run.pick_fit.is_not(None))
    if user_id:
        rq = rq.where(Run.user_id == user_id)
    fits = [r.pick_fit for r in session.exec(rq).all()]

    n = len(checkins)
    def pct(x):
        return round(100 * x / n, 1) if n else None
    return {
        "checkins_with_picks": n,
        "ran_a_pick": len(ran_rank),
        "ran_top_pick": sum(1 for v in ran_rank.values() if v == 1),
        "ran_pick_rate_pct": pct(len(ran_rank)),
        "top_pick_rate_pct": pct(sum(1 for v in ran_rank.values() if v == 1)),
        "rank_of_run": {str(k): sum(1 for v in ran_rank.values() if v == k) for k in (1, 2, 3)},
        "pick_fit": {k: fits.count(k) for k in ("yes", "sort_of", "no")},
    }


@app.get("/clubs")
def list_clubs(session: Session = Depends(get_session)):
    clubs = session.exec(select(Club)).all()
    result = []
    for club in clubs:
        schedules = session.exec(
            select(ClubSchedule).where(ClubSchedule.club_id == club.id)
        ).all()
        result.append({
            "id": str(club.id),
            "name": club.name,
            "location": club.location,
            "pace_range": club.pace_range,
            "experience_level": club.experience_level,
            "join_code": club.join_code,
            "schedule": [
                {"day": s.day_of_week, "time": s.meetup_time} for s in schedules
            ],
        })
    return result


@app.get("/clubs/mine/{user_id}")
def get_my_club(user_id: UUID, session: Session = Depends(get_session),
        _me: UUID = Depends(require_self)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.club_id:
        return None

    club = session.get(Club, user.club_id)
    schedules = session.exec(
        select(ClubSchedule).where(ClubSchedule.club_id == club.id)
    ).all()
    return {
        "id": str(club.id),
        "name": club.name,
        "location": club.location,
        "pace_range": club.pace_range,
        "experience_level": club.experience_level,
        "schedule": [
            {"day": s.day_of_week, "time": s.meetup_time} for s in schedules
        ],
    }


# ---------------------------------------------------------------------------
# Past runs, stats, favorites (used by the nav bar pages)
# ---------------------------------------------------------------------------

@app.get("/conditions/{user_id}")
def get_conditions(user_id: UUID, session: Session = Depends(get_session),
        _me: UUID = Depends(require_self)):
    """Weather / air / daylight for the user's home at the time they said
    they're running today. Returns null if there's no data (e.g. offline)."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    checkin = session.exec(
        select(Checkin)
        .where(Checkin.user_id == user_id, Checkin.checkin_date == date.today())
        .order_by(Checkin.created_at.desc())
    ).first()
    run_time = (checkin.run_time if checkin else None) or "now"
    cond = fetch_conditions(user.latitude, user.longitude, run_time)
    if not cond:
        return None
    cut, _ = heat_distance_factor(cond)
    cond.heat_cut_pct = round((1 - cut) * 100) if cut < 1 else None
    return cond.to_dict()


@app.get("/routes/{route_id}/path")
def get_route_path(route_id: UUID, session: Session = Depends(get_session)):
    """Full-resolution [lat, lon] path for one route (used for GPX export)."""
    route = session.get(Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return {
        "route_id": str(route.id),
        "route_name": display_name(route.nickname or route.name),
        "path": [[lat, lon] for lon, lat in to_shape(route.gps_path).coords],
    }


def _group_match_json(m) -> dict:
    s = m.session
    return {
        "club_id": s.club_id,
        "club_name": s.club_name,
        "location": s.location,
        "pace_range": s.pace_range,
        "experience_level": s.experience_level,
        "starts_at": m.starts_at.isoformat(timespec="minutes"),
        "day_of_week": s.day_of_week,
        "meetup_time": s.meetup_time,
        "distance_mi": s.distance_mi,
        "run_type": s.run_type,
        "surface": s.surface,
        "is_my_club": s.is_my_club,
        "is_today": m.is_today,
        "fit": m.fit,
        "reasons": m.reasons,
        "cautions": m.cautions,
        "distance_from_home_km": m.distance_from_home_km,
        "source_url": getattr(s, "source_url", None),
        "verified_on": getattr(s, "verified_on", None),
        "notes": getattr(s, "notes", None),
        "place_label": getattr(s, "place_label", None) or s.location,
    }


def club_place_label(location: Optional[str]) -> str:
    """'Garvanza Park, 6240 Meridian St, Los Angeles, CA' -> 'Garvanza Park, Los Angeles'
       '235 N Lake Ave, Pasadena, CA'                     -> '235 N Lake Ave, Pasadena'"""
    if not location:
        return ""
    parts = [p.strip() for p in location.split(",") if p.strip()]
    parts = [p for p in parts if not re.fullmatch(r"(CA|California|USA|United States|\d{5})", p)]
    if len(parts) <= 1:
        return parts[0] if parts else location
    return f"{parts[0]}, {parts[-1]}"


@app.get("/groups/{user_id}")
def get_group_matches(user_id: UUID, session: Session = Depends(get_session),
        _me: UUID = Depends(require_self)):
    """Club sessions in the next 7 days ranked by fit, plus the best one for
    today (if any fits well enough to suggest next to the solo routes)."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    checkin = session.exec(
        select(Checkin)
        .where(Checkin.user_id == user_id, Checkin.checkin_date == date.today())
        .order_by(Checkin.created_at.desc())
    ).first()

    profile = build_user_profile(session, user)
    recent = build_recent_runs(session, user_id)
    daily = build_daily_checkin(checkin) if checkin else DailyCheckin(energy_score=5)
    ctx = build_personal_context(profile, daily, recent)
    sore_legs = bool({normalize_body_part(p) for p in daily.sore_body_parts} & LOWER_BODY_PARTS)

    runner = RunnerToday(
        fitness_level=user.fitness_level,
        pace_min_mi=ctx.pace_min_km * KM_PER_MI,
        typical_mi=ctx.typical_km / KM_PER_MI,
        readiness=ctx.readiness,
        planned_mi=(checkin.planned_distance_km / KM_PER_MI) if checkin and checkin.planned_distance_km else None,
        run_time=checkin.run_time if checkin else None,
        sore_legs=sore_legs,
        checked_in_today=checkin is not None,
        home_lat=user.latitude,
        home_lon=user.longitude,
    )

    clubs = session.exec(select(Club)).all()
    for club in clubs:
        # older seeds stored just the store name for Glendale
        if club.location and club.location.startswith("lululemon, 889 Americana"):
            club.location = "Americana at Brand (lululemon), 889 Americana Way, Glendale, CA"
            session.add(club)
        # clubs whose address never geocoded have no "mi away"; try again (once)
        if club.latitude is None and club.location:
            parts = [p.strip() for p in club.location.split(",")]
            for attempt in (club.location, ", ".join(parts[1:])):
                try:
                    club.latitude, club.longitude, _ = geocode_la(attempt)
                    session.add(club)
                    break
                except Exception:
                    continue
    session.commit()

    sessions = []
    for club in clubs:
        for sched in session.exec(select(ClubSchedule).where(ClubSchedule.club_id == club.id)).all():
            sessions.append(GroupSession(
                club_id=str(club.id), club_name=club.name, location=club.location,
                pace_range=club.pace_range, experience_level=club.experience_level,
                day_of_week=sched.day_of_week.lower(), meetup_time=sched.meetup_time,
                distance_mi=sched.distance_mi, run_type=sched.run_type, surface=sched.surface,
                lat=club.latitude, lon=club.longitude, is_my_club=(club.id == user.club_id),
            ))
            sessions[-1].source_url = club.source_url
            sessions[-1].verified_on = club.verified_on.isoformat() if club.verified_on else None
            sessions[-1].notes = club.notes
            sessions[-1].place_label = club_place_label(club.location)

    matches = match_groups(sessions, runner)
    today = best_for_today(matches)
    return {
        "today": _group_match_json(today) if today else None,
        "upcoming": [_group_match_json(m) for m in matches],
        "checked_in_today": checkin is not None,
    }


class JoinClubRequest(BaseModel):
    user_id: UUID
    join_code: str


@app.post("/clubs/join")
def join_club(payload: JoinClubRequest, session: Session = Depends(get_session),
        me: UUID = Depends(current_user)):
    check_self(payload.user_id, me)
    user = session.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    club = session.exec(select(Club).where(Club.join_code == payload.join_code.strip().upper())).first()
    if not club:
        raise HTTPException(status_code=400, detail="That join code didn't match a club")
    user.club_id = club.id
    session.add(user)
    session.commit()
    return {"club_id": str(club.id), "club_name": club.name}


@app.post("/clubs/leave/{user_id}")
def leave_club(user_id: UUID, session: Session = Depends(get_session),
        _me: UUID = Depends(require_self)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.club_id = None
    session.add(user)
    session.commit()
    return {"ok": True}


class DirectionsRequest(BaseModel):
    path: List[List[float]]     # [[lat, lon], ...] as it will be run (out-and-backs already doubled)


class ToStartRequest(BaseModel):
    origin: List[float]          # [lat, lon] where the runner is now
    start: List[float]           # [lat, lon] start of the route


@app.post("/directions/to-start")
def get_directions_to_start(payload: ToStartRequest):
    """How to get from the runner's current spot to the start of the route."""
    if len(payload.origin) < 2 or len(payload.start) < 2:
        raise HTTPException(status_code=400, detail="origin and start are [lat, lon]")
    return to_start((payload.origin[0], payload.origin[1]), (payload.start[0], payload.start[1]))


@app.post("/directions")
def get_directions(payload: DirectionsRequest):
    """Turn-by-turn cues for a path, from OSRM. Returns null if OSRM is down."""
    path = [(p[0], p[1]) for p in payload.path if len(p) >= 2]
    return directions_for(path)


@app.get("/runs/{user_id}")
def list_runs(user_id: UUID, session: Session = Depends(get_session),
        _me: UUID = Depends(require_self)):
    runs = session.exec(
        select(Run).where(Run.user_id == user_id).order_by(Run.run_date.desc())
    ).all()
    result = []
    for run in runs:
        route = session.get(Route, run.route_id) if run.route_id else None
        result.append({
            "id": str(run.id),
            "run_date": run.run_date.isoformat(),
            "route_id": str(run.route_id) if run.route_id else None,
            "route_name": display_name(route.nickname or route.name) if route else None,
            "surface_type": route.surface_type if route else None,
            "distance_km": run.distance_km,
            "pace_min_km": run.pace_min_km,
            "rating": run.rating,
            "post_run_soreness": run.post_run_soreness,
            "duration_s": run.duration_s,
            "elevation_gain_m": run.elevation_gain_m,
            "avg_heart_rate": run.avg_heart_rate,
            "source": run.source,
            "pick_fit": run.pick_fit,
        })
    return result


@app.get("/stats/{user_id}")
def get_stats(user_id: UUID, session: Session = Depends(get_session),
        _me: UUID = Depends(require_self)):
    runs = session.exec(select(Run).where(Run.user_id == user_id)).all()
    today = date_type.today()
    week_start = today - timedelta(days=today.weekday())  # Monday

    # weekly distance for the last 8 weeks, oldest first
    weekly = []
    for i in range(7, -1, -1):
        start = week_start - timedelta(weeks=i)
        end = start + timedelta(days=7)
        km = sum(r.distance_km for r in runs if start <= r.run_date < end)
        weekly.append({"week_start": start.isoformat(), "distance_km": round(km, 2)})

    # consecutive days with at least one run, ending today or yesterday
    run_days = {r.run_date for r in runs}
    streak = 0
    day = today if today in run_days else today - timedelta(days=1)
    while day in run_days:
        streak += 1
        day -= timedelta(days=1)

    total_km = sum(r.distance_km for r in runs)
    rated = [r.rating for r in runs if r.rating is not None]
    favorites = session.exec(
        select(FavoriteRoute).where(FavoriteRoute.user_id == user_id)
    ).all()

    return {
        "total_runs": len(runs),
        "total_distance_km": round(total_km, 2),
        "this_week_distance_km": weekly[-1]["distance_km"],
        # distance-weighted so a long slow run counts more than a short fast one
        "avg_pace_min_km": round(sum(r.pace_min_km * r.distance_km for r in runs) / total_km, 2) if total_km else None,
        "longest_run_km": round(max((r.distance_km for r in runs), default=0), 2),
        "avg_rating": round(sum(rated) / len(rated), 1) if rated else None,
        "current_streak_days": streak,
        "favorite_count": len(favorites),
        "weekly": weekly,
        # Monday-first: did the user run on each day of the current week?
        "this_week_days": [
            (week_start + timedelta(days=i)) in run_days for i in range(7)
        ],
        "this_week_daily_km": [
            round(sum(r.distance_km for r in runs if r.run_date == week_start + timedelta(days=i)), 2)
            for i in range(7)
        ],
        "runs_this_week": sum(1 for r in runs if r.run_date >= week_start),
        "fastest_pace_min_km": round(min((r.pace_min_km for r in runs), default=0), 2) or None,
        "longest_run_name": _longest_name(session, runs),
        "surface_mix_km": _surface_mix(session, runs),
    }


def _longest_name(session: Session, runs: list) -> Optional[str]:
    if not runs:
        return None
    longest = max(runs, key=lambda r: r.distance_km)
    route = session.get(Route, longest.route_id) if longest.route_id else None
    return display_name(route.nickname or route.name) if route else None


def _surface_mix(session: Session, runs: list) -> dict:
    mix = {"pavement": 0.0, "trail": 0.0, "track": 0.0, "mixed": 0.0, "own": 0.0}
    for r in runs:
        route = session.get(Route, r.route_id) if r.route_id else None
        key = route.surface_type if route and route.surface_type in mix else "own"
        mix[key] += r.distance_km
    return {k: round(v, 2) for k, v in mix.items()}


class FavoriteRequest(BaseModel):
    user_id: UUID
    route_id: UUID


def _thin_path(points: list, max_points: int = 80) -> list:
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    thinned = [points[int(i * step)] for i in range(max_points)]
    thinned.append(points[-1])
    return thinned


@app.get("/favorites/{user_id}")
def list_favorites(user_id: UUID, session: Session = Depends(get_session),
        _me: UUID = Depends(require_self)):
    favorites = session.exec(
        select(FavoriteRoute)
        .where(FavoriteRoute.user_id == user_id)
        .order_by(FavoriteRoute.created_at.desc())
    ).all()
    result = []
    for fav in favorites:
        route = session.get(Route, fav.route_id)
        if not route:
            continue
        times_run = len(session.exec(
            select(Run).where(Run.user_id == user_id, Run.route_id == route.id)
        ).all())
        result.append({
            "route_id": str(route.id),
            "route_name": display_name(route.nickname or route.name),
            "distance_km": route.distance_km,
            "elevation_gain_m": route.elevation_gain_m,
            "difficulty": route.difficulty,
            "surface_type": route.surface_type,
            "scenic": route.scenic,
            "times_run": times_run,
            "saved_at": fav.created_at.isoformat(),
            # [lat, lon] points, thinned to ~80 so the response stays small
            "path": _thin_path([[lat, lon] for lon, lat in to_shape(route.gps_path).coords]),
        })
    return result


@app.post("/favorites")
def add_favorite(payload: FavoriteRequest, session: Session = Depends(get_session),
        me: UUID = Depends(current_user)):
    check_self(payload.user_id, me)
    if not session.get(Route, payload.route_id):
        raise HTTPException(status_code=404, detail="Route not found")
    existing = session.exec(
        select(FavoriteRoute).where(
            FavoriteRoute.user_id == payload.user_id,
            FavoriteRoute.route_id == payload.route_id,
        )
    ).first()
    if not existing:
        session.add(FavoriteRoute(user_id=payload.user_id, route_id=payload.route_id))
        session.commit()
    return {"ok": True}


@app.delete("/favorites/{user_id}/{route_id}")
def remove_favorite(user_id: UUID, route_id: UUID, session: Session = Depends(get_session),
        _me: UUID = Depends(require_self)):
    fav = session.exec(
        select(FavoriteRoute).where(
            FavoriteRoute.user_id == user_id,
            FavoriteRoute.route_id == route_id,
        )
    ).first()
    if fav:
        session.delete(fav)
        session.commit()
    return {"ok": True}




# ---------------------------------------------------------------------------
# Run together: friends check in separately, get one shared route
# ---------------------------------------------------------------------------

class RunGroupCreate(BaseModel):
    user_id: UUID
    name: str


class RunGroupJoin(BaseModel):
    user_id: UUID
    code: str


class RunGroupUser(BaseModel):
    user_id: UUID


class MeetingSpot(BaseModel):
    user_id: UUID
    address: Optional[str] = None      # None / "" clears it -> "near everyone"


NEAR_HOME_KM = 3.2          # same as the check-in's "Near home"
MEET_SPOT_RADIUS_KM = 3.0   # routes must start this close to a meeting spot


def _new_join_code(session: Session) -> str:
    import secrets
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I mix-ups
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if not session.exec(select(RunGroup).where(RunGroup.join_code == code)).first():
            return code


def _group_json(session: Session, g: RunGroup) -> dict:
    members = session.exec(select(RunGroupMember).where(RunGroupMember.group_id == g.id)).all()
    out = []
    for mem in members:
        u = session.get(User, mem.user_id)
        if not u:
            continue
        checked = session.exec(
            select(Checkin).where(Checkin.user_id == u.id, Checkin.checkin_date == date.today())
        ).first() is not None
        out.append({"user_id": str(u.id), "name": u.full_name.split()[0] if u.full_name else "Runner",
                    "checked_in_today": checked, "is_owner": u.id == g.owner_id})
    out.sort(key=lambda m: (not m["is_owner"], m["name"].lower()))
    return {"id": str(g.id), "name": g.name, "join_code": g.join_code,
            "meet_label": g.meet_label, "members": out}


def _member_of(session: Session, group_id: UUID, user_id: UUID) -> RunGroup:
    g = session.get(RunGroup, group_id)
    if not g or not session.exec(select(RunGroupMember).where(
            RunGroupMember.group_id == group_id, RunGroupMember.user_id == user_id)).first():
        raise HTTPException(status_code=404, detail="Group not found")
    return g


@app.post("/run-groups")
def create_run_group(payload: RunGroupCreate, session: Session = Depends(get_session),
        me: UUID = Depends(current_user)):
    check_self(payload.user_id, me)
    name = payload.name.strip()[:60] or "Running crew"
    g = RunGroup(name=name, join_code=_new_join_code(session), owner_id=payload.user_id)
    session.add(g)
    session.commit()
    session.add(RunGroupMember(group_id=g.id, user_id=payload.user_id))
    session.commit()
    return _group_json(session, g)


@app.post("/run-groups/join")
def join_run_group(payload: RunGroupJoin, session: Session = Depends(get_session),
        me: UUID = Depends(current_user)):
    check_self(payload.user_id, me)
    g = session.exec(select(RunGroup).where(RunGroup.join_code == payload.code.strip().upper())).first()
    if not g:
        raise HTTPException(status_code=404, detail="No group with that code. Check it with whoever shared it.")
    exists = session.exec(select(RunGroupMember).where(
        RunGroupMember.group_id == g.id, RunGroupMember.user_id == payload.user_id)).first()
    if not exists:
        session.add(RunGroupMember(group_id=g.id, user_id=payload.user_id))
        session.commit()
    return _group_json(session, g)


@app.post("/run-groups/{group_id}/leave")
def leave_run_group(group_id: UUID, payload: RunGroupUser, session: Session = Depends(get_session),
        me: UUID = Depends(current_user)):
    check_self(payload.user_id, me)
    mem = session.exec(select(RunGroupMember).where(
        RunGroupMember.group_id == group_id, RunGroupMember.user_id == payload.user_id)).first()
    if mem:
        session.delete(mem)
        session.commit()
    return {"ok": True}


@app.get("/run-groups/mine/{user_id}")
def my_run_groups(user_id: UUID, session: Session = Depends(get_session),
        _me: UUID = Depends(require_self)):
    ids = [m.group_id for m in session.exec(select(RunGroupMember).where(RunGroupMember.user_id == user_id)).all()]
    groups = [session.get(RunGroup, i) for i in ids]
    return [_group_json(session, g) for g in groups if g]


@app.put("/run-groups/{group_id}/meeting-spot")
def set_meeting_spot(group_id: UUID, payload: MeetingSpot, session: Session = Depends(get_session),
        me: UUID = Depends(current_user)):
    check_self(payload.user_id, me)
    g = _member_of(session, group_id, payload.user_id)
    if not payload.address or not payload.address.strip():
        g.meet_label = g.meet_lat = g.meet_lon = None
    else:
        try:
            lat, lon, label = geocode_la(payload.address.strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        g.meet_label, g.meet_lat, g.meet_lon = label, lat, lon
    session.add(g)
    session.commit()
    return _group_json(session, g)


@app.get("/run-groups/{group_id}/recommendations")
def run_group_recommendations(group_id: UUID, user_id: UUID, session: Session = Depends(get_session),
        _me: UUID = Depends(require_self)):
    g = _member_of(session, group_id, user_id)
    rows = session.exec(select(RunGroupMember).where(RunGroupMember.group_id == g.id)).all()

    members, homes, radii, waiting = [], [], [], []
    for row in rows:
        u = session.get(User, row.user_id)
        if not u:
            continue
        first = u.full_name.split()[0] if u.full_name else "Runner"
        ck = session.exec(
            select(Checkin).where(Checkin.user_id == u.id, Checkin.checkin_date == date.today())
            .order_by(Checkin.created_at.desc())
        ).first()
        if not ck:
            waiting.append(first)
            continue
        profile = build_user_profile(session, u)
        if g.meet_lat is not None:      # everyone meets there: judge closeness from the spot
            profile = replace(profile, home_lat=g.meet_lat, home_lon=g.meet_lon)
        daily = build_daily_checkin(ck)
        members.append(Member(first, profile, daily, build_recent_runs(session, u.id)))
        homes.append((u.latitude, u.longitude))
        radii.append(ck.willing_to_drive_km or MAX_DISTANCE_KM)

    if not members:
        raise HTTPException(status_code=400, detail="Nobody in the group has checked in today yet.")

    # where routes may start
    if g.meet_lat is not None:
        center, search_km = (g.meet_lat, g.meet_lon), MEET_SPOT_RADIUS_KM
    else:
        lat = sum(h[0] for h in homes) / len(homes)
        lon = sum(h[1] for h in homes) / len(homes)
        spread = max(_hav(lat, lon, h[0], h[1]) for h in homes)
        center, search_km = (lat, lon), min(spread + max(radii), MAX_DISTANCE_KM + spread)
    ids = [r[0] for r in session.exec(text("""
        SELECT id FROM route
        WHERE NOT COALESCE(hidden, FALSE) AND ST_DWithin(
            ST_StartPoint(gps_path)::geography,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :m)
    """), params={"lon": center[1], "lat": center[0], "m": search_km * 1000}).all()]
    routes = session.exec(select(Route).where(Route.id.in_(ids))).all() if ids else []

    if g.meet_lat is None and routes:
        # fair for everyone: each member's own travel limit, measured from their home
        def worst(route):
            s_lat, s_lon = route_start(route)
            return max(_hav(h[0], h[1], s_lat, s_lon) / r for h, r in zip(homes, radii))
        fits = [r for r in routes if worst(r) <= 1.0]
        routes = fits if len(fits) >= 3 else sorted(routes, key=worst)[:25]
    if not routes:
        raise HTTPException(status_code=404, detail="No routes found that work for everyone's location.")

    route_by_id = {str(r.id): r for r in routes}
    picks, shared_km = group_recommend(members, build_route_candidates(routes))

    def start_km_for(route, home):
        s_lat, s_lon = route_start(route)
        return round(_hav(home[0], home[1], s_lat, s_lon) * 0.621371, 1)

    return {
        "group": _group_json(session, g),
        "shared_distance_mi": round(shared_km * 0.621371, 1),
        "waiting_on": waiting,
        "picks": [{
            "route_id": p.route.id,
            "route_name": display_name(p.route.name),
            "distance_km": p.route.distance_km,
            "effective_distance_km": round(p.effective_distance_km, 2),
            "run_format": p.run_format,
            "repeat_count": p.repeat_count,
            "elevation_gain_m": getattr(p, "run_gain_m", None) if getattr(p, "run_gain_m", None) is not None
                                else run_climb_m(route_by_id[p.route.id], p.run_format, p.repeat_count),
            "surface_type": p.route.surface_type,
            "difficulty": p.difficulty,
            "minutes_range": [min(p.estimated_minutes), max(p.estimated_minutes)],
            "members": [{
                "name": f.name, "fit": f.fit, "reason": f.reason, "extra_laps": f.extra_laps,
                "start_mi": start_km_for(route_by_id[p.route.id], h),
            } for f, h in zip(p.members, homes)],
            "path": [[lat, lon] for lon, lat in to_shape(route_by_id[p.route.id].gps_path).coords],
        } for p in picks],
    }


# ---------------------------------------------------------------------------
# Email verification (soft: the app works right away, a banner nudges until
# the link in the welcome email is clicked)
# ---------------------------------------------------------------------------

VERIFY_PURPOSE = "verify_email"
RESEND_COOLDOWN_S = 60
_last_verify_sent: dict = {}


def verify_link(user: User) -> str:
    token = make_link_token(user.id, VERIFY_PURPOSE, user.email, hours=24)
    return f"{APP_URL}/verify-email?token={token}"


@app.get("/me")
def me(session: Session = Depends(get_session), me: UUID = Depends(current_user)):
    user = session.get(User, me)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": str(user.id), "email": user.email,
            "first_name": (user.full_name or "").split(" ")[0],
            "email_verified": bool(user.email_verified)}


class VerifyEmailRequest(BaseModel):
    token: str


@app.post("/verify-email")
def verify_email_link(payload: VerifyEmailRequest, session: Session = Depends(get_session)):
    """Opened from the email link, so it works without being logged in."""
    found = read_link_token(payload.token, VERIFY_PURPOSE)
    if not found:
        raise HTTPException(status_code=400, detail="This link has expired or isn't valid. Send yourself a new one from the app.")
    user_id, email = found
    user = session.get(User, user_id)
    if not user or (user.email or "").lower() != email:
        raise HTTPException(status_code=400, detail="This link is for an older email address. Send yourself a new one from the app.")
    if not user.email_verified:
        user.email_verified = True
        user.email_verified_at = datetime.utcnow()
        session.add(user)
        session.commit()
    return {"ok": True, "email": user.email}


@app.post("/verify-email/resend")
def resend_verify_email(background: BackgroundTasks, session: Session = Depends(get_session),
                        me: UUID = Depends(current_user)):
    user = session.get(User, me)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.email_verified:
        return {"ok": True, "already_verified": True}
    now = datetime.utcnow().timestamp()
    if now - _last_verify_sent.get(user.id, 0) < RESEND_COOLDOWN_S:
        raise HTTPException(status_code=429, detail="We just sent one. Give it a minute, and check your spam folder.")
    _last_verify_sent[user.id] = now
    background.add_task(send_verify_email, user.email, user.full_name, verify_link(user))
    return {"ok": True, "email": user.email}


# ---------------------------------------------------------------------------
# Forgot password. The reset link carries a fingerprint of the current
# password hash, so it stops working as soon as the password changes
# (one use) and after 1 hour. Clicking it also proves the person owns the
# email, so it marks the email verified.
# ---------------------------------------------------------------------------

RESET_PURPOSE = "reset_password"
MIN_PASSWORD_LEN = 6
_last_reset_sent: dict = {}


def _pw_fingerprint(user: User) -> str:
    return hashlib.sha256((user.hashed_password or "").encode()).hexdigest()[:16]


def reset_link(user: User) -> str:
    token = make_link_token(user.id, RESET_PURPOSE, f"{user.email}|{_pw_fingerprint(user)}", hours=1)
    return f"{APP_URL}/reset-password?token={token}"


class ForgotPasswordRequest(BaseModel):
    email: str


@app.post("/password/forgot")
def forgot_password(payload: ForgotPasswordRequest, background: BackgroundTasks,
                    session: Session = Depends(get_session)):
    """Always answers the same way, so it can't be used to find out who has an account."""
    email = payload.email.strip().lower()
    user = session.exec(select(User).where(func.lower(User.email) == email)).first()
    now = datetime.utcnow().timestamp()
    if user and now - _last_reset_sent.get(user.id, 0) >= RESEND_COOLDOWN_S:
        _last_reset_sent[user.id] = now
        background.add_task(send_reset_email, user.email, user.full_name, reset_link(user))
    return {"ok": True}


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


@app.post("/password/reset")
def reset_password(payload: ResetPasswordRequest, session: Session = Depends(get_session)):
    found = read_link_token(payload.token, RESET_PURPOSE)
    bad = HTTPException(status_code=400, detail="This reset link has expired or was already used. Ask for a new one.")
    if not found:
        raise bad
    user_id, stamp = found
    user = session.get(User, user_id)
    if not user or stamp != f"{(user.email or '').lower()}|{_pw_fingerprint(user)}":
        raise bad
    if len(payload.password) < MIN_PASSWORD_LEN:
        raise HTTPException(status_code=400, detail=f"Use at least {MIN_PASSWORD_LEN} characters for your password.")
    user.hashed_password = hash_password(payload.password)
    if not user.email_verified:
        user.email_verified = True
        user.email_verified_at = datetime.utcnow()
    session.add(user)
    session.commit()
    return {"user_id": str(user.id), "token": make_token(user.id)}


# ---------------------------------------------------------------------------
# Delete account: removes the user and everything linked to them.
# Run-together groups they own pass to another member, or are removed if empty.
# ---------------------------------------------------------------------------

def delete_user_everything(session: Session, user_id: UUID) -> None:
    p = {"uid": user_id}
    for table in ("recommendation", "run", "checkin", "injury", "favoriteroute", "run_group_member"):
        session.exec(text(f"DELETE FROM {table} WHERE user_id = :uid"), params=p)
    for (gid,) in session.exec(text("SELECT id FROM run_group WHERE owner_id = :uid"), params=p).all():
        heir = session.exec(text("SELECT user_id FROM run_group_member WHERE group_id = :g ORDER BY joined_at LIMIT 1"),
                            params={"g": gid}).first()
        if heir:
            session.exec(text("UPDATE run_group SET owner_id = :u WHERE id = :g"), params={"u": heir[0], "g": gid})
        else:
            session.exec(text("DELETE FROM run_group WHERE id = :g"), params={"g": gid})
    session.exec(text('DELETE FROM "user" WHERE id = :uid'), params=p)
    session.commit()


class DeleteAccountRequest(BaseModel):
    password: str


@app.post("/me/delete")
def delete_my_account(payload: DeleteAccountRequest, session: Session = Depends(get_session),
                      me: UUID = Depends(current_user)):
    user = session.get(User, me)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=403, detail="That password isn't right.")
    delete_user_everything(session, me)
    return {"ok": True}


@app.get("/health")
def health():
    """Tiny endpoint for uptime monitors (keeps the free Render service awake)."""
    return {"ok": True}
