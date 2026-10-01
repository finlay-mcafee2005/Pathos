"""
Rules-based scoring engine for route recommendations.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class UserProfile:
    fitness_level: str            # "beginner" | "intermediate" | "advanced"
    weekly_km_avg: float          # converted from the miles entered at signup
    active_injury_body_parts: List[str] = field(default_factory=list)

@dataclass
class DailyCheckin:
    energy_score: int              # 0-10
    sore_body_parts: List[str] = field(default_factory=list)
    wants_scenic: bool = False
    wants_adventure: bool = False
    planned_distance_km: Optional[float] = None
    sleep_hours: Optional[float] = None
    sleep_quality: Optional[int] = None   # 1 (poor) - 5 (great)
    surface_preference: Optional[str] = None  # "trail" | "road" | None (no preference)


@dataclass
class RecentRuns:
    last_7_days_km: float
    last_14_days_route_ids: List[str] = field(default_factory=list)
    avg_rating_by_route_id: dict = field(default_factory=dict)
    days_since_last_run_by_route_id: dict = field(default_factory=dict)


@dataclass
class RouteCandidate:
    id: str
    name: str
    distance_km: float
    elevation_gain_m: float
    difficulty: str                 # "easy" | "moderate" | "hard"
    surface_type: str = "unknown"   # "pavement" | "trail" | "track" | "mixed" | "unknown"
    scenic: bool = False
    is_loop: bool = False


@dataclass
class ScoredRoute:
    route: RouteCandidate
    score: float
    reasons: List[str]
    run_format: str = "single"      # "single" | "out_and_back" | "repeat"
    repeat_count: int = 1
    effective_distance_km: float = 0.0
    distance_matched: bool = True   # False only when a target was set and nothing matched
    # tie-breaker inputs (don't affect score, only ordering between equal scores)
    distance_error_km: float = 0.0
    days_since_last_run: Optional[int] = None   # None = never run
    avg_rating: Optional[float] = None
    breakdown: dict = field(default_factory=dict)   # component -> points


DIFFICULTY_RANK = {"easy": 0, "moderate": 1, "hard": 2}

ACCEPTABLE_DIFFICULTY_CEILING = {
    "beginner": "moderate",
    "intermediate": "hard",
    "advanced": "hard",
}


def passes_difficulty_gate(route: RouteCandidate, user: UserProfile) -> bool:
    ceiling = ACCEPTABLE_DIFFICULTY_CEILING.get(user.fitness_level, "easy")
    return DIFFICULTY_RANK[route.difficulty] <= DIFFICULTY_RANK[ceiling]


# ---------------------------------------------------------------------------
# Surface vs. body
# ---------------------------------------------------------------------------
# Soft, forgiving surfaces (dirt trail) reduce impact load on shins, knees,
# hips and lower back. Firm, even surfaces (pavement) give stable footing for
# ankles, calves, Achilles and feet, which uneven trail terrain stresses more.
# A track is both even and somewhat forgiving, so it strains neither group.
IMPACT_SENSITIVE_PARTS = {"shin", "knee", "hip", "lower_back"}
STABILITY_SENSITIVE_PARTS = {"ankle", "calf", "achilles", "foot"}

# How strongly each surface strains each group (mixed routes count for half).
SURFACE_STRAIN = {
    "pavement": {"impact": 1.0, "stability": 0.0},
    "trail":    {"impact": 0.0, "stability": 1.0},
    "mixed":    {"impact": 0.5, "stability": 0.5},
}

SORENESS_SURFACE_PENALTY = 30
INJURY_SURFACE_PENALTY = 50
FRIENDLY_SURFACE_BONUS = 5
SURFACE_PREFERENCE_BONUS = 20      # same weight as scenic: explicit preference
TIRED_TRAIL_PENALTY = 10           # inferred signal, stays below explicit ones

SURFACE_LABEL = {"pavement": "Road", "trail": "Trail", "track": "Track", "mixed": "Mixed-surface"}
SURFACE_NOUN = {"pavement": "pavement", "trail": "uneven trail", "mixed": "mixed terrain"}


def normalize_body_part(part: str) -> str:
    """'left_shin' -> 'shin', so muscle-map IDs and injury tags compare equally."""
    for prefix in ("left_", "right_"):
        if part.startswith(prefix):
            return part[len(prefix):]
    return part


def surface_strain(surface: str, parts: List[str]):
    """Return (strain weight 0-1, the body part it strains) for the worst
    affected part, or (0, None) if this surface doesn't stress any of them."""
    weights = SURFACE_STRAIN.get(surface)
    if not weights:
        return 0.0, None
    best_weight, best_part = 0.0, None
    for part in sorted({normalize_body_part(p) for p in parts}):
        if part in IMPACT_SENSITIVE_PARTS:
            w = weights["impact"]
        elif part in STABILITY_SENSITIVE_PARTS:
            w = weights["stability"]
        else:
            continue
        if w > best_weight:
            best_weight, best_part = w, part
    return best_weight, best_part


