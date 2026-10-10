"""
Queries the local OSRM server for real route geometry between
real landmarks in Glendale/Pasadena/Eagle Rock, and inserts them
as Route rows - replacing fake straight-line seed data.

Run with: python3 scripts/generate_real_routes.py

Requires: OSRM server running on localhost:5001 (see osrm-data setup)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlmodel import Session, create_engine
from geoalchemy2.elements import WKTElement

from app.models import Route

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")
OSRM_URL = "http://localhost:5001"

engine = create_engine(DATABASE_URL)

# (name, start_lon, start_lat, end_lon, end_lat, difficulty, surface_type, scenic)
ROUTE_DEFINITIONS = [
    ("Rose Bowl Loop", -118.1676, 34.1613, -118.1706, 34.1655,
     "easy", "pavement", True),
    ("Brand Park to Deukmejian", -118.2679, 34.1734, -118.2716, 34.2077,
     "hard", "trail", True),
    ("Eagle Rock Loop", -118.2181, 34.1378, -118.2226, 34.1367,
     "moderate", "pavement", False),
    ("Arroyo Seco Trail", -118.1665, 34.1367, -118.1656, 34.1447,
     "moderate", "trail", True),
    ("Descanso Gardens Loop", -118.2229, 34.2114, -118.2244, 34.2098,
     "easy", "trail", True),
]


def query_osrm_route(start_lon, start_lat, end_lon, end_lat):
    url = f"{OSRM_URL}/route/v1/foot/{start_lon},{start_lat};{end_lon},{end_lat}"
    response = httpx.get(url, params={"overview": "full", "geometries": "geojson"})
    response.raise_for_status()
    data = response.json()
    if data.get("code") != "Ok":
        raise ValueError(f"OSRM error: {data}")
    route = data["routes"][0]
    return route["geometry"]["coordinates"], route["distance"]


def make_linestring(coords):
    points = ", ".join(f"{lon} {lat}" for lon, lat in coords)
    return WKTElement(f"LINESTRING({points})", srid=4326)


with Session(engine) as session:
    for name, s_lon, s_lat, e_lon, e_lat, difficulty, surface, scenic in ROUTE_DEFINITIONS:
        try:
            coords, distance_m = query_osrm_route(s_lon, s_lat, e_lon, e_lat)
        except Exception as e:
            print(f"Skipped '{name}': {e}")
            continue

        route = Route(
            name=name,
            distance_km=round(distance_m / 1000, 2),
            elevation_gain_m=0,  # OSRM doesn't provide elevation; refine manually later
            surface_type=surface,
            difficulty=difficulty,
            scenic=scenic,
            gps_path=make_linestring(coords),
        )
        session.add(route)
        print(f"Added '{name}': {route.distance_km} km, {len(coords)} points")

    session.commit()
    print("Done.")