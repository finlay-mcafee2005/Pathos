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


def profile_for_line(line: List[List[float]], samples: List[Tuple[float, float, float]],
                     repeat: int = 1) -> Optional[dict]:
    """{'mi': [...], 'ft': [...]} along a [[lat, lon], ...] line, or None if too little data."""
    if len(line) < 2 or not samples:
        return None
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

    # walk the line every STEP_KM
    pts, dist = [], []
    along = 0.0
    carry = 0.0
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
    heights = [height(p) for p in pts]
    if not heights or sum(h is None for h in heights) > 0.2 * len(heights):
        return None
    # fill small gaps from neighbours
    last = next(h for h in heights if h is not None)
    for i, h in enumerate(heights):
        if h is None:
            heights[i] = last
        else:
            last = h
    lap_km = along
    mi, ft = [], []
    for n in range(max(1, repeat)):
        for d, h in zip(dist, heights):
            mi.append((n * lap_km + d) * 0.621371)
            ft.append(h * 3.28084)
    if len(ft) > MAX_POINTS:
        k = len(ft) / MAX_POINTS
        idx = [int(i * k) for i in range(MAX_POINTS)] + [len(ft) - 1]
        mi, ft = [mi[i] for i in idx], [ft[i] for i in idx]
    return {"mi": [round(x, 3) for x in mi], "ft": [round(x) for x in ft]}