def surface_relief(surface: str, parts: List[str]) -> Optional[str]:
    """Return a sore part this surface is specifically gentle on, if any."""
    normalized = {normalize_body_part(p) for p in parts}
    if surface == "trail":
        hit = normalized & IMPACT_SENSITIVE_PARTS
    elif surface == "pavement":
        hit = normalized & STABILITY_SENSITIVE_PARTS
    elif surface == "track":
        hit = normalized & (IMPACT_SENSITIVE_PARTS | STABILITY_SENSITIVE_PARTS)
    else:
        hit = set()
    return sorted(hit)[0] if hit else None


def pretty_part(part: str) -> str:
    return part.replace("_", " ")


BASE_SCORE = 100.0

# ---------------------------------------------------------------------------
# Weights. Order of influence (largest first):
#   safety (soreness / injury vs. surface)
#   > explicit check-in choices (scenic, road/trail, adventure, planned distance)
#   > inferred readiness (energy, sleep, training load -> length & hilliness)
#   > history (novelty, past ratings)
# Every component below is a continuous scale rather than an on/off bonus,
# so two routes only tie if they really are equivalent on every signal.
# ---------------------------------------------------------------------------
W_SCENIC = 20
W_SURFACE_PREF = 20
W_ADVENTURE = 15
W_DISTANCE_MAX = 25          # perfect match to an explicit planned distance
W_DISTANCE_FLOOR = -15       # very far off
INFERRED_DISTANCE_SCALE = 0.6  # no planned distance -> length fit counts less
W_TERRAIN = 15               # hilliness suits today's readiness
W_TERRAIN_FLOOR = -10
W_NOVELTY = 8                # never run / not run in 30+ days
W_RATING_PER_STAR = 5        # around a neutral 3-star rating
W_OUT_AND_BACK = -2          # small nudge toward true loops
W_REPEAT_PER_LAP = -3        # each extra lap of a repeated loop
W_OVERLOAD = 15              # long route while mileage is well above average

FITNESS_HILL_FACTOR = {"beginner": 0.6, "intermediate": 1.0, "advanced": 1.4}
DEFAULT_TYPICAL_RUN_KM = {"beginner": 4.0, "intermediate": 7.0, "advanced": 10.0}
RUNS_PER_WEEK = 4
MAX_REPEATS = 3

LOWER_BODY_PARTS = {
    "quad", "hamstring", "glutes", "calf", "shin", "knee", "ankle",
    "hip", "achilles", "foot", "lower_back",
}


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def load_ratio(user: UserProfile, recent: RecentRuns) -> Optional[float]:
    """This week's km relative to the runner's usual week (1.0 = normal)."""
    if user.weekly_km_avg <= 0:
        return None
    return recent.last_7_days_km / user.weekly_km_avg


def readiness(user: UserProfile, checkin: DailyCheckin, recent: RecentRuns) -> float:
    """0 (run-down) .. 1 (fresh). Weighted blend of whatever signals we have."""
    signals = [(checkin.energy_score / 10, 1.0)]
    if checkin.sleep_hours is not None:
        signals.append((clamp((checkin.sleep_hours - 4) / 4), 1.5))   # 4h -> 0, 8h+ -> 1
    if checkin.sleep_quality is not None:
        signals.append(((checkin.sleep_quality - 1) / 4, 0.5))        # 1 -> 0, 5 -> 1
    ratio = load_ratio(user, recent)
    if ratio is not None:
        signals.append((clamp(1 - (ratio - 1) / 0.5), 0.75))          # <=1x -> 1, 1.5x -> 0
    r = sum(v * w for v, w in signals) / sum(w for _, w in signals)

    sore_legs = {normalize_body_part(p) for p in checkin.sore_body_parts} & LOWER_BODY_PARTS
    r -= 0.05 * min(len(sore_legs), 4)
    return clamp(r)


def typical_run_km(user: UserProfile) -> float:
    if user.weekly_km_avg > 0:
        return user.weekly_km_avg / RUNS_PER_WEEK
    return DEFAULT_TYPICAL_RUN_KM.get(user.fitness_level, 5.0)


