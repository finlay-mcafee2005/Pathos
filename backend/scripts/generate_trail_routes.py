"""
Generates full-length trail runs - loops and out-and-backs from real
trailheads - instead of relying on short OSM trail segments.

Why: generate_routes_from_osm.py stores individual trail *ways* from OSM,
which are short pieces of a trail network (avg ~1.7 km). Longer trail days
then depend on out-and-backs and stitching segments together. Runners think
in whole runs: "Eaton Canyon to the falls and back", "a 10 km loop around
Griffith Park". This builds those.

How:
  1. Scan the OSM extract once and collect every node on a trail-type way
     (path / track / bridleway / footway that classify_surface() calls
     "trail" - the same rule the OSM pipeline uses).
  2. From each trailhead, ask OSRM for
       - loops: start -> 2 waypoints on a circle -> start (as in
         generate_road_loops.py), rescaled until the distance fits
       - out-and-backs: trailhead -> turnaround point; stored one-way, the
         engine doubles it
     at several distances and in four directions.
  3. Using OSRM's per-segment node annotations, measure what share of each
     route's distance is actually on trail:
       >= 60%  -> stored as "trail"
       35-60%  -> stored as "mixed"
       < 35%   -> discarded (that's a road run)
  4. Skip near-duplicates (mostly the same nodes as a route already kept).

Safe to re-run: deletes routes it created before (names containing
"trail loop - " or "trail out-and-back - ") and regenerates them.

Run with: python3 scripts/generate_trail_routes.py
Then:     python3 scripts/update_elevation.py   (elevation + difficulty)
Requires: OSRM on localhost:5001, osmium, the LA .osm.pbf extract
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import httpx
import osmium
from sqlalchemy import text
from sqlmodel import Session, create_engine
from geoalchemy2.elements import WKTElement

from app.models import Route
from app.scoring.difficulty import classify_difficulty
from osm_surface import classify_surface, TRAIL_HIGHWAY_TAGS
from generate_road_loops import offset, loop_waypoints, to_wkt

DATABASE_URL = "postgresql://postgres:devpassword@localhost:5432/run_recommender"
OSRM_URL = "http://localhost:5001"
OSM_FILE = os.path.expanduser(
    "~/run-recommender-app/osrm-data/planet_-118.49,33.738_-117.669,34.382.osm.pbf"
)

# (name, lat, lon) - OSRM snaps each to the nearest walkable way
TRAILHEADS = [
    ("Eaton Canyon",            34.1777, -118.0960),
    ("Griffith Observatory",    34.1184, -118.3004),
    ("Brand Park",              34.1734, -118.2679),
    ("Deukmejian Wilderness",   34.2077, -118.2716),
    ("Hahamongna",              34.1990, -118.1760),
    ("Debs Park",               34.0937, -118.1978),
    ("Sam Merrill (Cobb Estate)", 34.2042, -118.1286),
    ("Verdugo Mountains",       34.2178, -118.2551),
    ("Lower Arroyo Seco",       34.1367, -118.1665),
]

TARGET_DISTANCES_KM = [5, 8, 12, 16]     # round-trip distance for both kinds
DIRECTIONS = [(0, "north"), (90, "east"), (180, "south"), (270, "west")]
TOLERANCE = 0.15                         # trail networks are sparse; allow 15%
MAX_ITERATIONS = 6
TRAIL_MIN = 0.60
MIXED_MIN = 0.35
DUPLICATE_OVERLAP = 0.70


# ---------------------------------------------------------------------------
# 1. which OSM nodes are on trails
# ---------------------------------------------------------------------------

class TrailNodeCollector(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.nodes = set()

    def way(self, w):
        highway = w.tags.get("highway")
        if highway not in TRAIL_HIGHWAY_TAGS:
            return
        if classify_surface(highway, w.tags.get("surface"), w.tags.get("footway")) != "trail":
            return
        for n in w.nodes:
            self.nodes.add(n.ref)


# ---------------------------------------------------------------------------
# 2-3. route with OSRM and measure the trail share
# ---------------------------------------------------------------------------

def osrm_route(points, trail_nodes):
    """points: [(lat, lon), ...]. Returns (coords, km, trail_fraction, node_set)."""
    coord_str = ";".join(f"{lon},{lat}" for lat, lon in points)
    r = httpx.get(
        f"{OSRM_URL}/route/v1/foot/{coord_str}",
        params={"overview": "full", "geometries": "geojson", "annotations": "nodes,distance"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok":
        raise ValueError(data.get("message", data.get("code")))
    route = data["routes"][0]

    total = on_trail = 0.0
    node_set = set()
    for leg in route["legs"]:
        ann = leg.get("annotation", {})
        nodes, dists = ann.get("nodes", []), ann.get("distance", [])
        node_set.update(nodes)
        for i, d in enumerate(dists):
            total += d
            if nodes[i] in trail_nodes and nodes[i + 1] in trail_nodes:
                on_trail += d
    fraction = on_trail / total if total else 0.0
    return route["geometry"]["coordinates"], route["distance"] / 1000, fraction, node_set


def fit(build, target_km, first_guess):
    """Rescale one size parameter until the routed distance is close to target.
    build(size) -> (coords, km, fraction, nodes). Returns best (result, err)."""
    size, best = first_guess, None
    for _ in range(MAX_ITERATIONS):
        result = build(size)
        km = result[1]
        if km <= 0:
            break
        err = abs(km - target_km) / target_km
        if best is None or err < best[1]:
            best = (result, err)
        if err <= TOLERANCE:
            break
        size *= target_km / km
    return best


def loop_candidate(lat, lon, bearing, target_km, trail_nodes):
    def build(radius):
        wps = loop_waypoints(lat, lon, bearing, radius)
        return osrm_route([(lat, lon), *wps, (lat, lon)], trail_nodes)
    return fit(build, target_km, target_km / 6.8)


def out_and_back_candidate(lat, lon, bearing, target_km, trail_nodes):
    one_way = target_km / 2

    def build(dist):
        turnaround = offset(lat, lon, bearing, dist)
        return osrm_route([(lat, lon), turnaround], trail_nodes)
    return fit(build, one_way, one_way / 1.4)   # trails wind: ~1.4x straight-line


def overlap(a, b):
    small = min(len(a), len(b))
    return len(a & b) / small if small else 0.0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    t0 = time.time()
    print(f"Scanning {os.path.basename(OSM_FILE)} for trail nodes (takes a minute) ...")
    collector = TrailNodeCollector()
    collector.apply_file(OSM_FILE)
    trail_nodes = collector.nodes
    print(f"  {len(trail_nodes):,} trail nodes ({time.time() - t0:.0f}s)")

    engine = create_engine(DATABASE_URL)
    with Session(engine) as session:
        old = ("SELECT id FROM route WHERE name LIKE '%trail loop - %' "
               "OR name LIKE '%trail out-and-back - %'")
        session.exec(text(f"DELETE FROM recommendation WHERE route_id IN ({old})"))
        session.exec(text(f"UPDATE run SET route_id = NULL WHERE route_id IN ({old})"))
        removed = session.exec(text(
            "DELETE FROM route WHERE name LIKE '%trail loop - %' "
            "OR name LIKE '%trail out-and-back - %'")).rowcount
        session.commit()
        if removed:
            print(f"Removed {removed} trail routes from a previous run.")

        kept = []                       # node sets of accepted routes, for de-duplication
        added = {"trail": 0, "mixed": 0}
        skipped = {"error": 0, "distance": 0, "too much road": 0, "duplicate": 0}

        for name, lat, lon in TRAILHEADS:
            print(f"\n{name}")
            for target in TARGET_DISTANCES_KM:
                for bearing, direction in DIRECTIONS:
                    for kind, builder in (("loop", loop_candidate),
                                          ("out-and-back", out_and_back_candidate)):
                        label = f"{name} trail {kind} - {target} km {direction}"
                        try:
                            best = builder(lat, lon, bearing, target, trail_nodes)
                        except Exception as e:
                            skipped["error"] += 1
                            continue
                        if best is None or best[1] > TOLERANCE:
                            skipped["distance"] += 1
                            continue
                        (coords, km, fraction, nodes), _ = best
                        if fraction < MIXED_MIN:
                            skipped["too much road"] += 1
                            continue
                        if any(overlap(nodes, other) > DUPLICATE_OVERLAP for other in kept):
                            skipped["duplicate"] += 1
                            continue

                        surface = "trail" if fraction >= TRAIL_MIN else "mixed"
                        kept.append(nodes)
                        added[surface] += 1
                        session.add(Route(
                            name=label,
                            distance_km=round(km, 2),          # one-way for out-and-backs
                            elevation_gain_m=0,                # update_elevation.py fills this
                            surface_type=surface,
                            difficulty=classify_difficulty(km),  # refined by update_elevation.py
                            scenic=True,
                            gps_path=WKTElement(to_wkt(coords), srid=4326),
                        ))
                        round_trip = km * 2 if kind == "out-and-back" else km
                        print(f"  + {kind:<12} {round_trip:5.1f} km {direction:<5} "
                              f"{fraction:4.0%} on trail -> {surface}")
            session.commit()

    print(f"\nDone in {time.time() - t0:.0f}s. Added {added['trail']} trail + "
          f"{added['mixed']} mixed routes.")
    print("Skipped: " + ", ".join(f"{v} {k}" for k, v in skipped.items()))


if __name__ == "__main__":
    main()
