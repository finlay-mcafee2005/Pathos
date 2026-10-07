import re
from uuid import UUID
from datetime import date, timedelta
import json
from sqlalchemy import text

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, create_engine, select
from geoalchemy2.shape import to_shape
from datetime import date as date_type
from pydantic import BaseModel
from app.geocoding import geocode_address
from app.conditions import fetch_conditions
from app.directions import directions_for
from app.activity_import import parse_activity, match_route, ImportProblem
import base64
from zoneinfo import ZoneInfo
from typing import List, Literal, Optional
from app.models import User, Checkin, Route, Injury, Run, Club, ClubSchedule, FavoriteRoute
from app.auth import hash_password, verify_password

from app.scoring.engine import recommend, diversify
from app.scoring.converters import (
    build_user_profile, build_daily_checkin,
    build_recent_runs, build_route_candidates,
)
from app.scoring.route_combiner import generate_combined_routes
from app.scoring.engine import build_personal_context, DailyCheckin, normalize_body_part, LOWER_BODY_PARTS
from app.scoring.groups import GroupSession, RunnerToday, match_groups, best_for_today, KM_PER_MI

DATABASE_URL = "postgresql://postgres:devpassword@localhost:5432/run_recommender"
engine = create_engine(DATABASE_URL)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def add_new_columns():
    """create_all() won't add columns to tables that already exist, so add
    any new ones here. IF NOT EXISTS makes this safe to run every startup."""
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
                         ("max_heart_rate", "FLOAT"), ("source", "VARCHAR")]:
            conn.execute(text(f"ALTER TABLE run ADD COLUMN IF NOT EXISTS {col} {typ}"))


MAX_DISTANCE_KM = 15  # only consider routes within this radius of the user's home


def get_session():
    with Session(engine) as session:
        yield session


GENERATED_SUFFIX = re.compile(r"\s+-\s+\d+(\.\d+)?\s*km\s+(north|south|east|west)$", re.IGNORECASE)
GENERATED_KIND = [
    (" trail out-and-back", " Out-and-Back"),
    (" trail loop", " Trail Loop"),
    (" road loop", " Loop"),
]


def display_name(name: str) -> str:
    """Friendly card title. Generated routes are stored as e.g.
    'Occidental College road loop - 8 km south' (the scripts rely on that
    pattern to find and replace their own routes), but the card already
    shows distance and surface, so show 'Occidental College Loop'.
    Combined routes ('A + B') are cleaned part by part."""
    parts = []
    for part in name.split(" + "):
        part = GENERATED_SUFFIX.sub("", part)
        for old, new in GENERATED_KIND:
            if part.endswith(old):
                part = part[: -len(old)] + new
                break
        parts.append(part)
    return " + ".join(parts)


@app.get("/recommendations/{user_id}")
def get_recommendations(user_id: UUID, session: Session = Depends(get_session)):
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

    routes_query = text("""
        SELECT id FROM route
        WHERE ST_DWithin(
            ST_StartPoint(gps_path)::geography,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :max_distance_m
        )
    """)
    nearby_route_ids = session.exec(
        routes_query,
        params={
            "lon": user.longitude,
            "lat": user.latitude,
            "max_distance_m": effective_radius_km * 1000,
        },
    ).all()
    nearby_ids = [row[0] for row in nearby_route_ids]

    routes = session.exec(select(Route).where(Route.id.in_(nearby_ids))).all()

    if not routes:
        raise HTTPException(
            status_code=404,
            detail=f"No routes found within {effective_radius_km:.0f}km of your location",
        )

    user_profile = build_user_profile(session, user)
    daily_checkin = build_daily_checkin(checkin)
    daily_checkin.conditions = fetch_conditions(user.latitude, user.longitude, checkin.run_time or "now")
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
        combined_routes = generate_combined_routes(routes, checkin.planned_distance_km)
        if combined_routes:
            combined_candidates = build_route_candidates(combined_routes)
            combined_results = recommend(user_profile, daily_checkin, recent_runs, combined_candidates)
            for cr in combined_routes:
                route_by_id[str(cr.id)] = cr

            results = diversify(results + combined_results, 3,
                                surface_requested=bool(checkin.surface_preference))

    return [
        {
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
            "distance_km": r.route.distance_km,
            "elevation_gain_m": r.route.elevation_gain_m,
            "difficulty": r.difficulty,
            "surface_type": r.route.surface_type,
            "path": [
                [lat, lon]
                for lon, lat in (
                    route_by_id[r.route.id].coords
                    if hasattr(route_by_id[r.route.id], "coords")
                    else to_shape(route_by_id[r.route.id].gps_path).coords
                )
            ],
        }
        for r in results
    ]

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
    injuries: List[InjuryInput] = []
    club_join_code: Optional[str] = None


