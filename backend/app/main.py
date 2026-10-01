from uuid import UUID
from datetime import date
import json
from sqlalchemy import text

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, create_engine, select
from geoalchemy2.shape import to_shape
from datetime import date as date_type
from pydantic import BaseModel
from app.geocoding import geocode_address
from typing import List, Literal, Optional
from app.models import User, Checkin, Route, Injury, Run, Club, ClubSchedule
from app.auth import hash_password, verify_password

from app.scoring.engine import recommend, diversify
from app.scoring.converters import (
    build_user_profile, build_daily_checkin,
    build_recent_runs, build_route_candidates,
)
from app.scoring.route_combiner import generate_combined_routes

DATABASE_URL = "postgresql://postgres:devpassword@localhost:5432/run_recommender"
engine = create_engine(DATABASE_URL)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_DISTANCE_KM = 15  # only consider routes within this radius of the user's home


def get_session():
    with Session(engine) as session:
        yield session


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
            "route_name": r.route.name,
            "score": r.score,
            "score_breakdown": r.breakdown,
            "estimated_minutes": r.estimated_minutes,
            "run_format": r.run_format,
            "effective_distance_km": round(r.effective_distance_km, 2),
            "reasons": r.reasons,
            "distance_km": r.route.distance_km,
            "elevation_gain_m": r.route.elevation_gain_m,
            "difficulty": r.route.difficulty,
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
        mood_note=payload.mood_note,
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


@app.post("/runs")
def log_run(payload: RunRequest, session: Session = Depends(get_session)):
    run = Run(
        user_id=payload.user_id,
        route_id=payload.route_id,
        run_date=date_type.today(),
        distance_km=payload.distance_km,
        pace_min_km=payload.pace_min_km,
        rating=payload.rating,
        post_run_soreness=payload.post_run_soreness,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return {"run_id": str(run.id)}


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