"""
Rules-based scoring engine for route recommendations.
"""

from dataclasses import dataclass, field, replace
from datetime import date
from typing import List, Optional

from app.scoring.difficulty import classify_difficulty
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
    usual_pace_min_km: Optional[float] = None   # what they told us at signup

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
    run_time: Optional[str] = None            # "now" | "morning" | "midday" | "evening"
    available_minutes: Optional[float] = None # time they have; used when no planned distance
    conditions: Optional[object] = None       # app.conditions.Conditions, or None if unavailable
    mood: Optional[str] = None                # "stressed" | "flat" | "good" | "restless" | "low"
    run_intent: Optional[str] = None          # "easy" | "workout" | "long" | "explore"
    hills_pref: Optional[str] = None          # "avoid" | "want" | None (don't mind)


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
    shade: Optional[float] = None   # 0..1 share of the path under tree cover (None = unknown)
    elevation_loss_m: Optional[float] = None   # descent along the stored path (None = assume = gain)
    scenic_pct: Optional[float] = None         # 0..1 share near parks/nature/water/trees (None = unknown)


def climb_per_km(distance_km: float, gain_m: float, loss_m: Optional[float] = None) -> float:
    """Average climbing per km of running the route both ways.

    Uses up AND down: a path stored running downhill (start at the summit)
    has almost no "gain" in its stored direction, but anyone running it still
    has to climb back up. Averaging gain and loss makes the number the same
    whichever end the path happens to start from. For a loop gain ~= loss,
    so this is just gain / distance."""
    if not distance_km or distance_km <= 0:
        return 0.0
    gain = gain_m or 0.0
    loss = gain if loss_m is None else loss_m
    return (gain + loss) / 2 / distance_km


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
    target_km: float = 0.0          # the distance this route was judged against
    target_explicit: bool = False   # True when the runner set miles/minutes
    base_score: float = 0.0                          # score before the variety adjustment
    estimated_minutes: Optional[float] = None
    run_gain_m: Optional[float] = None    # total climbing for the run as recommended (both ways, all laps)
    approach_km: float = 0.0              # each way, home -> start, when the run starts from home
    difficulty: str = "moderate"   # of the run as actually run (out-and-back / laps included)


DIFFICULTY_RANK = {"easy": 0, "moderate": 1, "hard": 2}

ACCEPTABLE_DIFFICULTY_CEILING = {
    "beginner": "moderate",
    "intermediate": "hard",
    "advanced": "hard",
}


def passes_difficulty_gate(difficulty: str, user: UserProfile) -> bool:
    ceiling = ACCEPTABLE_DIFFICULTY_CEILING.get(user.fitness_level, "easy")
    return DIFFICULTY_RANK[difficulty] <= DIFFICULTY_RANK[ceiling]


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
FRIENDLY_SURFACE_BONUS = 2   # was 5: soreness now compares against the gentlest surface on offer,
                             # so this only rewarded being sore (a sore day out-scored a fresh one)
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
W_TERRAIN_EXTRA = 7           # ...plus up to this on a clearly run-down or clearly fresh day
TERRAIN_TIGHTEN = 0.15        # ...and the fit tightens by up to this on those days
W_TERRAIN_UNDER_FLOOR = -4    # ...when the route is flatter than ideal
LOW_ENERGY = 4                # mental energy at or below this (0-10) counts as low
W_LOW_ENERGY_HARD = 15        # max penalty for a Hard run on a low-energy day
LONG_GENTLE_M_PER_KM = 20     # 'Hard' only because it's long: averages under ~2% climb
CLOSE_TO_HOME_KM = 3.5        # check-in travel limit at or under this = "close to home" (the app sends 2 mi)
RUN_FROM_HOME_KM = 4.0        # ...then every route starting within this (straight line) is run from where they are
STREET_DETOUR = 1.3           # streets are ~30% longer than a straight line (the app draws the real way)
W_APPEAL = 8                  # always-on: parks, water and trees beat plain street grids
MIN_ROUTE_SHARE = 0.5         # run from home: under half the run on the route itself starts to cost
W_MOSTLY_APPROACH = 12        # ...up to this much when the route is a tiny bit at the end of the streets
IDEAL_CLIMB_SPAN = 30         # ideal climb (m/km) = 5 + span * readiness^curve
IDEAL_CURVE = 2.0             # >1 keeps an ordinary day well below a fresh one
FEEL_CENTER = 0.72            # readiness of an ordinary day (energy ~6, ~7 h sleep)
FEEL_WIDTH = 0.25             # this far above / below it = clearly fresh / clearly run-down
FEEL_DEADZONE = 0.3
W_FEEL = 12                   # fresh day -> hills/trails, run-down day -> flat/pavement
TERRAIN_TIGHTNESS = 0.7       # <1 = hill fit falls off faster away from today's ideal
W_NOVELTY = 8                # never run / not run in 30+ days
W_RATING_PER_STAR = 5        # around a neutral 3-star rating
W_OUT_AND_BACK = -2          # small nudge toward true loops
W_REPEAT_PER_LAP = -3        # each extra lap of a repeated loop
W_OVERLOAD = 15              # long route while mileage is well above average