SIGNUP_COVERAGE_RADIUS_KM = 50  # generous radius allowing for driving-distance users


@app.post("/signup")
def signup(payload: SignupRequest, session: Session = Depends(get_session)):
    try:
        lat, lon = geocode_address(payload.address)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    nearby_check = session.exec(
        text("""
            SELECT COUNT(*) FROM route
            WHERE ST_DWithin(
                ST_StartPoint(gps_path)::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :max_distance_m
            )
        """),
        params={"lon": lon, "lat": lat, "max_distance_m": SIGNUP_COVERAGE_RADIUS_KM * 1000},
    ).first()

    if nearby_check[0] == 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"We don't currently have any routes within {SIGNUP_COVERAGE_RADIUS_KM}km "
                f"of this address. This app currently covers the Los Angeles area "
                f"(Glendale, Pasadena, Eagle Rock, and nearby foothills)."
            ),
        )

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

    return {"user_id": str(user.id)}

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


@app.post("/checkins")
def create_checkin(payload: CheckinRequest, session: Session = Depends(get_session)):
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
    user = session.exec(select(User).where(User.email == payload.email)).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"user_id": str(user.id)}

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


@app.post("/runs")
def log_run(payload: RunRequest, session: Session = Depends(get_session)):
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
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return {"run_id": str(run.id)}


MAX_IMPORT_BYTES = 15 * 1024 * 1024
LOCAL_TZ = ZoneInfo("America/Los_Angeles")


class ImportRunRequest(BaseModel):
    user_id: UUID
    filename: str
    data_base64: str          # the file's bytes, base64-encoded by the browser


@app.post("/runs/import")
def import_run_file(payload: ImportRunRequest, session: Session = Depends(get_session)):
    """Read a GPX / TCX / FIT export and return what it contains, plus the
    Pathos route it matches (if any). Doesn't save anything: the Log a run
    form is filled in and the user confirms."""
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
                WHERE ST_DWithin(gps_path::geography,
                                 ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, 1500)
            """),
            params={"lon": start_lon, "lat": start_lat},
        ).all()
        ids = [row[0] for row in nearby]
        if ids:
            candidates = []
            for r in session.exec(select(Route).where(Route.id.in_(ids))).all():
                path = [(lat, lon) for lon, lat in to_shape(r.gps_path).coords]
                candidates.append((str(r.id), display_name(r.name), path))
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
def get_my_club(user_id: UUID, session: Session = Depends(get_session)):
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
def get_conditions(user_id: UUID, session: Session = Depends(get_session)):
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
    return cond.to_dict() if cond else None


@app.get("/routes/{route_id}/path")
def get_route_path(route_id: UUID, session: Session = Depends(get_session)):
    """Full-resolution [lat, lon] path for one route (used for GPX export)."""
    route = session.get(Route, route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    return {
        "route_id": str(route.id),
        "route_name": display_name(route.name),
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
    }


@app.get("/groups/{user_id}")
def get_group_matches(user_id: UUID, session: Session = Depends(get_session)):
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

    sessions = []
    for club in session.exec(select(Club)).all():
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
def join_club(payload: JoinClubRequest, session: Session = Depends(get_session)):
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
def leave_club(user_id: UUID, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.club_id = None
    session.add(user)
    session.commit()
    return {"ok": True}


class DirectionsRequest(BaseModel):
    path: List[List[float]]     # [[lat, lon], ...] as it will be run (out-and-backs already doubled)


@app.post("/directions")
def get_directions(payload: DirectionsRequest):
    """Turn-by-turn cues for a path, from OSRM. Returns null if OSRM is down."""
    path = [(p[0], p[1]) for p in payload.path if len(p) >= 2]
    return directions_for(path)


@app.get("/runs/{user_id}")
def list_runs(user_id: UUID, session: Session = Depends(get_session)):
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
            "route_name": display_name(route.name) if route else None,
            "surface_type": route.surface_type if route else None,
            "distance_km": run.distance_km,
            "pace_min_km": run.pace_min_km,
            "rating": run.rating,
            "post_run_soreness": run.post_run_soreness,
        })
    return result


@app.get("/stats/{user_id}")
def get_stats(user_id: UUID, session: Session = Depends(get_session)):
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
    }


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
def list_favorites(user_id: UUID, session: Session = Depends(get_session)):
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
            "route_name": display_name(route.name),
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
def add_favorite(payload: FavoriteRequest, session: Session = Depends(get_session)):
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
def remove_favorite(user_id: UUID, route_id: UUID, session: Session = Depends(get_session)):
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

