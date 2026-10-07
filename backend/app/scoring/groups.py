"""
Group run matching: which club sessions this week fit this runner, and
does one fit *today* well enough to suggest it alongside solo routes.

Not social: it only reads club schedules, paces and locations.

fit score (roughly 0-100):
    pace          30  your usual pace sits inside the group's range
    level         20  experience level matches
    distance      20  session distance near what you'd run anyway
    proximity     15  meets close to home
    your club     10  a club you've joined
    today        +/-  meetup time matches when you're running; session
                      type vs how you feel (no workouts on a run-down day)
"""

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
LEVEL_RANK = {"beginner": 0, "intermediate": 1, "advanced": 2}
KM_PER_MI = 1.60934

# which meetup hours count as "when I'm running"
RUN_TIME_WINDOWS = {"morning": (5, 11), "midday": (11, 15), "evening": (15, 22)}

TODAY_MIN_FIT = 60          # below this, don't suggest it on the recommendations page


@dataclass
class GroupSession:
    club_id: str
    club_name: str
    location: str
    pace_range: str
    experience_level: str
    day_of_week: str
    meetup_time: str                   # "18:30"
    distance_mi: Optional[float] = None
    run_type: Optional[str] = None     # easy | long | workout | social
    surface: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    is_my_club: bool = False
    source_url: Optional[str] = None
    verified_on: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class GroupMatch:
    session: GroupSession
    starts_at: datetime
    fit: float
    reasons: List[str] = field(default_factory=list)
    cautions: List[str] = field(default_factory=list)
    is_today: bool = False
    distance_from_home_km: Optional[float] = None


@dataclass
class RunnerToday:
    fitness_level: str
    pace_min_mi: float                 # their usual pace
    typical_mi: float                  # their usual run length
    readiness: float = 0.6             # 0 run-down .. 1 fresh
    planned_mi: Optional[float] = None
    run_time: Optional[str] = None     # now | morning | midday | evening, if checked in today
    sore_legs: bool = False
    checked_in_today: bool = False
    home_lat: Optional[float] = None
    home_lon: Optional[float] = None


def parse_pace_range(text: str):
    """'7:30-9:00 min/mi' -> (7.5, 9.0)"""
    times = re.findall(r"(\d+):(\d{2})", text or "")
    if len(times) < 2:
        return None
    lo, hi = (int(m) + int(s) / 60 for m, s in times[:2])
    return (min(lo, hi), max(lo, hi))


def fmt_pace(p: float) -> str:
    m = int(p)
    s = round((p - m) * 60)
    if s == 60:
        m, s = m + 1, 0
    return f"{m}:{s:02d}"


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def next_occurrence(day: str, hhmm: str, now: datetime) -> Optional[datetime]:
    if day not in DAYS:
        return None
    try:
        h, m = (int(x) for x in hhmm.split(":")[:2])
    except ValueError:
        return None
    days_ahead = (DAYS.index(day) - now.weekday()) % 7
    t = (now + timedelta(days=days_ahead)).replace(hour=h, minute=m, second=0, microsecond=0)
    if t < now:          # already happened today -> next week
        t += timedelta(days=7)
    return t


