"""
Rules-based scoring engine for route recommendations.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from typing import List, Optional

from app.scoring.personalization import (
    RunRecord, TasteProfile, RecoveryProfile, RhythmContext,
    build_taste_profile, build_recovery_profile, build_rhythm,
    haversine_km, GOAL_PROFILES, SEVERITY_MULTIPLIER, DEFAULT_PACE_MIN_KM,
)


@dataclass
class UserProfile:
    fitness_level: str            # "beginner" | "intermediate" | "advanced"
    weekly_km_avg: float          # converted from the miles entered at signup
    active_injury_body_parts: List[str] = field(default_factory=list)
    injury_severity: dict = field(default_factory=dict)   # body_part -> "mild" | "moderate" | "severe"
    goal: str = "general_fitness"  # "race_training" | "general_fitness" | "weight_loss"
    home_lat: Optional[float] = None
    home_lon: Optional[float] = None

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
    willing_to_drive_km: Optional[float] = None
    today: Optional[date] = None              # defaults to date.today(); set in tests


@dataclass
class RecentRuns:
    last_7_days_km: float
    last_14_days_route_ids: List[str] = field(default_factory=list)
    avg_rating_by_route_id: dict = field(default_factory=dict)
    days_since_last_run_by_route_id: dict = field(default_factory=dict)
    history: List[RunRecord] = field(default_factory=list)   # all past runs + route features


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
    start_lat: Optional[float] = None
    start_lon: Optional[float] = None


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
    base_score: float = 0.0                          # score before the variety adjustment
    estimated_minutes: Optional[float] = None


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

W_PROXIMITY = 8               # starts at home -> fades to 0 at the search radius
DEFAULT_RADIUS_KM = 15
W_TASTE_SURFACE = 8           # x surface affinity (~ -2..+2), capped at +/-10
W_TASTE_SCENIC = 2
W_TASTE_LOOP = 1.5
W_VARIETY = 10                # max penalty for a pick nearly identical to one above it

FITNESS_HILL_FACTOR = {"beginner": 0.6, "intermediate": 1.0, "advanced": 1.4}
DEFAULT_TYPICAL_RUN_KM = {"beginner": 4.0, "intermediate": 7.0, "advanced": 10.0}
RUNS_PER_WEEK = 4
MAX_REPEATS = 3
FLAT_HILL_M_PER_KM = 15

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


@dataclass
class PersonalContext:
    """Everything about this runner today that doesn't depend on the route.
    Built once per recommendation request, shared by every route's scoring."""
    today: date
    readiness: float
    typical_km: float
    taste: TasteProfile
    recovery: RecoveryProfile
    rhythm: RhythmContext
    pace_min_km: float
    long_run_factor: float = 1.0
    long_run_reason: Optional[str] = None


