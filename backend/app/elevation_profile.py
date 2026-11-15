"""
Elevation profile for a pick, as the run is actually drawn on the card (started at the
parking spot, run out-and-back, laps, or two routes joined). Built from each route's
saved elevation samples (scripts/update_elevation_profile.py) by walking the drawn line
and taking the height of the nearest sample.
"""
import json
import math
from typing import Dict, List, Optional, Tuple


STEP_KM = 0.04          # walk the drawn line every 40 m
NEAR_KM = 0.08          # nearest saved sample must be this close
CELL = 0.0008           # grid for nearest lookup (~80 m)
MAX_POINTS = 140        # points sent to the browser


def load_samples(session, ids) -> Dict[str, List[Tuple[float, float, float]]]:
    """route id -> [(lat, lon, metres), ...]; routes without a profile are left out."""
    from sqlalchemy import text
    ids = [str(i) for i in ids if i]
    if not ids:
        return {}
    try:
        rows = session.exec(text("SELECT id::text, elev_samples FROM route "
                                 "WHERE id = ANY(CAST(:ids AS uuid[])) AND elev_samples IS NOT NULL"),
                            params={"ids": ids}).all()
    except Exception:            # column not added yet (script not run): no profiles
        session.rollback()
        return {}
    out = {}
    for rid, raw in rows:
        try:
            out[rid] = [(lat / 1e5, lon / 1e5, e) for lon, lat, e in json.loads(raw)]
        except (ValueError, TypeError):
            continue
    return out


def _km(a, b) -> float:
    dy = (a[0] - b[0]) * 110.54
    dx = (a[1] - b[1]) * 111.32 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def _walk(line):
    """Points every STEP_KM along a [[lat, lon], ...] line, their distance along it, and its length."""
    pts, dist = [], []
    along = carry = 0.0
    for a, b in zip(line, line[1:]):
        seg = _km(a, b)
        t = carry
        while t <= seg and seg > 0:
            f = t / seg
            pts.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            dist.append(along + t)
            t += STEP_KM
        carry = t - seg
        along += seg
    pts.append(tuple(line[-1]))          # and the very end
    dist.append(along)
    return pts, dist, along


def _route_heights(pts, samples):
    """Height (m) of each point from the route's saved samples (nearest within NEAR_KM)."""
    grid: Dict[Tuple[int, int], list] = {}
    for s in samples:
        grid.setdefault((int(s[0] // CELL), int(s[1] // CELL)), []).append(s)

    def height(p):
        cy, cx = int(p[0] // CELL), int(p[1] // CELL)
        best, bd = None, NEAR_KM
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for s in grid.get((cy + dy, cx + dx), ()):
                    d = _km(p, s)
                    if d <= bd:
                        best, bd = s[2], d
        return best

    heights = [height(p) for p in pts]
    if not heights or sum(h is None for h in heights) > 0.2 * len(heights):
        return None
    last = next(h for h in heights if h is not None)
    for i, h in enumerate(heights):
        if h is None:
            heights[i] = last
        else:
            last = h
    return heights


# ---- the streets to the start (not in the route data): Open-Meteo's free elevation API ----
ELEV_URL = "https://api.open-meteo.com/v1/elevation"
_elev_cache: Dict[Tuple[float, float], float] = {}


def street_heights(pts) -> Optional[List[float]]:
    """Height (m) of [(lat, lon), ...] points from Open-Meteo (up to 100 per request).
    None if the service can't be reached: the chart then shows the route alone."""
    import urllib.parse
    import urllib.request
    keys = [(round(p[0], 4), round(p[1], 4)) for p in pts]
    todo = [k for k in dict.fromkeys(keys) if k not in _elev_cache]
    for i in range(0, len(todo), 100):
        chunk = todo[i:i + 100]
        url = ELEV_URL + "?" + urllib.parse.urlencode({
            "latitude": ",".join(f"{k[0]:.4f}" for k in chunk),
            "longitude": ",".join(f"{k[1]:.4f}" for k in chunk)})
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Pathos/1.0 (student running-route project)"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                vals = json.loads(resp.read().decode()).get("elevation") or []
        except Exception as ex:
            print(f"street elevation lookup failed ({type(ex).__name__}: {ex})", flush=True)
            return None
        if len(vals) != len(chunk):
            return None
        for k, v in zip(chunk, vals):
            _elev_cache[k] = float(v)
    return [_elev_cache[k] for k in keys]


def profile_for_line(line: List[List[float]], samples: List[Tuple[float, float, float]],
                     repeat: int = 1, approach: Optional[List[List[float]]] = None) -> Optional[dict]:
    """{'mi': [...], 'ft': [...], 'route': [from_mi, to_mi]} for the whole run: the streets from
    where they are to the start (approach), the route (laps repeated), and the same streets
    back. 'route' marks where the route itself starts and ends on the chart. None if there
    isn't enough data for the route."""
    if len(line) < 2 or not samples:
        return None
    pts, dist, lap_km = _walk(line)
    heights = _route_heights(pts, samples)
    if heights is None:
        return None
    # route part, laps repeated
    r_d, r_h = [], []
    for n in range(max(1, repeat)):
        r_d += [n * lap_km + d for d in dist]
        r_h += heights
    route_km = lap_km * max(1, repeat)

    a_d, a_h = [], []
    if approach and len(approach) >= 2:
        a_pts, a_dist, a_km = _walk(approach)
        if len(a_pts) > 100:                                   # one request is enough
            k = len(a_pts) / 100
            idx = sorted(set([int(i * k) for i in range(100)] + [len(a_pts) - 1]))
            a_pts, a_dist = [a_pts[i] for i in idx], [a_dist[i] for i in idx]
        a_h = street_heights(a_pts)
        if a_h:
            # two elevation sources: line the streets up with the route where they meet
            shift = heights[0] - a_h[-1]
            a_h = [h + shift for h in a_h]
            a_d = a_dist
        else:
            a_km = 0.0
    else:
        a_km = 0.0

    mi, ft = [], []
    for d, h in zip(a_d, a_h or []):                            # there
        mi.append(d); ft.append(h)
    for d, h in zip(r_d, r_h):                                  # the route
        mi.append(a_km + d); ft.append(h)
    if a_d:                                                     # and back the same way
        for d, h in zip(reversed(a_d), reversed(a_h)):
            mi.append(a_km + route_km + (a_km - d)); ft.append(h)
    mi = [x * 0.621371 for x in mi]
    ft = [x * 3.28084 for x in ft]
    if len(ft) > MAX_POINTS:
        k = len(ft) / MAX_POINTS
        idx = sorted(set([int(i * k) for i in range(MAX_POINTS)] + [len(ft) - 1]))
        mi, ft = [mi[i] for i in idx], [ft[i] for i in idx]
    return {"mi": [round(x, 3) for x in mi], "ft": [round(x) for x in ft],
            "route": [round(a_km * 0.621371, 3), round((a_km + route_km) * 0.621371, 3)]}