def choose_format(route: RouteCandidate, target: float, max_repeats: int):
    """Best way to run this route to hit target km.
    Returns (diff_km, format, repeat_count, effective_km).
    Point-to-point routes are always out-and-back (running one-way would
    strand the runner); loops can be run once or repeated."""
    if not route.is_loop:
        d = route.distance_km * 2
        return abs(d - target), "out_and_back", 1, d
    best = (abs(route.distance_km - target), "single", 1, route.distance_km)
    if route.distance_km > 0:
        n = max(1, round(target / route.distance_km))
        if 1 < n <= max_repeats:
            d = route.distance_km * n
            if abs(d - target) < best[0]:
                best = (abs(d - target), "repeat", n, d)
    return best


def distance_points(err: float, tol: float) -> float:
    """Continuous: 25 at a perfect match, 10 at the edge of tolerance,
    then falling to -15 for routes far off the target."""
    if err <= tol:
        return W_DISTANCE_MAX - 15 * err / tol
    return max(W_DISTANCE_FLOOR, 10 - 10 * (err - tol) / tol)


def score_route(
    route: RouteCandidate,
    user: UserProfile,
    checkin: DailyCheckin,
    recent: RecentRuns,
) -> ScoredRoute:
    parts: dict = {}          # component -> points, returned for transparency
    reasons: List[str] = []

    def add(name: str, pts: float, reason: Optional[str] = None):
        if pts:
            parts[name] = parts.get(name, 0.0) + pts
        if reason:
            reasons.append(reason)

    surface = route.surface_type
    surface_label = SURFACE_LABEL.get(surface, "")
    ready = readiness(user, checkin, recent)

    # --- 1. safety: soreness / injury vs. surface -------------------------
    sore_weight, sore_part = surface_strain(surface, checkin.sore_body_parts)
    if sore_weight > 0:
        add("soreness", -SORENESS_SURFACE_PENALTY * sore_weight,
            f"Caution: {SURFACE_NOUN[surface]} is harder on your sore {pretty_part(sore_part)}")

    injury_weight, injury_part = surface_strain(surface, user.active_injury_body_parts)
    if injury_weight > 0:
        add("injury", -INJURY_SURFACE_PENALTY * injury_weight,
            f"Caution: {SURFACE_NOUN[surface]} strains your {pretty_part(injury_part)} injury")

    relief_part = surface_relief(surface, checkin.sore_body_parts + user.active_injury_body_parts)
    if relief_part and sore_weight == 0 and injury_weight == 0:
        add("surface_relief", FRIENDLY_SURFACE_BONUS,
            f"{surface_label} surface is easier on your {pretty_part(relief_part)}")

    # --- 2. explicit check-in choices --------------------------------------
    if checkin.wants_scenic and route.scenic:
        add("scenic", W_SCENIC, "Scenic route, as requested")

    if checkin.surface_preference:
        wanted = "pavement" if checkin.surface_preference == "road" else checkin.surface_preference
        if surface == wanted:
            add("surface_pref", W_SURFACE_PREF, f"{surface_label} route, as requested")
        elif surface == "mixed":
            add("surface_pref", W_SURFACE_PREF / 2, f"Partly {checkin.surface_preference}, as requested")

    days_since = recent.days_since_last_run_by_route_id.get(route.id)
    if checkin.wants_adventure and (days_since is None or days_since > 14) \
            and route.id not in recent.last_14_days_route_ids:
        add("adventure", W_ADVENTURE, "New route, as requested")

    # --- 3. distance fit (explicit target, or inferred from readiness) -----
    typical = typical_run_km(user)
    if checkin.planned_distance_km:
        target = checkin.planned_distance_km
        err, run_format, repeat_count, effective_distance = choose_format(route, target, MAX_REPEATS)
        tol = max(0.5, target * 0.25)
        distance_matched = err <= tol
        add("distance", distance_points(err, tol))
        if distance_matched:
            mi = effective_distance * 0.621371
            if run_format == "single":
                reasons.append("Close match to your planned distance")
            elif run_format == "out_and_back":
                reasons.append(f"Out-and-Back: {mi:.1f} mi")
            else:
                reasons.append(f"{repeat_count}x Loop: {mi:.1f} mi")
    else:
        # no plan: aim for a normal run, shorter when run-down, longer when fresh
        target = typical * (0.7 + 0.5 * ready)
        err, run_format, repeat_count, effective_distance = choose_format(route, target, 1)
        tol = max(0.8, target * 0.3)
        distance_matched = True
        pts = distance_points(err, tol) * INFERRED_DISTANCE_SCALE
        add("distance", pts, "Good length for how you're feeling today" if pts >= 10 else None)

    if run_format == "out_and_back":
        add("format", W_OUT_AND_BACK)
    elif run_format == "repeat":
        add("format", W_REPEAT_PER_LAP * (repeat_count - 1))

    # --- 4. terrain: hilliness vs. readiness and fitness ------------------
    if route.distance_km > 0:
        hill = route.elevation_gain_m / route.distance_km              # m of climb per km
        ideal = (5 + 35 * ready) * FITNESS_HILL_FACTOR.get(user.fitness_level, 1.0)
        scale = max(ideal, 15)
        pts = clamp(W_TERRAIN * (1 - abs(hill - ideal) / scale), W_TERRAIN_FLOOR, W_TERRAIN)
        reason = None
        if pts >= 8 and ready >= 0.7 and checkin.energy_score >= 7 and hill >= 20:
            reason = "Feeling fresh - good day for some climbing"
        elif pts >= 8 and ready < 0.45 and hill < 15:
            reason = "Gentle, flat route for an easy day"
        elif pts <= -5 and hill > ideal:
            reason = "Hillier than ideal for how you're feeling"
        add("terrain", pts, reason)

    # --- 5. training load: long route while mileage is high ---------------
    ratio = load_ratio(user, recent)
    if ratio is not None and ratio > 1.2:
        severity = clamp((ratio - 1.2) / 0.3)                         # 1.2x -> 0, 1.5x -> 1
        length = clamp(effective_distance / typical, 0, 1.5) / 1.5
        pts = -W_OVERLOAD * severity * length
        add("overload", pts,
            "Suggested: recovery pace (weekly mileage above average)" if pts <= -3 else None)

    # tired legs + uneven terrain = higher trip / roll risk, so lean toward even footing
    poorly_rested = (
        (checkin.sleep_hours is not None and checkin.sleep_hours < 6)
        or (checkin.sleep_quality is not None and checkin.sleep_quality <= 2)
    )
    if poorly_rested and surface in ("trail", "mixed"):
        add("footing", -TIRED_TRAIL_PENALTY * (1.0 if surface == "trail" else 0.5),
            "Suggested: even footing (poor sleep raises trip risk on trails)")

    # --- 6. history: novelty and past ratings -----------------------------
    add("novelty", W_NOVELTY if days_since is None else W_NOVELTY * clamp(days_since / 30))

    avg_rating = recent.avg_rating_by_route_id.get(route.id)
    if avg_rating is not None:
        add("rating", (avg_rating - 3) * W_RATING_PER_STAR,
            "You've rated this route highly before" if avg_rating >= 4 else None)

    score = round(BASE_SCORE + sum(parts.values()), 1)
    return ScoredRoute(
        route=route,
        score=score,
        reasons=reasons,
        run_format=run_format,
        repeat_count=repeat_count,
        effective_distance_km=effective_distance,
        distance_matched=distance_matched,
        distance_error_km=err if checkin.planned_distance_km else 0.0,
        days_since_last_run=days_since,
        avg_rating=avg_rating,
        breakdown={k: round(v, 1) for k, v in parts.items()},
    )