def build_personal_context(user: UserProfile, checkin: DailyCheckin,
                           recent: RecentRuns) -> PersonalContext:
    today = checkin.today or date.today()
    goal = GOAL_PROFILES.get(user.goal, GOAL_PROFILES["general_fitness"])
    taste = build_taste_profile(recent.history, today)
    recovery = build_recovery_profile(recent.history, today)

    # "normal run" = signup mileage, blended toward what they actually run lately
    typical = typical_run_km(user)
    rhythm = build_rhythm(recent.history, today, typical)
    if rhythm.recent_median_km:
        typical = 0.5 * typical + 0.5 * rhythm.recent_median_km
    if taste.preferred_distance_km and taste.confidence:
        typical = (1 - 0.5 * taste.confidence) * typical + 0.5 * taste.confidence * taste.preferred_distance_km

    ready = clamp(readiness(user, checkin, recent) + rhythm.readiness_delta)

    long_run_factor, long_run_reason = 1.0, None
    if today.weekday() >= 5 and ready >= 0.5 and not rhythm.reason:
        long_run_factor = goal["weekend_long_run"]
        long_run_reason = "Weekend - a good day for a longer run"

    pace = rhythm.median_pace or DEFAULT_PACE_MIN_KM.get(user.fitness_level, 6.0)
    return PersonalContext(today, ready, typical, taste, recovery, rhythm, pace,
                           long_run_factor, long_run_reason)


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
    ctx: Optional[PersonalContext] = None,
) -> ScoredRoute:
    if ctx is None:
        ctx = build_personal_context(user, checkin, recent)
    goal = GOAL_PROFILES.get(user.goal, GOAL_PROFILES["general_fitness"])
    parts: dict = {}          # component -> points, returned for transparency
    reasons: List[str] = []

    def add(name: str, pts: float, reason: Optional[str] = None):
        if pts:
            parts[name] = parts.get(name, 0.0) + pts
        if reason:
            reasons.append(reason)

    surface = route.surface_type
    surface_label = SURFACE_LABEL.get(surface, "")
    ready = ctx.readiness
    hill = route.elevation_gain_m / route.distance_km if route.distance_km > 0 else 0.0

    # --- 1. safety: soreness / injury vs. surface -------------------------
    sore_weight, sore_part = surface_strain(surface, checkin.sore_body_parts)
    if sore_weight > 0:
        add("soreness", -SORENESS_SURFACE_PENALTY * sore_weight,
            f"Caution: {SURFACE_NOUN[surface]} is harder on your sore {pretty_part(sore_part)}")

    injury_weight, injury_part = surface_strain(surface, user.active_injury_body_parts)
    if injury_weight > 0:
        severities = [sev for part, sev in user.injury_severity.items()
                      if normalize_body_part(part) == injury_part]
        sev = max((SEVERITY_MULTIPLIER.get(x, 1.0) for x in severities), default=1.0)
        add("injury", -INJURY_SURFACE_PENALTY * injury_weight * sev,
            f"Caution: {SURFACE_NOUN[surface]} strains your {pretty_part(injury_part)} injury")

    relief_part = surface_relief(surface, checkin.sore_body_parts + user.active_injury_body_parts)
    if relief_part and sore_weight == 0 and injury_weight == 0:
        add("surface_relief", FRIENDLY_SURFACE_BONUS,
            f"{surface_label} surface is easier on your {pretty_part(relief_part)}")

    # how THIS runner has felt after runs on this surface
    extra = ctx.recovery.surface_soreness.get(surface)
    if extra is not None:
        if extra >= 1.0:
            add("soreness_history", -min(8.0, 3 * extra),
                f"You've tended to be sorer after {SURFACE_NOUN.get(surface, surface)} runs"
                if extra >= 1.5 else None)
        elif extra <= -1.0:
            add("soreness_history", min(4.0, 2 * -extra))

    # ...and after hilly runs: graded by how hilly this route is
    if ctx.recovery.hill_tolerance < 1.0 and hill > FLAT_HILL_M_PER_KM:
        steepness = clamp((hill - FLAT_HILL_M_PER_KM) / 20)
        add("soreness_history", -(1 - ctx.recovery.hill_tolerance) * 25 * steepness,
            "Your legs have been sorer after hilly runs" if steepness >= 0.5 else None)

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

    # --- 3. learned taste (from their own ratings) -------------------------
    taste = ctx.taste
    if taste.confidence > 0:
        aff = taste.surface_affinity.get(surface)
        if aff is not None:
            pts = clamp(W_TASTE_SURFACE * aff * taste.confidence, -10, 10)
            add("taste_surface", pts,
                f"You tend to rate {surface_label.lower()} runs highly" if pts >= 3 else None)
        if route.scenic and taste.scenic_affinity:
            pts = clamp(W_TASTE_SCENIC * taste.scenic_affinity * taste.confidence * 2, -6, 6)
            add("taste_scenic", pts, "You rate scenic runs highly" if pts >= 3 else None)
        if route.is_loop and taste.loop_affinity:
            add("taste_loop", clamp(W_TASTE_LOOP * taste.loop_affinity * taste.confidence * 2, -4, 4))

    if goal["steady_surface_bonus"] and surface in ("pavement", "track"):
        add("goal", goal["steady_surface_bonus"])
    if goal["scenic_bonus"] and route.scenic:
        add("goal", goal["scenic_bonus"])

    # --- 4. distance fit (explicit target, or inferred) --------------------
    typical = ctx.typical_km
    if checkin.planned_distance_km:
        target = checkin.planned_distance_km
        err, run_format, repeat_count, effective_distance = choose_format(route, target, MAX_REPEATS)
        tol = max(0.5, target * 0.25)
        distance_matched = err <= tol
        add("distance", distance_points(err, tol) * goal["distance_weight"])
        if distance_matched:
            mi = effective_distance * 0.621371
            if run_format == "single":
                reasons.append("Close match to your planned distance")
            elif run_format == "out_and_back":
                reasons.append(f"Out-and-Back: {mi:.1f} mi")
            else:
                reasons.append(f"{repeat_count}x Loop: {mi:.1f} mi")
    else:
        # no plan: aim for THEIR normal run, shorter when run-down, longer when
        # fresh, longer still on a weekend
        target = typical * (0.7 + 0.5 * ready) * ctx.long_run_factor
        err, run_format, repeat_count, effective_distance = choose_format(route, target, 1)
        tol = max(0.8, target * 0.3)
        distance_matched = True
        pts = distance_points(err, tol) * INFERRED_DISTANCE_SCALE
        reason = None
        if pts >= 10:
            reason = ctx.long_run_reason or "Good length for how you're feeling today"
        add("distance", pts, reason)

    if run_format == "out_and_back":
        add("format", W_OUT_AND_BACK)
    elif run_format == "repeat":
        add("format", W_REPEAT_PER_LAP * (repeat_count - 1))

    # --- 5. terrain: hilliness vs. readiness, taste, recovery, goal -------
    if route.distance_km > 0:
        ideal = (5 + 35 * ready) * FITNESS_HILL_FACTOR.get(user.fitness_level, 1.0)
        if taste.preferred_hill is not None and taste.confidence > 0:
            learned = taste.preferred_hill * (0.6 + 0.8 * ready)
            ideal = (1 - taste.confidence) * ideal + taste.confidence * learned
        ideal *= ctx.recovery.hill_tolerance * goal["hill_factor"]
        scale = max(ideal, 15)
        pts = clamp(W_TERRAIN * (1 - abs(hill - ideal) / scale), W_TERRAIN_FLOOR, W_TERRAIN)
        reason = None
        if hill < FLAT_HILL_M_PER_KM and ctx.recovery.hill_reason:
            reason = ctx.recovery.hill_reason
        elif hill < FLAT_HILL_M_PER_KM and ctx.rhythm.reason:
            reason = ctx.rhythm.reason
        elif ctx.rhythm.recovery_day:
            reason = None
        elif pts >= 8 and ready >= 0.7 and checkin.energy_score >= 7 and hill >= 20:
            reason = "Feeling fresh - good day for some climbing"
        elif pts >= 8 and ready < 0.45 and hill < FLAT_HILL_M_PER_KM:
            reason = "Gentle, flat route for an easy day"
        elif pts <= -5 and hill > ideal:
            reason = "Hillier than ideal for how you're feeling"
        add("terrain", pts, reason)

    # recovery day (hard effort yesterday / long streak): hills and extra length cost more
    if ctx.rhythm.recovery_day:
        steepness = clamp((hill - FLAT_HILL_M_PER_KM) / 20)
        longer = clamp(effective_distance / typical - 1)
        add("rhythm", -12 * steepness - 6 * longer)

    # --- 6. training load: long route while mileage is high ---------------
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

    # --- 7. proximity to home ---------------------------------------------
    if None not in (user.home_lat, user.home_lon, route.start_lat, route.start_lon):
        d = haversine_km(user.home_lat, user.home_lon, route.start_lat, route.start_lon)
        radius = checkin.willing_to_drive_km or DEFAULT_RADIUS_KM
        add("proximity", W_PROXIMITY * clamp(1 - d / radius),
            "Starts close to home" if d < 1.0 else None)

    # --- 8. history: novelty and past ratings -----------------------------
    novelty = W_NOVELTY if days_since is None else W_NOVELTY * clamp(days_since / 30)
    add("novelty", novelty * goal["novelty_weight"])

    avg_rating = recent.avg_rating_by_route_id.get(route.id)
    if avg_rating is not None:
        add("rating", (avg_rating - 3) * W_RATING_PER_STAR,
            "You've rated this route highly before" if avg_rating >= 4 else None)

    # estimated time: their pace, plus ~5 min per 100 m of climbing
    minutes = effective_distance * ctx.pace_min_km + hill * effective_distance * 0.05

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
        base_score=score,
        estimated_minutes=round(minutes),
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


