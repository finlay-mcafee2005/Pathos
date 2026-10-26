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
    climb_per_km,
    UserProfile, DailyCheckin, RecentRuns, RouteCandidate,
)
from app.scoring.personalization import RunRecord


def build_user_profile(session: Session, user: User) -> UserProfile:
    active_injuries = session.exec(
        select(Injury).where(
            Injury.user_id == user.id,
            Injury.resolved_at == None,  # noqa: E711
        )
    ).all()
    return UserProfile(
        fitness_level=user.fitness_level,
        weekly_km_avg=(user.weekly_mileage_avg or 0) * 1.60934,  # signup asks for miles
        active_injury_body_parts=[i.body_part for i in active_injuries],
        injury_severity={i.body_part: i.severity for i in active_injuries},
        goal=user.goal or "general_fitness",
        home_lat=user.latitude,
        home_lon=user.longitude,
        usual_pace_min_km=getattr(user, "usual_pace_min_km", None),
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
        willing_to_drive_km=checkin.willing_to_drive_km,
        run_time=getattr(checkin, "run_time", None),
        available_minutes=getattr(checkin, "available_minutes", None),
        mood=getattr(checkin, "mood", None),
        run_intent=getattr(checkin, "run_intent", None),
        hills_pref=getattr(checkin, "hills_pref", None),
        quiet_streets=bool(getattr(checkin, "quiet_streets", False)),
        no_laps=bool(getattr(checkin, "no_laps", False)),
        shape_pref=getattr(checkin, "shape_pref", None),
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

    # full history joined with route features, for the personalization layer
    route_ids = {r.route_id for r in all_runs if r.route_id}
    routes_by_id = {}
    if route_ids:
        routes_by_id = {
            rt.id: rt for rt in session.exec(select(Route).where(Route.id.in_(route_ids))).all()
        }
    history = []
    for r in all_runs:
        rt = routes_by_id.get(r.route_id)
        history.append(RunRecord(
            run_date=r.run_date,
            distance_km=r.distance_km,
            pace_min_km=r.pace_min_km,
            rating=r.rating,
            post_run_soreness=r.post_run_soreness,
            route_id=str(r.route_id) if r.route_id else None,
            surface_type=rt.surface_type if rt else None,
            hill_m_per_km=climb_per_km(rt.distance_km, rt.elevation_gain_m,
                                       getattr(rt, "elevation_loss_m", None)) if rt and rt.distance_km else None,
            scenic=rt.scenic if rt else None,
            is_loop=is_loop_route(rt) if rt else None,
        ))

    return RecentRuns(
        history=history,
        last_7_days_km=last_7_days_km,
        last_14_days_route_ids=last_14_route_ids,
        avg_rating_by_route_id=avg_rating_by_route_id,
        days_since_last_run_by_route_id=days_since_last_run_by_route_id,
    )


def is_loop_route(route, threshold_km: float = 0.15) -> bool:
    """A route is a loop if its start and end points are close together.
    Works for both real SQLModel Route objects and synthetic combined routes."""
    from math import radians, sin, cos, sqrt, atan2

    from app.scoring.route_combiner import get_route_coords   # cached geometry
    coords = get_route_coords(route)

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


def route_start(route):
    """(lat, lon) of the first point, for real Routes and combined routes."""
    from app.scoring.route_combiner import get_route_coords   # cached geometry
    coords = get_route_coords(route)
    if not coords:
        return None, None
    lon, lat = coords[0][0], coords[0][1]
    return lat, lon


def build_route_candidates(routes: List[Route]) -> List[RouteCandidate]:
    return [
        RouteCandidate(
            id=str(r.id),
            name=getattr(r, "nickname", None) or r.name,
            distance_km=r.distance_km,
            elevation_gain_m=r.elevation_gain_m,
            difficulty=r.difficulty,
            surface_type=getattr(r, "surface_type", None) or "unknown",
            scenic=r.scenic,
            is_loop=is_loop_route(r),
            start_lat=route_start(r)[0],
            start_lon=route_start(r)[1],
            shade=getattr(r, "shade_pct", None),
            scenic_pct=getattr(r, "scenic_pct", None),
            busy_pct=getattr(r, "busy_pct", None),
            freeway_crossings=getattr(r, "freeway_crossings", None),
            downtown_pct=getattr(r, "downtown_pct", None),
            turns_per_km=getattr(r, "turns_per_km", None),
            stem_km=getattr(r, "stem_km", None),
            steepest_grade=getattr(r, "steepest_grade", None),
            elevation_loss_m=getattr(r, "elevation_loss_m", None),
        )
        for r in routes
    ]