W_PROXIMITY = 14              # starts at home -> fades to 0 at the search radius (travel is a priority)
DEFAULT_RADIUS_KM = 15
W_TASTE_SURFACE = 8           # x surface affinity (~ -2..+2), capped at +/-10
W_TASTE_SCENIC = 2
W_TASTE_LOOP = 1.5
W_VARIETY = 10                # max penalty for a pick nearly identical to one above it

# mood and run intent: explicit, so they sit near the other check-in choices
W_MOOD = 8
W_INTENT = 10

# conditions (weather, air, daylight). Safety-type signals, so they can
# outweigh preferences when things get bad, but stay small on normal days.
HEAT_START_F = 78             # "feels like" temperature where heat starts to count
HEAT_SEVERE_F = 95
W_HEAT_MAX = 20               # long, hilly run in severe heat
W_UV = 4                      # long exposed run at very high UV
UV_HIGH = 8
WIND_STRONG_MPH = 20
W_WIND = 6                    # hilly / exposed route in strong wind
AQI_START = 100               # "unhealthy for sensitive groups"
AQI_SEVERE = 200
W_AIR_MAX = 25
RAIN_MUDDY_MM = 5             # rain in the last 48h that leaves trails muddy
W_MUD = 15
W_DARK_TRAIL = 20             # finishing an unlit trail after sunset
W_DARK_ROAD = 6
# heat shortens the target distance: nothing below 82F feels-like,
# 15% shorter around 90F, 30% shorter at 98F+
HEAT_CUT_START_F = 82
HEAT_CUT_FULL_F = 98
HEAT_CUT_MAX = 0.30
SHADE_HEAT_RELIEF = 0.6       # a fully shaded route takes 60% less heat penalty
W_SHADE = 8                   # bonus for a shady route on a hot day

FITNESS_HILL_FACTOR = {"beginner": 0.6, "intermediate": 1.0, "advanced": 1.4}
DEFAULT_TYPICAL_RUN_KM = {"beginner": 4.0, "intermediate": 7.0, "advanced": 10.0}
RUNS_PER_WEEK = 4
MAX_REPEATS = 3
FLAT_HILL_M_PER_KM = 15
W_HILLS_PREF = 18             # the runner said outright: avoid hills / want hills

