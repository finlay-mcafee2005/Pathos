"""
Personalization layer.

Turns a runner's own history into signals for the scoring engine, so two
runners who submit identical check-ins still get different recommendations:

  TasteProfile     what kinds of routes they rate highly (surface, scenery,
                   loops, hilliness, length) - learned from rated runs
  RecoveryProfile  how their body responds - e.g. sorer after hilly or
                   pavement runs - learned from post-run soreness
  RhythmContext    where they are in their week - hard run yesterday,
                   several days in a row, or well rested
  GOAL_PROFILES    how their signup goal shifts the trade-offs

Everything here is plain Python with no database access, so it can be unit
tested directly (see scripts/test_scoring.py).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from math import radians, sin, cos, asin, sqrt
from statistics import median
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Input: one past run, joined with the features of the route it was on
# ---------------------------------------------------------------------------

@dataclass
class RunRecord:
    run_date: date
    distance_km: float
    pace_min_km: Optional[float] = None
    rating: Optional[int] = None             # 1-5
    post_run_soreness: Optional[int] = None  # 0-10
    route_id: Optional[str] = None
    surface_type: Optional[str] = None
    hill_m_per_km: Optional[float] = None
    scenic: Optional[bool] = None
    is_loop: Optional[bool] = None


HALF_LIFE_DAYS = 45          # a run from 45 days ago counts half as much as today's
MIN_RATED_RUNS = 3           # below this, no taste profile at all
CONFIDENCE_SHRINK = 5        # confidence = n / (n + 5): 3 runs -> 0.38, 15 -> 0.75


def recency_weight(run_date: date, today: date) -> float:
    age = max((today - run_date).days, 0)
    return 0.5 ** (age / HALF_LIFE_DAYS)


def weighted_mean(pairs) -> Optional[float]:
    pairs = list(pairs)
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return None
    return sum(v * w for v, w in pairs) / total_w


def shrink(value: float, n: int, k: float = 2) -> float:
    """Pull small-sample estimates toward 0 (no opinion)."""
    return value * n / (n + k)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


# ---------------------------------------------------------------------------
# Taste: what they rate highly
# ---------------------------------------------------------------------------

@dataclass
class TasteProfile:
    n_rated: int = 0
    confidence: float = 0.0                                  # 0..1
    surface_affinity: Dict[str, float] = field(default_factory=dict)  # ~ -2..+2
    scenic_affinity: float = 0.0       # rating gap: scenic minus non-scenic
    loop_affinity: float = 0.0         # rating gap: loops minus out-and-backs
    preferred_hill: Optional[float] = None         # m/km of routes they loved
    preferred_distance_km: Optional[float] = None


def build_taste_profile(history: List[RunRecord], today: date) -> TasteProfile:
    rated = [r for r in history if r.rating is not None and r.surface_type is not None]
    profile = TasteProfile(n_rated=len(rated))
    if len(rated) < MIN_RATED_RUNS:
        return profile
    profile.confidence = len(rated) / (len(rated) + CONFIDENCE_SHRINK)

    # Center ratings on the runner's own average: someone who rates every
    # run a 4 isn't "loving" everything, they're just a generous rater.
    w = {id(r): recency_weight(r.run_date, today) for r in rated}
    mean_rating = weighted_mean((r.rating, w[id(r)]) for r in rated)

    def centered(r):
        return r.rating - mean_rating

    by_surface: Dict[str, list] = {}
    for r in rated:
        by_surface.setdefault(r.surface_type, []).append((centered(r), w[id(r)]))
    profile.surface_affinity = {
        s: shrink(weighted_mean(v), len(v), k=1) for s, v in by_surface.items()
    }

    def gap(flag):
        yes = [(centered(r), w[id(r)]) for r in rated if getattr(r, flag) is True]
        no = [(centered(r), w[id(r)]) for r in rated if getattr(r, flag) is False]
        if not yes or not no:
            return 0.0
        return shrink(weighted_mean(yes) - weighted_mean(no), min(len(yes), len(no)))

    profile.scenic_affinity = gap("scenic")
    profile.loop_affinity = gap("is_loop")

    # Hilliness / length of the runs they rated above their own average
    liked = [r for r in rated if centered(r) > 0.25]
    if liked:
        lw = [(r, w[id(r)] * centered(r)) for r in liked]
        hills = [(r.hill_m_per_km, wt) for r, wt in lw if r.hill_m_per_km is not None]
        if hills:
            profile.preferred_hill = weighted_mean(hills)
        profile.preferred_distance_km = weighted_mean((r.distance_km, wt) for r, wt in lw)
    return profile


# ---------------------------------------------------------------------------
# Recovery: how their body responds
# ---------------------------------------------------------------------------

HILLY_M_PER_KM = 25
FLAT_M_PER_KM = 15


@dataclass
class RecoveryProfile:
    hill_tolerance: float = 1.0        # multiplier on ideal hilliness (0.6 .. 1.2)
    hill_reason: Optional[str] = None
    surface_soreness: Dict[str, float] = field(default_factory=dict)  # surface -> extra soreness vs. their norm


def build_recovery_profile(history: List[RunRecord], today: date) -> RecoveryProfile:
    logged = [r for r in history if r.post_run_soreness is not None]
    profile = RecoveryProfile()
    if len(logged) < 3:
        return profile
    w = {id(r): recency_weight(r.run_date, today) for r in logged}
    base = weighted_mean((r.post_run_soreness, w[id(r)]) for r in logged)

    hilly = [(r.post_run_soreness, w[id(r)]) for r in logged
             if r.hill_m_per_km is not None and r.hill_m_per_km >= HILLY_M_PER_KM]
    flat = [(r.post_run_soreness, w[id(r)]) for r in logged
            if r.hill_m_per_km is not None and r.hill_m_per_km < FLAT_M_PER_KM]
    if len(hilly) >= 2 and len(flat) >= 2:
        hill_gap = weighted_mean(hilly) - weighted_mean(flat)
        if hill_gap > 1.5:
            profile.hill_tolerance = max(0.6, 1 - 0.08 * hill_gap)
            profile.hill_reason = "Kept it flatter - your legs have been sorer after hilly runs"
        elif hill_gap < -1:
            profile.hill_tolerance = min(1.2, 1 + 0.05 * -hill_gap)

    by_surface: Dict[str, list] = {}
    for r in logged:
        if r.surface_type:
            by_surface.setdefault(r.surface_type, []).append((r.post_run_soreness, w[id(r)]))
    profile.surface_soreness = {
        s: shrink(weighted_mean(v) - base, len(v)) for s, v in by_surface.items() if len(v) >= 2
    }
    return profile


# ---------------------------------------------------------------------------
# Rhythm: where they are in their training week
# ---------------------------------------------------------------------------

@dataclass
class RhythmContext:
    readiness_delta: float = 0.0
    reason: Optional[str] = None
    days_since_last_run: Optional[int] = None
    streak_days: int = 0
    median_pace: Optional[float] = None
    recent_median_km: Optional[float] = None
    recovery_day: bool = False      # hard effort yesterday or a long streak


def build_rhythm(history: List[RunRecord], today: date, typical_km: float) -> RhythmContext:
    ctx = RhythmContext()
    if not history:
        return ctx
    paces = [r.pace_min_km for r in history if r.pace_min_km]
    ctx.median_pace = median(paces) if paces else None
    recent = sorted((r for r in history if (today - r.run_date).days <= 28),
                    key=lambda r: r.run_date, reverse=True)[:10]
    if len(recent) >= 3:
        ctx.recent_median_km = median(r.distance_km for r in recent)

    last = max(history, key=lambda r: r.run_date)
    ctx.days_since_last_run = (today - last.run_date).days

    run_days = {r.run_date for r in history}
    day = today if today in run_days else today - timedelta(days=1)
    while day in run_days:
        ctx.streak_days += 1
        day -= timedelta(days=1)

    hard = (
        last.distance_km >= 1.3 * typical_km
        or (last.pace_min_km and ctx.median_pace and last.pace_min_km < 0.95 * ctx.median_pace)
        or (last.post_run_soreness or 0) >= 6
    )
    if ctx.days_since_last_run <= 1 and hard:
        ctx.readiness_delta -= 0.2
        ctx.reason = "Easier day after yesterday's hard effort"
        ctx.recovery_day = True
    if ctx.streak_days >= 4:
        ctx.readiness_delta -= 0.10
        ctx.reason = ctx.reason or f"Day {ctx.streak_days + 1} in a row - keeping it manageable"
        ctx.recovery_day = True
    if ctx.days_since_last_run >= 4:
        ctx.readiness_delta += 0.05
    return ctx


# ---------------------------------------------------------------------------
# Goals: how the signup goal shifts trade-offs
# ---------------------------------------------------------------------------

GOAL_PROFILES = {
    # precise distances, steady surfaces, longer weekend runs, less novelty-chasing
    "race_training": dict(distance_weight=1.3, weekend_long_run=1.35, hill_factor=1.0,
                          novelty_weight=0.6, steady_surface_bonus=3, scenic_bonus=0),
    # variety keeps it fun
    "general_fitness": dict(distance_weight=1.0, weekend_long_run=1.15, hill_factor=1.0,
                            novelty_weight=1.5, steady_surface_bonus=0, scenic_bonus=0),
    # sustainable effort and enjoyable routes support consistency
    "weight_loss": dict(distance_weight=1.0, weekend_long_run=1.2, hill_factor=0.8,
                        novelty_weight=1.0, steady_surface_bonus=0, scenic_bonus=3),
}

SEVERITY_MULTIPLIER = {"mild": 0.6, "moderate": 1.0, "severe": 1.5}
DEFAULT_PACE_MIN_KM = {"beginner": 7.0, "intermediate": 6.0, "advanced": 5.0}
