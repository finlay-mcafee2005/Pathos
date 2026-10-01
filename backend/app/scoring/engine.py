"""
Rules-based scoring engine for route recommendations.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class UserProfile:
    fitness_level: str            # "beginner" | "intermediate" | "advanced"
    weekly_mileage_avg: float
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


def score_route(
    route: RouteCandidate,
    user: UserProfile,
    checkin: DailyCheckin,
    recent: RecentRuns,
) -> ScoredRoute:
    score = BASE_SCORE
    reasons: List[str] = []

    surface = route.surface_type
    surface_label = SURFACE_LABEL.get(surface, "")

    # --- soreness / injury vs. surface ---
    sore_weight, sore_part = surface_strain(surface, checkin.sore_body_parts)
    if sore_weight > 0:
        score -= SORENESS_SURFACE_PENALTY * sore_weight
        reasons.append(f"Caution: {SURFACE_NOUN[surface]} is harder on your sore {pretty_part(sore_part)}")

    injury_weight, injury_part = surface_strain(surface, user.active_injury_body_parts)
    if injury_weight > 0:
        score -= INJURY_SURFACE_PENALTY * injury_weight
        reasons.append(f"Caution: {SURFACE_NOUN[surface]} strains your {pretty_part(injury_part)} injury")

    relief_part = surface_relief(surface, checkin.sore_body_parts + user.active_injury_body_parts)
    if relief_part and sore_weight == 0 and injury_weight == 0:
        score += FRIENDLY_SURFACE_BONUS
        reasons.append(f"{surface_label} surface is easier on your {pretty_part(relief_part)}")

    # --- explicit user preferences (carry more weight than inferred mood signals) ---
    if checkin.wants_scenic and route.scenic:
        score += 20
        reasons.append("Scenic route, as requested")

    if checkin.surface_preference:
        wanted = "pavement" if checkin.surface_preference == "road" else checkin.surface_preference
        if surface == wanted:
            score += SURFACE_PREFERENCE_BONUS
            reasons.append(f"{surface_label} route, as requested")
        elif surface == "mixed":
            score += SURFACE_PREFERENCE_BONUS / 2
            reasons.append(f"Partly {checkin.surface_preference}, as requested")

    if checkin.wants_adventure and route.id not in recent.last_14_days_route_ids:
        score += 15
        reasons.append("New route, as requested")

    run_format = "single"
    repeat_count = 1
    effective_distance = route.distance_km

    if checkin.planned_distance_km:
        target = checkin.planned_distance_km
        tolerance = max(0.5, target * 0.25)

        # Option 1: run it as-is - only valid for true loops, since a
        # point-to-point route left "as-is" would strand the runner away
        # from their start. Point-to-point routes always start with an
        # impossibly large default diff, forcing them into out-and-back
        # (Option 2) instead.
        if route.is_loop:
            best_diff = abs(route.distance_km - target)
            best_format, best_count, best_dist = "single", 1, route.distance_km
        else:
            best_diff = float("inf")
            best_format, best_count, best_dist = "out_and_back", 1, route.distance_km * 2

        # Option 2: out-and-back (point-to-point routes only)
        if not route.is_loop:
            out_back_dist = route.distance_km * 2
            diff = abs(out_back_dist - target)
            if diff < best_diff:
                best_diff, best_format, best_count, best_dist = diff, "out_and_back", 1, out_back_dist

        # Option 3: repeat the loop N times (loop routes only), capped at a
        # sane number of reps - repeating a short loop many times is a worse
        # recommendation than a single longer route, even if the math is closer
        MAX_REPEATS = 3
        if route.is_loop and route.distance_km > 0:
            n = max(1, round(target / route.distance_km))
            if n <= MAX_REPEATS:
                repeat_dist = route.distance_km * n
                diff = abs(repeat_dist - target)
                if diff < best_diff:
                    best_diff, best_format, best_count, best_dist = diff, "repeat", n, repeat_dist

        run_format, repeat_count, effective_distance = best_format, best_count, best_dist

        distance_matched = True
        if best_diff <= tolerance:
            score += 15
            effective_distance_mi = effective_distance * 0.621371
            if run_format == "single":
                reasons.append("Close match to your planned distance")
            elif run_format == "out_and_back":
                reasons.append(f"Out-and-Back: {effective_distance_mi:.1f} mi")
            elif run_format == "repeat":
                reasons.append(f"{repeat_count}x Loop: {effective_distance_mi:.1f} mi")
        elif best_diff > tolerance * 3:
            score -= 10
            distance_matched = False
        else:
            distance_matched = False

    # --- mood / energy (inferred, secondary to explicit preferences) ---
    if checkin.energy_score < 4:
        if route.distance_km > user.weekly_mileage_avg / 7 * 1.3:
            score -= 15
        if route.difficulty == "easy":
            score += 5
    elif checkin.energy_score > 7:
        if route.difficulty in ("moderate", "hard"):
            score += 15
            reasons.append("High energy today - good day for a harder effort")

    # --- sleep (duration and quality, secondary signal like energy) ---
    if checkin.sleep_hours is not None:
        if checkin.sleep_hours < 4:
            if route.difficulty == "hard":
                score -= 25
            elif route.difficulty == "easy":
                score += 10
            reasons.append("Suggested: easier route (very little sleep)")
        elif checkin.sleep_hours < 6:
            if route.difficulty == "hard":
                score -= 10
            reasons.append("Suggested: lighter effort (limited sleep)")

    if checkin.sleep_quality is not None and checkin.sleep_quality <= 2:
        if route.difficulty == "hard":
            score -= 15
        reasons.append("Suggested: lighter effort (poor sleep quality)")

    # tired legs + uneven terrain = higher trip / roll risk, so lean toward even footing
    poorly_rested = (
        (checkin.sleep_hours is not None and checkin.sleep_hours < 6)
        or (checkin.sleep_quality is not None and checkin.sleep_quality <= 2)
    )
    if poorly_rested and surface in ("trail", "mixed"):
        score -= TIRED_TRAIL_PENALTY * (1.0 if surface == "trail" else 0.5)
        reasons.append("Suggested: even footing (poor sleep raises trip risk on trails)")

    # --- training load (overtraining guard) ---
    if recent.last_7_days_km > user.weekly_mileage_avg * 1.2:
        overage_ratio = recent.last_7_days_km / user.weekly_mileage_avg
        penalty = min(25, 10 * overage_ratio)
        score -= penalty
        reasons.append("Suggested: recovery pace (weekly mileage above average)")

    if route.id not in recent.last_14_days_route_ids:
        score += 5

    avg_rating = recent.avg_rating_by_route_id.get(route.id)
    if avg_rating is not None and avg_rating > 4:
        score += 10
        reasons.append("You've rated similar routes highly before")

    return ScoredRoute(
        route=route,
        score=score,
        reasons=reasons,
        run_format=run_format,
        repeat_count=repeat_count,
        effective_distance_km=effective_distance if checkin.planned_distance_km else route.distance_km,
        distance_matched=distance_matched if checkin.planned_distance_km else True,
        distance_error_km=best_diff if checkin.planned_distance_km else 0.0,
        days_since_last_run=recent.days_since_last_run_by_route_id.get(route.id),
        avg_rating=avg_rating,
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