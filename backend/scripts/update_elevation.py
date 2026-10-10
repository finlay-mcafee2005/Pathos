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
with engine.begin() as _conn:   # new column for total descent (no-op if it exists)
    from sqlalchemy import text as _text
    _conn.execute(_text("ALTER TABLE route ADD COLUMN IF NOT EXISTS elevation_loss_m FLOAT"))

MAX_POINTS_PER_ROUTE = 20  # sample down long paths to keep API calls small
MAX_RETRIES = 6
DELAY_BETWEEN_ROUTES_S = 0.5


def sample_points(coords, max_points):
    """Evenly sample down a list of (lon, lat) coords to at most max_points."""
    if len(coords) <= max_points:
        return coords
    step = len(coords) / max_points
    return [coords[int(i * step)] for i in range(max_points)]


BACKUP_API = "https://api.opentopodata.org/v1/ned10m"   # USGS 10 m DEM, free, 100 pts/request, 1 req/s


def fetch_backup(coords):
    """Same as fetch_elevations, from OpenTopoData. Used when Open-Meteo is rate-limited."""
    locations = "|".join(f"{lat:.6f},{lon:.6f}" for lon, lat in coords)
    for attempt in range(3):
        response = httpx.get(BACKUP_API, params={"locations": locations}, timeout=30)
        if response.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        response.raise_for_status()
        time.sleep(1.1)  # their limit: 1 request per second
        return [r["elevation"] for r in response.json()["results"]]
    raise RuntimeError("backup service also rate-limited")


def fetch_elevations(coords):
    """coords: list of (lon, lat). Returns list of elevations in meters.
    Tries Open-Meteo once; if it's rate-limited, switches to the backup."""
    global USE_BACKUP
    if USE_BACKUP:
        return fetch_backup(coords)
    response = httpx.get(ELEVATION_API, params={
        "latitude": ",".join(f"{lat:.6f}" for lon, lat in coords),
        "longitude": ",".join(f"{lon:.6f}" for lon, lat in coords),
    }, timeout=30)
    if response.status_code == 429:
        print("    Open-Meteo is rate-limited, switching to OpenTopoData")
        USE_BACKUP = True
        return fetch_backup(coords)
    response.raise_for_status()
    return response.json()["elevation"]


USE_BACKUP = "--backup" in sys.argv


def fetch_elevations_old(coords):
    """(previous version, kept for reference)"""
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


def calculate_loss(elevations):
    """Sum of all drops between consecutive points (meters, positive)."""
    return sum(max(0.0, elevations[i - 1] - elevations[i]) for i in range(1, len(elevations)))


def is_loop(coords):
    (lon1, lat1), (lon2, lat2) = coords[0], coords[-1]
    return abs(lat1 - lat2) < 0.0015 and abs(lon1 - lon2) < 0.0018   # ~150 m


def calculate_gain(elevations):
    """Sum of all positive elevation changes between consecutive points."""
    gain = 0.0
    for i in range(1, len(elevations)):
        diff = elevations[i] - elevations[i - 1]
        if diff > 0:
            gain += diff
    return gain


POINTS_PER_REQUEST = 100   # Open-Meteo's max per call
CACHE_DECIMALS = 3          # ~100 m grid, about the DEM's resolution: nearby points share a lookup


def key(lon, lat):
    return (round(lat, CACHE_DECIMALS), round(lon, CACHE_DECIMALS))


with Session(engine) as session:
    # Only routes still missing elevation, so re-running resumes where it left off.
    # Pass --all to recompute every route.
    query = select(Route)
    if "--all" not in sys.argv:
        query = query.where((Route.elevation_gain_m == 0) | (Route.elevation_gain_m == None)  # noqa: E711
                            | (Route.elevation_loss_m == None))  # noqa: E711
    routes = session.exec(query).all()
    print(f"Found {len(routes)} routes to process.")

    # 1. sample each route, and collect the distinct grid points we need
    samples = {}
    for r in routes:
        coords = list(to_shape(r.gps_path).coords)
        samples[r.id] = [key(lon, lat) for lon, lat in sample_points(coords, MAX_POINTS_PER_ROUTE)]
    needed = sorted({k for pts in samples.values() for k in pts})
    print(f"{len(needed)} distinct points to look up "
          f"({(len(needed) + POINTS_PER_REQUEST - 1) // POINTS_PER_REQUEST} requests).")

    # 2. fetch them 100 at a time
    cache = {}
    for b in range(0, len(needed), POINTS_PER_REQUEST):
        chunk = needed[b:b + POINTS_PER_REQUEST]
        try:
            elev = fetch_elevations([(lon, lat) for lat, lon in chunk])
        except Exception as e:
            print(f"Stopped at request {b // POINTS_PER_REQUEST + 1}: {e}")
            print("The free limit is used up for now. Wait about an hour and run this again; "
                  "it saves what it has and resumes.")
            break
        cache.update(zip(chunk, elev))
        print(f"  request {b // POINTS_PER_REQUEST + 1}: {len(cache)}/{len(needed)} points")
        time.sleep(DELAY_BETWEEN_ROUTES_S)

    # 3. score every route whose points are all known, and save
    done = 0
    for r in routes:
        pts = samples[r.id]
        if not all(k in cache for k in pts):
            continue
        elev = [cache[k] for k in pts if cache[k] is not None]
        gain, loss = calculate_gain(elev), calculate_loss(elev)
        r.elevation_gain_m = round(max(gain, 0.1), 1)   # 0.1 = measured flat, so it isn't redone
        r.elevation_loss_m = round(loss, 1)
        if is_loop(list(to_shape(r.gps_path).coords)):
            r.difficulty = classify_difficulty(r.distance_km, r.elevation_gain_m)
        else:
            # point-to-point routes are run out-and-back: rate the whole round trip
            r.difficulty = classify_difficulty(r.distance_km * 2, gain + loss)
        session.add(r)
        done += 1
    session.commit()
    print(f"Done. Updated {done} of {len(routes)} routes.")
