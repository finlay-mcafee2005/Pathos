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




def get_route_coords(route):
    """Works for both real SQLModel Route objects and CombinedRoute objects."""
    if hasattr(route, "coords"):
        return route.coords
    from geoalchemy2.shape import to_shape
    return list(to_shape(route.gps_path).coords)


class CombinedRoute:
    """A synthetic route made of 2-3 real routes chained together.
    Duck-types enough of the real Route model to flow through the
    existing scoring pipeline unmodified."""

    def __init__(self, legs, coords_list):
        self.id = str(uuid4())
        self.name = " + ".join(leg.name for leg in legs)
        self.coords = [pt for coords in coords_list for pt in coords]
        self.distance_km = round(path_length_km(self.coords), 2)
        self.elevation_gain_m = sum(leg.elevation_gain_m or 0 for leg in legs)
        self.difficulty = classify_difficulty(self.distance_km, self.elevation_gain_m)
        surface_types = {leg.surface_type for leg in legs}
        self.surface_type = next(iter(surface_types)) if len(surface_types) == 1 else "mixed"
        self.scenic = any(leg.scenic for leg in legs)


def generate_combined_routes(routes: List, target_km: float) -> List[CombinedRoute]:
    """Builds an adjacency graph of routes whose endpoints connect, then
    searches for chains of 2-3 routes whose total distance is close to
    the target."""
    valid_routes = []
    for r in routes:
        coords = get_route_coords(r)
        if len(coords) >= 2:
            valid_routes.append((r, coords))

    # Each route usable in 2 orientations: forward and reversed
    oriented = []
    for r, coords in valid_routes:
        oriented.append((r, coords, coords[0], coords[-1]))
        oriented.append((r, list(reversed(coords)), coords[-1], coords[0]))

    n = len(oriented)

    # Precompute adjacency: for oriented route i, which oriented routes j
    # (of a *different* underlying route) have a start point close to i's end
    adjacency = [[] for _ in range(n)]
    for i in range(n):
        _, _, _, end_i = oriented[i]
        for j in range(n):
            if oriented[j][0].id == oriented[i][0].id:
                continue  # never chain a route to itself
            start_j = oriented[j][2]
            if haversine_km(*end_i, *start_j) <= CONNECT_THRESHOLD_KM:
                adjacency[i].append(j)

    combined = []
    seen_combos = set()

    def dfs(chain_idx, used_route_ids, chain_legs, chain_coords, total_dist):
        if len(chain_legs) >= 2:
            if abs(total_dist - target_km) <= MAX_COMBO_SEARCH_RANGE_KM:
                key = tuple(sorted(used_route_ids))
                if key not in seen_combos:
                    seen_combos.add(key)
                    combined.append(CombinedRoute(chain_legs, chain_coords))

        if len(chain_legs) >= MAX_CHAIN_LENGTH:
            return

        for next_idx in adjacency[chain_idx]:
            next_route, next_coords, _, _ = oriented[next_idx]
            if next_route.id in used_route_ids:
                continue
            dfs(
                next_idx,
                used_route_ids | {next_route.id},
                chain_legs + [next_route],
                chain_coords + [next_coords],
                total_dist + next_route.distance_km,
            )

    for i in range(n):
        route_i = oriented[i][0]
        dfs(i, {route_i.id}, [route_i], [oriented[i][1]], route_i.distance_km)

    return combined
