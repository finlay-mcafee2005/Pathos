"""
Generates realistic road-running loops with the local OSRM server.

The OSM trail pipeline only picks up footpaths, so the database ends up
with ~200 trails and almost no usable road runs. This script builds true
loops (start = finish) of set distances from a handful of road-running
start points, so the "Road" check-in option has real options.

How a loop is built:
  - Put a circle through the start point (in a given direction).
  - Place two waypoints on that circle at 120 and 240 degrees.
  - Ask OSRM for start -> wp1 -> wp2 -> start.
  - Rescale the circle until the routed distance is within 10% of target.

Each loop is checked against trail routes already in the DB: if more
than 25% of it runs along known trails, it's stored as "mixed" instead
of "pavement".

Safe to re-run: it deletes loops it created before (names containing
"road loop") and regenerates them.

Run with: python3 scripts/generate_road_loops.py
Then:     python3 scripts/update_elevation.py
Requires: OSRM server running on localhost:5001
"""

import sys
import os
from math import radians, degrees, sin, cos, asin, atan2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlalchemy import text
from sqlmodel import Session, create_engine
from geoalchemy2.elements import WKTElement

from app.models import Route
from app.scoring.difficulty import classify_difficulty

DATABASE_URL = "postgresql://postgres:devpassword@localhost:5432/run_recommender"
OSRM_URL = "http://localhost:5001"

# (name, lat, lon, scenic)
ANCHORS = [
    ("Occidental College",  34.1271, -118.2109, False),
    ("Rose Bowl",           34.1613, -118.1676, True),
    ("Highland Park",       34.1112, -118.1925, False),
    ("Downtown Glendale",   34.1466, -118.2551, False),
    ("Old Pasadena",        34.1458, -118.1505, False),
    ("South Pasadena",      34.1159, -118.1574, False),
    ("Atwater Village",     34.1185, -118.2610, False),
    ("Silver Lake",         34.0952, -118.2625, True),
]

TARGET_DISTANCES_KM = [3, 5, 8, 12]
DIRECTIONS = [(0, "north"), (180, "south")]   # which side of the start the loop bulges toward
TOLERANCE = 0.10
MAX_ITERATIONS = 6
TRAIL_OVERLAP_MIXED = 0.25

EARTH_R_KM = 6371.0


def offset(lat, lon, bearing_deg, dist_km):
    """Point dist_km away from (lat, lon) along bearing_deg."""
    lat1, lon1, b = radians(lat), radians(lon), radians(bearing_deg)
    d = dist_km / EARTH_R_KM
    lat2 = asin(sin(lat1) * cos(d) + cos(lat1) * sin(d) * cos(b))
    lon2 = lon1 + atan2(sin(b) * sin(d) * cos(lat1), cos(d) - sin(lat1) * sin(lat2))
    return degrees(lat2), degrees(lon2)


def loop_waypoints(lat, lon, bearing, radius_km):
    """Circle through the start, centered radius_km away along bearing.
    Returns two waypoints at +120 / +240 degrees around that circle."""
    c_lat, c_lon = offset(lat, lon, bearing, radius_km)
    back = (bearing + 180) % 360          # direction from center to start
    wp1 = offset(c_lat, c_lon, (back + 120) % 360, radius_km)
    wp2 = offset(c_lat, c_lon, (back + 240) % 360, radius_km)
    return [wp1, wp2]


def osrm_loop(lat, lon, waypoints):
    pts = [(lat, lon), *waypoints, (lat, lon)]
    coord_str = ";".join(f"{p_lon},{p_lat}" for p_lat, p_lon in pts)
    r = httpx.get(
        f"{OSRM_URL}/route/v1/foot/{coord_str}",
        params={"overview": "full", "geometries": "geojson"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok":
        raise ValueError(data.get("message", data.get("code")))
    route = data["routes"][0]
    return route["geometry"]["coordinates"], route["distance"] / 1000


def build_loop(lat, lon, bearing, target_km):
    radius = target_km / 6.8   # triangle perimeter (~5.2r) x typical street detour (~1.3)
    best = None
    for _ in range(MAX_ITERATIONS):
        coords, km = osrm_loop(lat, lon, loop_waypoints(lat, lon, bearing, radius))
        err = abs(km - target_km) / target_km
        if best is None or err < best[2]:
            best = (coords, km, err)
        if err <= TOLERANCE:
            break
        radius *= target_km / km
    return best


def to_wkt(coords):
    return "LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in coords) + ")"


def trail_overlap_fraction(session, wkt):
    """Share of the loop's length that runs within 15 m of a known trail route."""
    row = session.exec(text("""
        WITH loop AS (SELECT ST_GeomFromText(:wkt, 4326) AS g),
        trails AS (
            SELECT ST_Union(ST_Buffer(r.gps_path::geography, 15)::geometry) AS u
            FROM route r, loop
            WHERE r.surface_type = 'trail'
              AND ST_DWithin(r.gps_path::geography, loop.g::geography, 50)
        )
        SELECT COALESCE(
            ST_Length(ST_Intersection(loop.g, trails.u)::geography)
              / NULLIF(ST_Length(loop.g::geography), 0),
            0)
        FROM loop, trails
    """), params={"wkt": wkt}).first()
    return min(1.0, float(row[0] or 0))




def main():
    engine = create_engine(DATABASE_URL)

    with Session(engine) as session:
        # clear loops from a previous run (keep run history, drop stale recommendations)
        old_ids = "SELECT id FROM route WHERE name LIKE '%road loop%'"
        session.exec(text(f"DELETE FROM recommendation WHERE route_id IN ({old_ids})"))
        session.exec(text(f"UPDATE run SET route_id = NULL WHERE route_id IN ({old_ids})"))
        removed = session.exec(text("DELETE FROM route WHERE name LIKE '%road loop%'")).rowcount
        session.commit()
        if removed:
            print(f"Removed {removed} loops from a previous run.")

        added, skipped = 0, 0
        for anchor, lat, lon, scenic in ANCHORS:
            for target in TARGET_DISTANCES_KM:
                for bearing, direction in DIRECTIONS:
                    label = f"{anchor} road loop - {target} km {direction}"
                    try:
                        coords, km, err = build_loop(lat, lon, bearing, target)
                    except Exception as e:
                        print(f"  Skipped '{label}': {e}")
                        skipped += 1
                        continue
                    if err > TOLERANCE * 2:
                        print(f"  Skipped '{label}': best was {km:.1f} km")
                        skipped += 1
                        continue

                    wkt = to_wkt(coords)
                    overlap = trail_overlap_fraction(session, wkt)
                    surface = "mixed" if overlap > TRAIL_OVERLAP_MIXED else "pavement"

                    session.add(Route(
                        name=label,
                        distance_km=round(km, 2),
                        elevation_gain_m=0,          # filled in by update_elevation.py
                        surface_type=surface,
                        difficulty=classify_difficulty(km),  # refined by update_elevation.py
                        scenic=scenic,
                        gps_path=WKTElement(wkt, srid=4326),
                    ))
                    added += 1
                    print(f"  Added '{label}': {km:.2f} km, {surface} ({overlap:.0%} on trails)")
            session.commit()

        print(f"Done. Added {added} loops, skipped {skipped}.")


if __name__ == "__main__":
    main()
