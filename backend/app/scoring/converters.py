"""
Converts SQLModel database rows into the plain dataclasses
the scoring engine (engine.py) expects. Keeps the scoring
engine itself free of any database dependency.
"""
import json
from datetime import date, timedelta
from typing import List

from sqlmodel import Session, select

from app.models import User, Checkin, Run, Route, Injury
from app.scoring.engine import (
    UserProfile, DailyCheckin, RecentRuns, RouteCandidate,
)


def build_user_profile(session: Session, user: User) -> UserProfile:
    active_injuries = session.exec(
        select(Injury).where(
            Injury.user_id == user.id,
            Injury.resolved_at == None,  # noqa: E711
        )
    ).all()
    return UserProfile(
        fitness_level=user.fitness_level,
        weekly_mileage_avg=user.weekly_mileage_avg,
        active_injury_body_parts=[i.body_part for i in active_injuries],
    )


def build_daily_checkin(checkin: Checkin) -> DailyCheckin:
    sore_parts = json.loads(checkin.sore_body_parts) if checkin.sore_body_parts else []
    return DailyCheckin(
        energy_score=checkin.energy_score,
        sore_body_parts=sore_parts,
        wants_scenic=checkin.wants_scenic,
        wants_adventure=checkin.wants_adventure,
        planned_distance_km=checkin.planned_distance_km,
        sleep_hours=checkin.sleep_hours,
        sleep_quality=checkin.sleep_quality,
        surface_preference=checkin.surface_preference,
    )


def build_recent_runs(session: Session, user_id) -> RecentRuns:
    seven_days_ago = date.today() - timedelta(days=7)
    fourteen_days_ago = date.today() - timedelta(days=14)

    recent = session.exec(
        select(Run).where(Run.user_id == user_id, Run.run_date >= seven_days_ago)
    ).all()
    last_7_days_km = sum(r.distance_km for r in recent)

    last_14 = session.exec(
        select(Run).where(Run.user_id == user_id, Run.run_date >= fourteen_days_ago)
    ).all()
    last_14_route_ids = [str(r.route_id) for r in last_14 if r.route_id]

    all_runs = session.exec(select(Run).where(Run.user_id == user_id)).all()
    ratings_by_route: dict = {}
    for r in all_runs:
        if r.route_id and r.rating is not None:
            ratings_by_route.setdefault(str(r.route_id), []).append(r.rating)
    avg_rating_by_route_id = {
        rid: sum(ratings) / len(ratings) for rid, ratings in ratings_by_route.items()
    }

    last_run_date: dict = {}
    for r in all_runs:
        if r.route_id and r.run_date:
            rid = str(r.route_id)
            if rid not in last_run_date or r.run_date > last_run_date[rid]:
                last_run_date[rid] = r.run_date
    days_since_last_run_by_route_id = {
        rid: (date.today() - d).days for rid, d in last_run_date.items()
    }

    return RecentRuns(
        last_7_days_km=last_7_days_km,
        last_14_days_route_ids=last_14_route_ids,
        avg_rating_by_route_id=avg_rating_by_route_id,
        days_since_last_run_by_route_id=days_since_last_run_by_route_id,
    )


def is_loop_route(route, threshold_km: float = 0.15) -> bool:
    """A route is a loop if its start and end points are close together.
    Works for both real SQLModel Route objects and synthetic combined routes."""
    from math import radians, sin, cos, sqrt, atan2

    if hasattr(route, "coords"):
        coords = route.coords
    else:
        from geoalchemy2.shape import to_shape
        coords = list(to_shape(route.gps_path).coords)

    if len(coords) < 2:
        return False

    lon1, lat1 = coords[0]
    lon2, lat2 = coords[-1]

    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    distance_km = R * 2 * atan2(sqrt(a), sqrt(1 - a))

    return distance_km <= threshold_km


def build_route_candidates(routes: List[Route]) -> List[RouteCandidate]:
    return [
        RouteCandidate(
            id=str(r.id),
            name=r.name,
            distance_km=r.distance_km,
            elevation_gain_m=r.elevation_gain_m,
            difficulty=r.difficulty,
            surface_type=getattr(r, "surface_type", None) or "unknown",
            scenic=r.scenic,
            is_loop=is_loop_route(r),
        )
        for r in routes
    ]