def similarity(a: ScoredRoute, b: ScoredRoute, count_surface: bool = True) -> float:
    """0 (nothing alike) .. 1 (basically the same run)."""
    sim = 0.0
    if count_surface and a.route.surface_type == b.route.surface_type:
        sim += 0.35
    da, db = a.effective_distance_km, b.effective_distance_km
    if max(da, db) > 0 and abs(da - db) <= 0.15 * max(da, db):
        sim += 0.25
    if None not in (a.route.start_lat, a.route.start_lon, b.route.start_lat, b.route.start_lon):
        if haversine_km(a.route.start_lat, a.route.start_lon,
                        b.route.start_lat, b.route.start_lon) <= 1.5:
            sim += 0.40
    return sim


def diversify(scored: List[ScoredRoute], top_n: int,
              surface_requested: bool = False) -> List[ScoredRoute]:
    """Greedy pick (maximal marginal relevance): each next pick is the best
    remaining route after a penalty for resembling routes already picked.
    Stops the top 3 from being e.g. the same loop run north vs. south.
    Uses base_score, so re-running it (main.py merges real + combined
    routes) never stacks penalties. When the runner asked for a surface,
    sharing that surface isn't counted as "too similar"."""
    pool = sorted(scored, key=lambda s: (-s.base_score,) + rank_key(s)[1:])
    picked: List[ScoredRoute] = []
    while pool and len(picked) < top_n:
        best = None
        for s in pool:
            sim = max((similarity(s, p, not surface_requested) for p in picked), default=0.0)
            adjusted = s.base_score - W_VARIETY * sim
            key = (-round(adjusted, 1),) + rank_key(s)[1:]
            if best is None or key < best[0]:
                best = (key, s, adjusted, sim)
        _, s, adjusted, sim = best
        pool.remove(s)
        breakdown = {k: v for k, v in s.breakdown.items() if k != "variety"}
        if sim > 0:
            breakdown["variety"] = round(-W_VARIETY * sim, 1)
        picked.append(replace(s, score=round(adjusted, 1), breakdown=breakdown))
    return picked


def recommend(
    user: UserProfile,
    checkin: DailyCheckin,
    recent: RecentRuns,
    candidates: List[RouteCandidate],
    top_n: int = 3,
) -> List[ScoredRoute]:
    ctx = build_personal_context(user, checkin, recent)
    eligible = [r for r in candidates if passes_difficulty_gate(r, user)]
    scored = [score_route(r, user, checkin, recent, ctx) for r in eligible]
    # Always rank every eligible route and return the best top_n, even if
    # none is a great distance match, so the user always sees options.
    return diversify(scored, top_n, surface_requested=bool(checkin.surface_preference))
