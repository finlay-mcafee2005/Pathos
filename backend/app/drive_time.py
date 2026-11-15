"""
Drive times from the runner to each route's start (or its parking spot), so a
"15 / 30 / 45 min drive" limit means minutes behind the wheel, not a straight-line
radius. A straight line badly undercounts winding hill and canyon roads: one
tester's "within 30 min" pick was a 54-minute drive.

Uses OSRM's car profile (/table service, one origin to many destinations).
Local dev can run its own OSRM car server; production uses the public FOSSGIS
server. OSRM times are free-flow, so they're padded for LA traffic and parking.
If the server can't be reached, fall back to an estimate from road distance.
"""
import json
import math
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

OSRM_CAR_URL = os.environ.get("OSRM_CAR_URL", "https://routing.openstreetmap.de/routed-car").rstrip("/")
USER_AGENT = "Pathos/1.0 (student running-route project)"
TIMEOUT_S = 6
CHUNK = 25                  # destinations per request (public servers cap table size)
TRAFFIC_FACTOR = 1.25       # OSRM assumes empty roads
PARK_MIN = 3                # finding a spot and getting out of the car
# fallback when OSRM is down: streets run ~1.4x the straight line, ~30 km/h average
FALLBACK_ROAD_FACTOR = 1.4
FALLBACK_KMH = 30.0
CACHE_TTL_S = 6 * 3600
_cache: Dict[Tuple, Tuple[float, float]] = {}

Point = Tuple[float, float]   # (lat, lon)


def _km(a: Point, b: Point) -> float:
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def estimate_minutes(origin: Point, dest: Point) -> float:
    """Rough drive time without a routing server."""
    return _km(origin, dest) * FALLBACK_ROAD_FACTOR / FALLBACK_KMH * 60 + PARK_MIN


def _key(p: Point) -> Tuple[float, float]:
    return (round(p[0], 3), round(p[1], 3))      # ~100 m: nearby starts share one lookup


def _table(origin: Point, dests: List[Point]) -> Optional[List[Optional[float]]]:
    """Free-flow seconds from origin to each dest, or None if the request failed."""
    coords = ";".join(f"{lon:.5f},{lat:.5f}" for lat, lon in [origin] + dests)
    url = f"{OSRM_CAR_URL}/table/v1/driving/{coords}?sources=0&annotations=duration"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode())
        if data.get("code") != "Ok":
            return None
        row = data["durations"][0][1:]
        return [None if s is None else float(s) for s in row]
    except Exception as ex:
        print(f"drive-time lookup failed ({type(ex).__name__}: {ex})", flush=True)
        return None


def drive_minutes(origin: Point, dests: List[Point]) -> List[float]:
    """Minutes to drive from origin to each dest (traffic and parking included).
    Unreachable or failed lookups fall back to the road-distance estimate."""
    now = time.time()
    okey = _key(origin)
    out: List[Optional[float]] = [None] * len(dests)
    todo: Dict[Tuple[float, float], List[int]] = {}
    for i, d in enumerate(dests):
        hit = _cache.get((okey, _key(d)))
        if hit and now - hit[0] < CACHE_TTL_S:
            out[i] = hit[1]
        else:
            todo.setdefault(_key(d), []).append(i)

    keys = list(todo)
    chunks = [keys[i:i + CHUNK] for i in range(0, len(keys), CHUNK)]
    if chunks:
        with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
            results = list(pool.map(lambda ks: _table(origin, list(ks)), chunks))
        for ks, secs in zip(chunks, results):
            for j, k in enumerate(ks):
                if secs is None or secs[j] is None:
                    mins = estimate_minutes(origin, k)
                else:
                    mins = secs[j] / 60 * TRAFFIC_FACTOR + PARK_MIN
                    _cache[(okey, k)] = (now, mins)     # only cache real answers
                for i in todo[k]:
                    out[i] = mins
    return [m if m is not None else estimate_minutes(origin, d) for m, d in zip(out, dests)]
