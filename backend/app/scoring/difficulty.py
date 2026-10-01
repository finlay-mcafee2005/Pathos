"""
One shared definition of route difficulty, used by every route generator,
the elevation updater, and the scoring engine.

Difficulty comes from *effort*, not just length:

    effort_km = distance_km + elevation_gain_m / 100

i.e. every 100 m of climbing counts like an extra flat kilometre (a common
runner's rule of thumb). On top of that, sustained steepness bumps a route
up a level even if it's short - a 3 km route climbing 200 m is not "easy".

    effort < 5    -> easy       (e.g. 4 km flat)
    effort < 10   -> moderate   (e.g. 7 km with 150 m of climbing)
    effort >= 10  -> hard       (e.g. 8 km with 300 m of climbing)
    + one level if the route averages >= 50 m of climb per km (~5% grade)
"""

LEVELS = ["easy", "moderate", "hard"]
EASY_MAX_EFFORT = 5.0
MODERATE_MAX_EFFORT = 10.0
STEEP_M_PER_KM = 50.0


def effort_km(distance_km: float, elevation_gain_m: float) -> float:
    return distance_km + (elevation_gain_m or 0) / 100.0


def classify_difficulty(distance_km: float, elevation_gain_m: float = 0.0) -> str:
    effort = effort_km(distance_km, elevation_gain_m)
    if effort < EASY_MAX_EFFORT:
        level = 0
    elif effort < MODERATE_MAX_EFFORT:
        level = 1
    else:
        level = 2
    if distance_km > 0 and (elevation_gain_m or 0) / distance_km >= STEEP_M_PER_KM:
        level = min(level + 1, 2)
    return LEVELS[level]