NEVER_RUN_DAYS = 10_000


def rank_key(s: ScoredRoute):
    """Sort key for ranking. Score decides first; equal scores are broken by:
      1. closest to the planned distance
      2. least recently run (never-run routes first) - keeps suggestions fresh
      3. highest past rating
      4. route id - so identical inputs always give identical order
    Score is rounded to 0.1 so float noise (e.g. 104.9999 vs 105.0) counts as a tie.
    Use with sort(key=rank_key) - ascending, best first."""
    days = s.days_since_last_run if s.days_since_last_run is not None else NEVER_RUN_DAYS
    rating = s.avg_rating if s.avg_rating is not None else 0.0
    return (
        -round(s.score, 1),
        round(s.distance_error_km, 2),
        -days,
        -rating,
        s.route.id,
    )


def recommend(
    user: UserProfile,
    checkin: DailyCheckin,
    recent: RecentRuns,
    candidates: List[RouteCandidate],
    top_n: int = 3,
) -> List[ScoredRoute]:
    eligible = [r for r in candidates if passes_difficulty_gate(r, user)]
    scored = [score_route(r, user, checkin, recent) for r in eligible]

    # Distance matching already happened inside score_route() with a
    # proportional tolerance, contributing to each route's score. We no
    # longer hard-filter non-matches out - instead, always rank every
    # eligible route and return the best top_n, even if none of them
    # are a great distance match. This guarantees the user always sees
    # up to top_n options rather than an empty or partial result.
    scored.sort(key=rank_key)
    return scored[:top_n]