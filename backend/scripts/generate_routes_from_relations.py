"""
Queries the free Overpass API for OSM "route relations" - trails and
paths made of multiple connected segments stitched into one logical
route - and inserts them with their real full length, solving the
fragmentation issue individual way-segments have.

Run with: python3 scripts/generate_routes_from_relations.py

Requires: httpx
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlmodel import Session, create_engine
from geoalchemy2.elements import WKTElement

from app.models import Route
from app.scoring.difficulty import classify_difficulty

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")
engine = create_engine(DATABASE_URL)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Bounding box roughly covering Glendale/Pasadena/Eagle Rock
BBOX = "34.05,-118.35,34.35,-117.95"  # south,west,north,east

MIN_LENGTH_KM = 3.0
MAX_LENGTH_KM = 25.0
MAX_ROUTES = 50


def haversine_km(lon1, lat1, lon2, lat2):
    from math import radians, sin, cos, sqrt, atan2
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




# Overpass QL query: find route relations (hiking/foot) within the bbox,
# with their full geometry
query = f"""
[out:json][timeout:90];
(
  relation["route"="hiking"]({BBOX});
  relation["route"="foot"]({BBOX});
  relation["route"="bicycle"]({BBOX});
  relation["network"="rwn"]({BBOX});
  relation["network"="lwn"]({BBOX});
  relation["network"="rcn"]({BBOX});
);
out geom;
"""

print("Querying Overpass API for route relations (this can take 20-60s)...")
response = httpx.post(
    OVERPASS_URL,
    content=f"data={query}",
    headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "run-recommender-app (student project)",
    },
    timeout=90,
)
response.raise_for_status()
data = response.json()

elements = data.get("elements", [])
print(f"Found {len(elements)} route relations.")

with Session(engine) as session:
    inserted = 0
    for rel in elements:
        if inserted >= MAX_ROUTES:
            break
        try:
            name = rel.get("tags", {}).get("name")
            if not name:
                continue

            # Collect all coordinates from all member ways with geometry
            all_coords = []
            for member in rel.get("members", []):
                geom = member.get("geometry")
                if geom:
                    for pt in geom:
                        all_coords.append((pt["lon"], pt["lat"]))

            if len(all_coords) < 2:
                continue

            tagged_distance = rel.get("tags", {}).get("distance")
            if tagged_distance:
                try:
                    length_km = float(tagged_distance)
                except ValueError:
                    length_km = path_length_km(all_coords)
            else:
                length_km = path_length_km(all_coords)

            if length_km < MIN_LENGTH_KM or length_km > MAX_LENGTH_KM:
                continue

            points = ", ".join(f"{lon} {lat}" for lon, lat in all_coords)
            wkt = f"LINESTRING({points})"

            route = Route(
                name=name[:100],
                distance_km=round(length_km, 2),
                elevation_gain_m=0,  # filled in later by update_elevation.py
                surface_type="trail",
                difficulty=classify_difficulty(length_km),  # refined by update_elevation.py
                scenic=True,
                gps_path=WKTElement(wkt, srid=4326),
            )
            session.add(route)
            session.commit()
            inserted += 1
            print(f"Added '{name}': {route.distance_km} km")

        except Exception as e:
            print(f"Skipped one relation: {e}")
            continue

    print(f"Done. Inserted {inserted} routes.")
