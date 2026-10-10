"""
Parses real trail/path geometry directly from the OSM extract using
osmium, and inserts them as candidate routes - an automated alternative
to manually picking landmark coordinate pairs.

Run with: python3 scripts/generate_routes_from_osm.py

Requires: osmium (pip install osmium)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import osmium
from sqlmodel import Session, create_engine
from geoalchemy2.elements import WKTElement

from app.models import Route
from osm_surface import classify_surface
from app.scoring.difficulty import classify_difficulty

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")
OSM_FILE = os.path.expanduser(
    "~/run-recommender-app/osrm-data/planet_-118.49,33.738_-117.669,34.382.osm.pbf"
)

MIN_LENGTH_M = 300
MAX_LENGTH_M = 8000
MAX_ROUTES = 200

CENTER_LAT, CENTER_LON = 34.15, -118.22
MAX_DISTANCE_FROM_CENTER_KM = 15

TARGET_HIGHWAY_TAGS = {"path", "footway", "track", "bridleway"}


def haversine_m(lon1, lat1, lon2, lat2):
    from math import radians, sin, cos, sqrt, atan2
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def is_scenic(highway_tag, surface_tag):
    return highway_tag in ("path", "track") or surface_tag in ("unpaved", "dirt", "gravel", "ground")


class TrailHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.ways = []

    def way(self, w):
        highway = w.tags.get("highway")
        if highway not in TARGET_HIGHWAY_TAGS:
            return
        try:
            coords = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
        except Exception:
            return
        if len(coords) < 2:
            return

        length_m = sum(
            haversine_m(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
            for i in range(len(coords) - 1)
        )
        if length_m < MIN_LENGTH_M or length_m > MAX_LENGTH_M:
            return

        mid_lon, mid_lat = coords[len(coords) // 2]
        if haversine_m(mid_lon, mid_lat, CENTER_LON, CENTER_LAT) > MAX_DISTANCE_FROM_CENTER_KM * 1000:
            return

        self.ways.append({
            "name": w.tags.get("name"),
            "highway": highway,
            "surface": w.tags.get("surface"),
            "footway": w.tags.get("footway"),
            "length_m": length_m,
            "coords": coords,
        })


print(f"Parsing OSM data from {OSM_FILE} ...")
handler = TrailHandler()
handler.apply_file(OSM_FILE, locations=True)

print(f"Found {len(handler.ways)} candidate segments after length filtering.")

named = [w for w in handler.ways if w["name"]]
seen_names = set()
unique_named = []
for w in named:
    if w["name"] not in seen_names:
        seen_names.add(w["name"])
        unique_named.append(w)

print(f"{len(unique_named)} unique named segments.")

selected = unique_named[:MAX_ROUTES]

if len(selected) < MAX_ROUTES:
    unnamed = [w for w in handler.ways if not w["name"]]
    unnamed.sort(key=lambda w: w["length_m"], reverse=True)
    needed = MAX_ROUTES - len(selected)
    for i, w in enumerate(unnamed[:needed]):
        w["name"] = f"Trail Segment #{i + 1}"
        selected.append(w)

print(f"Inserting {len(selected)} routes ...")

engine = create_engine(DATABASE_URL)

with Session(engine) as session:
    inserted = 0
    for w in selected:
        try:
            points = ", ".join(f"{lon} {lat}" for lon, lat in w["coords"])
            wkt = f"LINESTRING({points})"

            route = Route(
                name=str(w["name"])[:100],
                distance_km=round(w["length_m"] / 1000, 2),
                elevation_gain_m=0,
                surface_type=classify_surface(w["highway"], w["surface"], w["footway"]),
                difficulty=classify_difficulty(w["length_m"] / 1000),  # refined by update_elevation.py
                scenic=is_scenic(w["highway"], w["surface"]),
                gps_path=WKTElement(wkt, srid=4326),
            )
            session.add(route)
            inserted += 1
        except Exception as e:
            print(f"Skipped one segment: {e}")
            continue

    session.commit()
    print(f"Done. Inserted {inserted} routes.")