def score_session(s: GroupSession, runner: RunnerToday, starts_at: datetime, now: datetime) -> GroupMatch:
    fit = 0.0
    reasons: List[str] = []
    cautions: List[str] = []

    # pace
    rng = parse_pace_range(s.pace_range)
    if rng:
        lo, hi = rng
        p = runner.pace_min_mi
        if lo <= p <= hi:
            fit += 30
            reasons.append(f"Your {fmt_pace(p)}/mi pace is right in their range")
        else:
            off = lo - p if p < lo else p - hi
            fit += max(-10, 30 - 25 * off)
            if p > hi:
                cautions.append(f"They usually run faster ({s.pace_range.split(' ')[0]}/mi)")
            elif off >= 0.75:
                cautions.append("You'd be one of the quicker runners")
    elif "all" in (s.pace_range or "").lower():
        fit += 25
        reasons.append("All paces welcome")
    elif "beginner" in (s.pace_range or "").lower():
        fit += 30 if runner.fitness_level == "beginner" else 12
    else:
        fit += 15

    # experience level
    if s.experience_level == "all":
        fit += 20
    else:
        gap = abs(LEVEL_RANK.get(s.experience_level, 1) - LEVEL_RANK.get(runner.fitness_level, 1))
        fit += {0: 20, 1: 8}.get(gap, -10)
        if gap == 0:
            reasons.append(f"Built for {s.experience_level} runners like you")

    # distance
    target = runner.planned_mi or runner.typical_mi
    if s.distance_mi and target:
        err = abs(s.distance_mi - target) / max(target, 1)
        fit += max(-5, 20 - 30 * err)
        if err <= 0.2:
            reasons.append(f"About {s.distance_mi:g} mi, close to your usual run")
        elif s.distance_mi > target * 1.5:
            cautions.append(f"Longer than you usually go ({s.distance_mi:g} mi)")
    else:
        fit += 10

    # proximity
    dist_km = None
    if None not in (s.lat, s.lon, runner.home_lat, runner.home_lon):
        dist_km = haversine_km(runner.home_lat, runner.home_lon, s.lat, s.lon)
        fit += 15 * max(0.0, 1 - max(dist_km - 2, 0) / 18)    # full credit within 2 km, 0 at 20 km
        if dist_km <= 3:
            reasons.append("Meets close to home")
    else:
        fit += 7

    if s.is_my_club:
        fit += 10
        reasons.append("Your club")

    # today: timing and how you feel
    is_today = starts_at.date() == now.date()
    if is_today and runner.checked_in_today:
        rt = runner.run_time or "now"
        if rt.startswith("tomorrow_"):
            rt = "never"          # running tomorrow, so no session today is "when you planned"
        hour = starts_at.hour + starts_at.minute / 60
        if rt == "now":
            in_window = 0 <= (starts_at - now).total_seconds() / 3600 <= 2
        else:
            a, b = RUN_TIME_WINDOWS.get(rt, (0, 0))
            in_window = a <= hour < b
        if in_window:
            fit += 10
            reasons.append("Meets right when you planned to run")
        else:
            fit -= 10

        if s.run_type in ("workout", "long") and runner.readiness < 0.45:
            fit -= 20
            cautions.append(f"A {s.run_type} is a lot for how you're feeling today")
        elif s.run_type in ("easy", "social") and runner.readiness < 0.45:
            fit += 5
            reasons.append("An easy group pace suits a low-energy day")
        if runner.sore_legs and s.run_type == "workout":
            fit -= 10
            cautions.append("Workouts are hard on sore legs")
        if s.run_type == "workout" and runner.readiness >= 0.7:
            fit += 5
            reasons.append("You're fresh - a good day for a workout")

    return GroupMatch(session=s, starts_at=starts_at, fit=round(max(0.0, min(100.0, fit)), 1),
                      reasons=reasons, cautions=cautions, is_today=is_today,
                      distance_from_home_km=round(dist_km, 1) if dist_km is not None else None)


def match_groups(sessions: List[GroupSession], runner: RunnerToday,
                 now: Optional[datetime] = None) -> List[GroupMatch]:
    """Every session in the next 7 days, best fit first."""
    now = now or datetime.now()
    matches = []
    for s in sessions:
        t = next_occurrence(s.day_of_week, s.meetup_time, now)
        if t is not None:
            matches.append(score_session(s, runner, t, now))
    return sorted(matches, key=lambda m: (-m.fit, m.starts_at))


def best_for_today(matches: List[GroupMatch]) -> Optional[GroupMatch]:
    today = [m for m in matches if m.is_today and m.fit >= TODAY_MIN_FIT]
    return max(today, key=lambda m: m.fit) if today else None