LOWER_BODY_PARTS = {
    "quad", "hamstring", "glutes", "calf", "shin", "knee", "ankle",
    "hip", "achilles", "foot", "lower_back", "adductor",
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
    signals = [(checkin.energy_score / 10, 1.5)]      # energy counts as much as sleep
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
    # very low mental energy caps readiness, however well they slept:
    # a 2/10 day is not an average day just because sleep was fine
    if checkin.energy_score <= LOW_ENERGY:
        r = min(r, 0.25 + 0.05 * checkin.energy_score)
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
    heat_cut: float = 1.0               # <1 when heat shortened today's target distance
    heat_feels_f: Optional[float] = None
    sore_baseline: Optional[float] = None   # strain of the gentlest surface among today's options


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

    # pace: their logged runs once there are some, else what they told us at
    # signup, else a guess from their fitness level
    pace = (rhythm.median_pace or user.usual_pace_min_km
            or DEFAULT_PACE_MIN_KM.get(user.fitness_level, 6.0))
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
    hill = climb_per_km(route.distance_km, route.elevation_gain_m, route.elevation_loss_m)

    # --- 1. safety: soreness / injury vs. surface -------------------------
    sore_weight, sore_part = surface_strain(surface, checkin.sore_body_parts)
    # Only count the EXTRA strain versus the gentlest surface actually on offer today.
    # Sore knees + sore calves strain both road and trail; penalising every route
    # the same just drags every match down on a rough day without changing the order.
    baseline = ctx.sore_baseline if ctx.sore_baseline is not None else \
        min(surface_strain(s, checkin.sore_body_parts)[0] for s in SURFACE_STRAIN)
    sore_weight = max(0.0, sore_weight - baseline)
    wanted_surface = {"road": "pavement"}.get(checkin.surface_preference, checkin.surface_preference)
    if sore_weight > 0:
        # they know they're sore and still asked for this surface: warn, but count it half
        if wanted_surface and surface == wanted_surface:
            sore_weight *= 0.5
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
    # (no "gentler surface" bonus for a surface other than the one they asked for)
    if relief_part and sore_weight == 0 and injury_weight == 0 \
            and not (wanted_surface and surface != wanted_surface):
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
        elif surface != "unknown":
            add("surface_pref", -W_SURFACE_PREF * 0.75)  # the other surface: they asked for this one

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
    # "Close to home" in the check-in = they run from where they are: the run to the
    # start and back counts toward today's distance, so the route part is that much
    # shorter. Any other travel choice (15/30/45 min) = they get to the start first.
    approach = 0.0
    close_to_home = checkin.willing_to_drive_km is not None and checkin.willing_to_drive_km <= CLOSE_TO_HOME_KM
    if close_to_home and None not in (user.home_lat, user.home_lon, route.start_lat, route.start_lon):
        straight = haversine_km(user.home_lat, user.home_lon, route.start_lat, route.start_lon)
        if straight <= RUN_FROM_HOME_KM:
            approach = straight * STREET_DETOUR
    typical = ctx.typical_km
    if checkin.planned_distance_km:
        target = checkin.planned_distance_km
        err, run_format, repeat_count, effective_distance = choose_format(route, max(0.5, target - 2 * approach), MAX_REPEATS)
        effective_distance += 2 * approach
        err = abs(effective_distance - target)
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
        err, run_format, repeat_count, effective_distance = choose_format(route, max(0.5, target - 2 * approach), 1)
        effective_distance += 2 * approach
        err = abs(effective_distance - target)
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

    # Run from home: the streets to the start and back are part of the run, so what
    # the runner actually feels is the climb (and the parks) spread over the whole run,
    # not just the route part. A route that's mostly "getting there" isn't much of a route.
    route_hill = hill
    route_share = 1.0
    if approach > 0 and effective_distance > 0:
        route_share = clamp((effective_distance - 2 * approach) / effective_distance)
        hill = route_hill * route_share
        if route_share < MIN_ROUTE_SHARE:
            add("approach", -W_MOSTLY_APPROACH * (1 - route_share / MIN_ROUTE_SHARE),
                "Most of this run is getting to the route" if route_share < 0.3 else None)

    # how far today is from an ordinary day: -1 run-down .. 0 ordinary .. +1 fresh
    # (a little either side of ordinary counts as ordinary)
    lean = clamp((ready - FEEL_CENTER) / FEEL_WIDTH, -1, 1)
    lean = clamp((abs(lean) - FEEL_DEADZONE) / (1 - FEEL_DEADZONE)) * (1 if lean >= 0 else -1)

    # --- 5. terrain: hilliness vs. readiness, taste, recovery, goal -------
    if route.distance_km > 0:
        ideal = (5 + IDEAL_CLIMB_SPAN * ready ** IDEAL_CURVE) * FITNESS_HILL_FACTOR.get(user.fitness_level, 1.0)
        if taste.preferred_hill is not None and taste.confidence > 0:
            learned = taste.preferred_hill * (0.6 + 0.8 * ready)
            ideal = (1 - taste.confidence) * ideal + taste.confidence * learned
        ideal *= ctx.recovery.hill_tolerance * goal["hill_factor"]
        if checkin.run_intent == "easy" or ctx.rhythm.recovery_day:
            ideal = min(ideal, 8.0)                 # an easy / day-after-a-hard-effort run is a flat run
        # how forgiving the fit is: tighter than before so a fresh day and an
        # ordinary day actually prefer different amounts of climbing
        # on an ordinary day their own taste leads; the further from ordinary they feel,
        # the more hilliness counts and the tighter the fit (so days pick different routes)
        w_terrain = W_TERRAIN + W_TERRAIN_EXTRA * abs(lean)
        scale = max(ideal, 15) * (TERRAIN_TIGHTNESS - TERRAIN_TIGHTEN * abs(lean))
        if hill > ideal:
            # on a tired day, climbing above the ideal costs more, sooner
            scale *= 0.5 + 0.5 * ready
        # too steep on a run-down day can cost more than the usual floor
        # flatter than ideal on a fresh day is a missed chance, not a problem: it costs less
        floor = W_TERRAIN_FLOOR - 12 * (1 - ready) if hill > ideal else W_TERRAIN_UNDER_FLOOR
        pts = clamp(w_terrain * (1 - abs(hill - ideal) / scale), floor, w_terrain)
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

    # how they feel today tilts the KIND of run, not just its hilliness: a fresh day leans
    # toward climbing and trails, a run-down day toward flat, even pavement.
    hillness = clamp((hill - 8) / 25)                               # 8 m/km -> 0, 33 m/km -> 1
    rugged = {"trail": 1.0, "mixed": 0.5}.get(surface, 0.0)
    add("feel", W_FEEL * lean * (0.6 * hillness + 0.4 * rugged - 0.3))

    # the runner's own call on hills today outweighs anything inferred above
    if checkin.hills_pref == "avoid":
        steep = clamp((hill - 10) / 25)                    # 10 m/km -> 0, 35 m/km -> 1
        if hill < FLAT_HILL_M_PER_KM:
            add("hills", W_HILLS_PREF * 0.4, "Flat, like you asked")
        else:
            add("hills", -W_HILLS_PREF * steep,
                "Has some climbing (you asked to avoid hills)" if steep >= 0.5 else None)
    elif checkin.hills_pref == "want":
        climb = clamp((hill - 15) / 25)                    # 15 m/km -> 0, 40 m/km -> 1
        if climb > 0:
            add("hills", W_HILLS_PREF * climb, "Plenty of climbing, like you asked" if climb >= 0.5 else None)
        elif hill < 10:
            add("hills", -W_HILLS_PREF * 0.5)

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

    # --- 6b. surroundings: how pleasant the route itself is --------------
    # Separate from the "scenic" request: this is a small, always-on nudge so a
    # path through a park or along the river beats a loop of plain streets.
    if route.scenic_pct is not None or route.shade is not None:
        appeal = 0.6 * (route.scenic_pct or 0.0) + 0.4 * (route.shade or 0.0)
        add("appeal", W_APPEAL * route_share * clamp((appeal - 0.15) / 0.6),
            "Runs through parks, trees or along water" if appeal >= 0.6 else None)

    # --- 7. proximity to home ---------------------------------------------
    if None not in (user.home_lat, user.home_lon, route.start_lat, route.start_lon):
        d = haversine_km(user.home_lat, user.home_lon, route.start_lat, route.start_lon)
        radius = checkin.willing_to_drive_km or DEFAULT_RADIUS_KM
        # close-to-home matters most on a tired day; on a fresh day they're up for going farther
        near_weight = W_PROXIMITY * (1.1 - 0.3 * ctx.readiness)
        add("proximity", near_weight * clamp(1 - d / radius),
            "Starts close to home" if d < 1.0 else None)

    # --- 8. history: novelty and past ratings -----------------------------
    novelty = W_NOVELTY if days_since is None else W_NOVELTY * clamp(days_since / 30)
    add("novelty", novelty * goal["novelty_weight"])

    avg_rating = recent.avg_rating_by_route_id.get(route.id)
    if avg_rating is not None:
        add("rating", (avg_rating - 3) * W_RATING_PER_STAR,
            "You've rated this route highly before" if avg_rating >= 4 else None)

    # --- 9. conditions: heat, air quality, wind, mud, daylight -------------
    cond = checkin.conditions
    if cond is not None:
        run_minutes = effective_distance * ctx.pace_min_km + hill * effective_distance * 0.05
        length = clamp(run_minutes / 90)          # 0 for a short jog, 1 at 90+ minutes
        steepness = clamp(hill / 40)              # climbing works harder in heat

        feels = getattr(cond, "feels_like_f", None)
        if feels is None:
            feels = getattr(cond, "temp_f", None)
        if feels is not None and feels > HEAT_START_F:
            heat = clamp((feels - HEAT_START_F) / (HEAT_SEVERE_F - HEAT_START_F))
            pts = -W_HEAT_MAX * heat * (0.3 + 0.7 * length) * (1 + 0.5 * steepness) / 1.5
            shade = getattr(route, "shade", None)
            if shade:
                pts *= 1 - SHADE_HEAT_RELIEF * shade        # trees take the edge off
                if shade >= 0.35:
                    add("shade", W_SHADE * heat * shade,
                        "Shady route for a hot day" if heat * shade >= 0.3 else None)
            reason = None
            if pts <= -4:
                reason = (f"It'll feel like {feels:.0f}°F - shorter and flatter is the smart call"
                          if heat < 1 else f"Dangerous heat ({feels:.0f}°F) - keep it short, or go early")
            add("heat", pts, reason)

        uv = getattr(cond, "uv_index", None)
        if uv is not None and uv >= UV_HIGH and run_minutes > 45:
            add("heat", -W_UV * clamp((run_minutes - 45) / 45))

        wind = getattr(cond, "wind_mph", None)
        if wind is not None and wind >= WIND_STRONG_MPH and (hill >= 20 or surface == "trail"):
            add("wind", -W_WIND * clamp((wind - WIND_STRONG_MPH) / 15 + 0.3),
                f"Windy ({wind:.0f} mph) - exposed ridges will be rough" if wind >= 25 else None)

        aqi = getattr(cond, "us_aqi", None)
        if aqi is not None and aqi > AQI_START:
            bad = clamp((aqi - AQI_START) / (AQI_SEVERE - AQI_START))
            pts = -W_AIR_MAX * bad * (0.35 + 0.65 * clamp(run_minutes / 60))
            add("air", pts,
                f"Air quality is poor (AQI {aqi:.0f}) - keep it short and easy" if pts <= -3 else None)

        rain = getattr(cond, "rain_last_48h_mm", 0) or 0
        if rain >= RAIN_MUDDY_MM and surface in ("trail", "mixed"):
            add("mud", -W_MUD * (1.0 if surface == "trail" else 0.5),
                "Recent rain - trails may be muddy and slick")

        until_sunset = getattr(cond, "minutes_until_sunset", None)
        if until_sunset is not None and run_minutes > until_sunset - 10:
            dark = clamp((run_minutes - until_sunset + 10) / 30)
            if surface in ("trail", "mixed"):
                add("daylight", -W_DARK_TRAIL * dark, "You'd finish after sunset - unlit trails are risky")
            else:
                add("daylight", -W_DARK_ROAD * dark)

    # --- 10. mood and what the run is for ----------------------------------
    never_run = days_since is None
    familiar = days_since is not None and days_since <= 60
    liked = avg_rating is not None and avg_rating >= 4
    hilly = hill >= 20
    soft = surface in ("trail", "mixed")
    home_km = None
    if None not in (user.home_lat, user.home_lon, route.start_lat, route.start_lon):
        home_km = haversine_km(user.home_lat, user.home_lon, route.start_lat, route.start_lon)

    mood = checkin.mood
    if mood == "stressed":
        pts = (0.6 if route.scenic else 0) + (0.4 if soft else 0) - (0.6 if route.difficulty == "hard" else 0)
        add("mood", W_MOOD * pts,
            "Scenic and away from traffic - good for clearing your head" if pts >= 0.6 else None)
    elif mood == "flat":
        pts = (0.5 if route.scenic else 0) + (0.4 if never_run or (days_since or 0) > 30 else 0) \
            - (0.5 if route.difficulty == "hard" else 0)
        add("mood", W_MOOD * pts, "Something a little different to get you going" if pts >= 0.5 else None)
    elif mood == "good":
        add("mood", W_MOOD * (0.4 if hilly else 0))
    elif mood == "restless":
        pts = (0.6 if never_run or (days_since or 0) > 30 else 0) + (0.5 if hilly else 0)
        add("mood", W_MOOD * pts, "New ground and some climbing for a restless day" if pts >= 0.6 else None)
    elif mood == "low":
        # comfort over novelty: familiar and well-liked counts double, new ground counts against
        pts = (1.0 if familiar else 0) + (0.5 if liked else 0) \
            + (0.5 if home_km is not None and home_km < 2 else 0) \
            - (0.4 if never_run else 0) - (1.5 if route.difficulty == "hard" else 0)
        add("mood", W_MOOD * pts, "Familiar and close to home for a low day" if pts >= 1.0 else None)

    intent = checkin.run_intent
    if intent == "easy":
        # any climbing counts against an easy day, flat counts for it
        flat = clamp(1 - hill / FLAT_HILL_M_PER_KM)
        add("intent", W_INTENT * (0.8 * flat - clamp((hill - 5) / 20)) - (4 if route.difficulty == "hard" else 0),
            "Flat and easy, like you wanted" if hill < 8 else None)
    elif intent == "workout":
        even = surface in ("pavement", "track")
        add("intent", W_INTENT * (0.8 if even else -0.6),
            "Even footing for a workout" if even else None)
    elif intent == "long":
        add("intent", W_INTENT * (0.3 if route.scenic else 0))
    elif intent == "explore":
        add("intent", W_INTENT * (1.2 if never_run else 0.5 if (days_since or 0) > 60 else -0.3),
            "A route you've never run" if never_run else None)

    # difficulty of the run as actually run: an out-and-back or 3 laps
    # doubles / triples both the distance and the climbing
    run_gain = route_hill * max(0.0, effective_distance - 2 * approach)   # the streets to the start are counted flat
    run_difficulty = classify_difficulty(effective_distance, run_gain)
    # low mental energy: a Hard *climbing* run is a hard sell today. A run that's Hard only
    # because of the distance they chose isn't penalised (every option at that length is).
    if checkin.energy_score <= LOW_ENERGY and run_difficulty == "hard" \
            and not long_but_gentle(effective_distance, run_gain):
        add("energy", -W_LOW_ENERGY_HARD * (LOW_ENERGY + 1 - checkin.energy_score) / (LOW_ENERGY + 1),
            "A tough run for a low-energy day")

    # estimated time: their pace, plus ~5 min per 100 m of climbing
    minutes = effective_distance * ctx.pace_min_km + run_gain * 0.05

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
        target_km=target,
        target_explicit=bool(checkin.planned_distance_km),
        days_since_last_run=days_since,
        avg_rating=avg_rating,
        breakdown={k: round(v, 1) for k, v in parts.items()},
        base_score=score,
        estimated_minutes=round(minutes),
        run_gain_m=round(run_gain, 1),
        approach_km=round(approach, 2),
        difficulty=run_difficulty,
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
    # same length (within 5%) adds to "same run"; it no longer rewards picks
    # for being very different lengths, which pulled in 2 mi and 10 mi options
    da, db = a.effective_distance_km, b.effective_distance_km
    if max(da, db) > 0 and abs(da - db) <= 0.05 * max(da, db):
        sim += 0.25
    if None not in (a.route.start_lat, a.route.start_lon, b.route.start_lat, b.route.start_lon):
        if haversine_km(a.route.start_lat, a.route.start_lon,
                        b.route.start_lat, b.route.start_lon) <= 1.5:
            sim += 0.40
    # same family of generated loops ("Oxy Loop via A St" / "Oxy Loop via B St")
    if route_family(a.route.name) == route_family(b.route.name):
        sim += 0.30
    return min(sim, 1.0)


def long_but_gentle(distance_km: float, climb_m: float) -> bool:
    """Rated Hard only because of length: flat enough that it isn't a hard effort per mile."""
    return bool(distance_km) and (climb_m or 0) / distance_km < LONG_GENTLE_M_PER_KM \
        and classify_difficulty(distance_km, climb_m) == "hard"


def route_family(name: str) -> str:
    """'Oxy Loop via Avenue 53' -> 'oxy loop'; 'Los Feliz North Loop (5.0 mi)' -> 'los feliz north loop'."""
    n = (name or "").lower()
    for sep in (" via ", " (", " & back", " to "):
        n = n.split(sep)[0]
    return n.strip()


# Distance is a band, not just a score: routes far from the target only show
# up when there aren't enough within it. (Inferred targets get a wider band.)
DISTANCE_BAND_EXPLICIT = (0.75, 1.30)
DISTANCE_BAND_INFERRED = (0.60, 1.50)


def in_distance_band(scored: List[ScoredRoute], top_n: int) -> List[ScoredRoute]:
    def ok(s, band):
        lo, hi = band
        return s.target_km <= 0 or lo * s.target_km <= s.effective_distance_km <= hi * s.target_km
    for widen in (1.0, 1.25, 1.6):   # loosen step by step if the area is thin
        kept = []
        for s in scored:
            lo, hi = DISTANCE_BAND_EXPLICIT if s.target_explicit else DISTANCE_BAND_INFERRED
            if ok(s, (lo / widen, hi * widen)):
                kept.append(s)
        if len(kept) >= top_n:
            return kept
    return scored


def diversify(scored: List[ScoredRoute], top_n: int,
              surface_requested: bool = False) -> List[ScoredRoute]:
    """Greedy pick (maximal marginal relevance): each next pick is the best
    remaining route after a penalty for resembling routes already picked.
    Stops the top 3 from being e.g. the same loop run north vs. south.
    Uses base_score, so re-running it (main.py merges real + combined
    routes) never stacks penalties. When the runner asked for a surface,
    sharing that surface isn't counted as "too similar"."""
    pool = sorted(in_distance_band(scored, top_n), key=lambda s: (-s.base_score,) + rank_key(s)[1:])
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
    ctx, checkin = prepare_context(user, checkin, recent)
    surfaces = {c.surface_type for c in candidates if c.surface_type in SURFACE_STRAIN or c.surface_type == "track"}
    if surfaces:
        ctx.sore_baseline = min(surface_strain(s, checkin.sore_body_parts)[0] for s in surfaces)
    scored = [score_route(r, user, checkin, recent, ctx) for r in candidates]
    # gate on the difficulty of the run as it would actually be run
    scored = [s for s in scored if passes_difficulty_gate(s.difficulty, user)]
    # Always rank every eligible route and return the best top_n, even if
    # none is a great distance match, so the user always sees options.
    return diversify(scored, top_n, surface_requested=bool(checkin.surface_preference))


def prepare_context(user: UserProfile, checkin: DailyCheckin, recent: RecentRuns):
    """Runner context for today, with the run's purpose and any time budget
    folded in. Returns (ctx, checkin) - the check-in may gain a distance."""
    ctx = build_personal_context(user, checkin, recent)
    # what the run is for shifts the target length when they didn't set one
    if checkin.run_intent == "long":
        ctx = replace(ctx, long_run_factor=max(1.5, ctx.long_run_factor), long_run_reason="Longer route for your long run")
    elif checkin.run_intent == "easy":
        ctx = replace(ctx, long_run_factor=0.8, long_run_reason=None)
    elif checkin.run_intent == "workout":
        ctx = replace(ctx, long_run_factor=1.0, long_run_reason=None)
    # "I have 40 minutes" -> a distance target at their usual pace (with a
    # little slack for stoplights and warm-up)
    if not checkin.planned_distance_km and checkin.available_minutes:
        checkin = replace(checkin, planned_distance_km=round(
            checkin.available_minutes * 0.9 / ctx.pace_min_km, 2))
    # hot out: aim shorter, whether they gave a distance or not
    cut, feels = heat_distance_factor(checkin.conditions)
    if cut < 1:
        ctx = replace(ctx, heat_cut=cut, heat_feels_f=feels)
        if checkin.planned_distance_km:
            checkin = replace(checkin, planned_distance_km=round(checkin.planned_distance_km * cut, 2))
        else:
            ctx = replace(ctx, long_run_factor=ctx.long_run_factor * cut)
    return ctx, checkin


def heat_distance_factor(conditions) -> tuple:
    """(multiplier for today's target distance, feels-like °F). 1.0 when it isn't hot."""
    if conditions is None:
        return 1.0, None
    feels = getattr(conditions, "feels_like_f", None)
    if feels is None:
        feels = getattr(conditions, "temp_f", None)
    if feels is None or feels <= HEAT_CUT_START_F:
        return 1.0, feels
    frac = min(1.0, (feels - HEAT_CUT_START_F) / (HEAT_CUT_FULL_F - HEAT_CUT_START_F))
    return round(1 - HEAT_CUT_MAX * frac, 3), feels


def target_km(ctx: PersonalContext, checkin: DailyCheckin) -> float:
    """The distance this runner should aim for today (their own or inferred)."""
    if checkin.planned_distance_km:
        return checkin.planned_distance_km
    return ctx.typical_km * (0.7 + 0.5 * ctx.readiness) * ctx.long_run_factor
