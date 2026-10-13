"""
Generates synthetic "combined route" candidates by chaining 2-3 real
routes together when their endpoints are geographically close enough
to run as one continuous route. Used to cover target distances that
no single route or out-and-back/repeat-loop variation can reach.
"""

from math import radians, sin, cos, sqrt, atan2
from uuid import uuid4
from typing import List

from app.scoring.difficulty import classify_difficulty

CONNECT_THRESHOLD_KM = 1.2
MAX_COMBO_SEARCH_RANGE_KM = 3.0
MAX_CHAIN_LENGTH = 3


def haversine_km(lon1, lat1, lon2, lat2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def path_length_km(coords):
    total = 0.0
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        total += haversine_km(lon1, lat1, lon2, lat2)
    return total




_coords_cache: dict = {}


def get_route_coords(route):
    """Works for both real SQLModel Route objects and CombinedRoute objects.
    Real routes' geometry is parsed once and cached (paths don't change while
    the server runs), which saves re-parsing hundreds of paths per request."""
    if hasattr(route, "coords"):
        return route.coords
    key = str(route.id)
    cached = _coords_cache.get(key)
    if cached is None:
        from geoalchemy2.shape import to_shape
        cached = list(to_shape(route.gps_path).coords)
        _coords_cache[key] = cached
    return cached


class CombinedRoute:
    """A synthetic route made of 2-3 real routes chained together.
    Duck-types enough of the real Route model to flow through the
    existing scoring pipeline unmodified."""

    def __init__(self, legs, coords_list, distance_km=None):
        self.id = str(uuid4())
        self.name = " + ".join(getattr(leg, "nickname", None) or leg.name for leg in legs)
        self.coords = [pt for coords in coords_list for pt in coords]
        self.distance_km = round(distance_km if distance_km is not None else path_length_km(self.coords), 2)
        self.elevation_gain_m = sum(leg.elevation_gain_m or 0 for leg in legs)
        self.difficulty = classify_difficulty(self.distance_km, self.elevation_gain_m)
        surface_types = {leg.surface_type for leg in legs}
        self.surface_type = next(iter(surface_types)) if len(surface_types) == 1 else "mixed"
        self.scenic = any(leg.scenic for leg in legs)


MAX_COMBOS = 150          # plenty to choose 3 good ones from; keeps scoring fast
_CELL_DEG = 0.012         # grid cell ~1.3 km, a bit bigger than CONNECT_THRESHOLD_KM


def _cell(lon, lat):
    return (int(lat // _CELL_DEG), int(lon // _CELL_DEG))


def generate_combined_routes(routes: List, target_km: float) -> List[CombinedRoute]:
    """Finds chains of 2-3 routes whose endpoints connect and whose total
    distance is close to the target.

    Fast path: endpoints are bucketed into a grid so only nearby routes are
    compared (instead of every pair), chains stop growing once they're past
    the target, and the search stops after MAX_COMBOS. Combos closest to the
    target are tried first so the cap keeps the best ones."""
    max_total = target_km + MAX_COMBO_SEARCH_RANGE_KM
    oriented = []
    for r in routes:
        if not r.distance_km or r.distance_km >= max_total:
            continue                      # a single leg already too long to chain
        coords = get_route_coords(r)
        if len(coords) < 2:
            continue
        oriented.append((r, coords, coords[0], coords[-1]))
        if coords[0] != coords[-1]:
            oriented.append((r, coords[::-1], coords[-1], coords[0]))

    # index oriented routes by the grid cell of their start point
    starts_by_cell: dict = {}
    for j, o in enumerate(oriented):
        starts_by_cell.setdefault(_cell(*o[2]), []).append(j)

    adjacency = []
    for i, (route_i, _, _, end_i) in enumerate(oriented):
        cy, cx = _cell(*end_i)
        near = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for j in starts_by_cell.get((cy + dy, cx + dx), ()):
                    if oriented[j][0].id != route_i.id and \
                            haversine_km(*end_i, *oriented[j][2]) <= CONNECT_THRESHOLD_KM:
                        near.append(j)
        adjacency.append(near)

    combined = []
    seen_combos = set()
    budget = [200_000]                    # hard cap on search steps

    def dfs(chain_idx, used_route_ids, chain_legs, chain_coords, total_dist, gap_km):
        if budget[0] <= 0 or len(combined) >= MAX_COMBOS:
            return
        budget[0] -= 1
        if len(chain_legs) >= 2 and abs(total_dist - target_km) <= MAX_COMBO_SEARCH_RANGE_KM:
            key = tuple(sorted(used_route_ids))
            if key not in seen_combos:
                seen_combos.add(key)
                combined.append(CombinedRoute(chain_legs, chain_coords, total_dist + gap_km))
        if len(chain_legs) >= MAX_CHAIN_LENGTH:
            return
        end = oriented[chain_idx][3]
        # try the legs that land closest to the target first
        nexts = sorted(adjacency[chain_idx],
                       key=lambda j: abs(total_dist + oriented[j][0].distance_km - target_km))
        for next_idx in nexts:
            next_route, next_coords, next_start, _ = oriented[next_idx]
            if next_route.id in used_route_ids:
                continue
            new_total = total_dist + next_route.distance_km
            if new_total > max_total:
                continue                  # already past the target: don't go deeper
            dfs(next_idx, used_route_ids | {next_route.id}, chain_legs + [next_route],
                chain_coords + [next_coords], new_total,
                gap_km + haversine_km(*end, *next_start))

    order = sorted(range(len(oriented)), key=lambda i: -oriented[i][0].distance_km)
    for i in order:
        route_i = oriented[i][0]
        dfs(i, {route_i.id}, [route_i], [oriented[i][1]], route_i.distance_km, 0.0)
        if len(combined) >= MAX_COMBOS or budget[0] <= 0:
            break

    return combined
