"""
Fetches real elevation data for every route's path using the free
Open-Meteo elevation API, calculates total elevation gain, and updates
each route's elevation_gain_m field.

Run with: python3 scripts/update_elevation.py

Requires: httpx (already installed for geocoding)
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from sqlmodel import Session, create_engine, select
from geoalchemy2.shape import to_shape

from app.models import Route
from app.scoring.difficulty import classify_difficulty

DATABASE_URL = "postgresql://postgres:devpassword@localhost:5432/run_recommender"
# Open-Meteo (Copernicus 90m DEM): free, no key, up to 100 points/request.
# Replaced Open-Elevation, which rate-limits (429) almost immediately.
ELEVATION_API = "https://api.open-meteo.com/v1/elevation"

engine = create_engine(DATABASE_URL)

MAX_POINTS_PER_ROUTE = 20  # sample down long paths to keep API calls small
MAX_RETRIES = 6
DELAY_BETWEEN_ROUTES_S = 0.5


def sample_points(coords, max_points):
    """Evenly sample down a list of (lon, lat) coords to at most max_points."""
    if len(coords) <= max_points:
        return coords
    step = len(coords) / max_points
    return [coords[int(i * step)] for i in range(max_points)]


def fetch_elevations(coords):
    """coords: list of (lon, lat). Returns list of elevations in meters."""
    params = {
        "latitude": ",".join(f"{lat:.6f}" for lon, lat in coords),
        "longitude": ",".join(f"{lon:.6f}" for lon, lat in coords),
    }
    # Free API rate-limits bursts (429). Back off and retry instead of skipping.
    for attempt in range(MAX_RETRIES):
        response = httpx.get(ELEVATION_API, params=params, timeout=30)
        if response.status_code == 429 or response.status_code >= 500:
            wait = int(response.headers.get("Retry-After", 0)) or min(60, 5 * 2 ** attempt)
            print(f"    rate-limited ({response.status_code}), waiting {wait}s ...")
            time.sleep(wait)
            continue
        response.raise_for_status()
        return response.json()["elevation"]
    raise RuntimeError(f"gave up after {MAX_RETRIES} retries")


def calculate_gain(elevations):
    """Sum of all positive elevation changes between consecutive points."""
    gain = 0.0
    for i in range(1, len(elevations)):
        diff = elevations[i] - elevations[i - 1]
        if diff > 0:
            gain += diff
    return gain


with Session(engine) as session:
    # Only routes still missing elevation, so re-running resumes where it left off.
    # Pass --all to recompute every route.
    query = select(Route)
    if "--all" not in sys.argv:
        query = query.where((Route.elevation_gain_m == 0) | (Route.elevation_gain_m == None))  # noqa: E711
    routes = session.exec(query).all()
    print(f"Found {len(routes)} routes to process.")

    for i, route in enumerate(routes, start=1):
        try:
            shape = to_shape(route.gps_path)
            coords = list(shape.coords)  # list of (lon, lat)
            sampled = sample_points(coords, MAX_POINTS_PER_ROUTE)

            elevations = fetch_elevations(sampled)
            gain = calculate_gain(elevations)

            route.elevation_gain_m = round(gain, 1)
            route.difficulty = classify_difficulty(route.distance_km, route.elevation_gain_m)
            session.add(route)
            session.commit()

            print(f"[{i}/{len(routes)}] {route.name}: {route.elevation_gain_m}m gain")

            time.sleep(DELAY_BETWEEN_ROUTES_S)  # be polite to the free API

        except Exception as e:
            print(f"[{i}/{len(routes)}] Skipped '{route.name}': {e}")
            continue

    print("Done.")
