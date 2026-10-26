"""
Turn-by-turn cues for a route, from the self-hosted OSRM server (foot profile).

We send OSRM the route's own line and ask it to map-match it (the /match
service) so the cues follow *our* route rather than OSRM's idea of the
shortest path. If matching fails, we fall back to /route through the
route's turning points. Each OSRM step becomes a short cue like
"Turn right onto Monterey Road".
"""

import hashlib
import json
import math
import os
import urllib.parse
import urllib.request
from typing import List, Optional, Tuple

# Local dev: self-hosted OSRM on port 5001.
# Production: set OSRM_URL to the public FOSSGIS foot server,
#   https://routing.openstreetmap.de/routed-foot
OSRM_URL = os.environ.get("OSRM_URL", "http://localhost:5001").rstrip("/")
# public OSM servers ask clients to identify themselves
USER_AGENT = "Pathos/1.0 (student running-route project)"
TIMEOUT_S = 8
MAX_MATCH_POINTS = 100          # OSRM's default --max-matching-size
MAX_ROUTE_POINTS = 100
_cache: dict = {}

Point = Tuple[float, float]     # (lat, lon)


# --- geometry ----------------------------------------------------------------

def meters(a: Point, b: Point) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def resample(path: List[Point], max_points: int) -> List[Point]:
    """Evenly spaced points along the path (keeps first and last)."""
    if len(path) <= max_points:
        return path
    cum = [0.0]
    for i in range(1, len(path)):
        cum.append(cum[-1] + meters(path[i - 1], path[i]))
    total = cum[-1]
    out, j = [path[0]], 0
    for k in range(1, max_points - 1):
        target = total * k / (max_points - 1)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        out.append(path[j + 1])
    out.append(path[-1])
    return out


def _offset(p: Point, a: Point, b: Point) -> float:
    k = math.cos(math.radians(a[0])) * 111320
    ax, ay, bx, by, px, py = a[1] * k, a[0] * 110540, b[1] * k, b[0] * 110540, p[1] * k, p[0] * 110540
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2)) if l2 else 0.0
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def simplify(path: List[Point], tol: float) -> List[Point]:
    if len(path) < 3:
        return path
    idx, dmax = 0, 0.0
    for i in range(1, len(path) - 1):
        d = _offset(path[i], path[0], path[-1])
        if d > dmax:
            idx, dmax = i, d
    if dmax <= tol:
        return [path[0], path[-1]]
    return simplify(path[: idx + 1], tol)[:-1] + simplify(path[idx:], tol)


# --- OSRM calls --------------------------------------------------------------

def _get(url: str) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _coords(points: List[Point]) -> str:
    return ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in points)


def _osrm_match(path: List[Point]) -> Optional[List[dict]]:
    pts = resample(path, MAX_MATCH_POINTS)
    # fake timestamps at a running pace so OSRM expects steady forward motion
    ts, t = [], 0.0
    for i, p in enumerate(pts):
        if i:
            t += max(1.0, meters(pts[i - 1], p) / 3.0)
        ts.append(str(int(t)))
    params = urllib.parse.urlencode({
        "steps": "true",
        "overview": "false",
        "tidy": "true",
        "gaps": "ignore",
        "timestamps": ";".join(ts),
        "radiuses": ";".join(["25"] * len(pts)),
    })
    data = _get(f"{OSRM_URL}/match/v1/foot/{_coords(pts)}?{params}")
    if not data or data.get("code") != "Ok" or not data.get("matchings"):
        return None
    steps = []
    for matching in data["matchings"]:
        for leg in matching.get("legs", []):
            steps.extend(leg.get("steps", []))
    return steps or None


def _osrm_route(path: List[Point]) -> Optional[List[dict]]:
    tol, pts = 15.0, simplify(path, 15.0)
    while len(pts) > MAX_ROUTE_POINTS:
        tol *= 1.5
        pts = simplify(path, tol)
    params = urllib.parse.urlencode({"steps": "true", "overview": "false", "continue_straight": "true"})
    data = _get(f"{OSRM_URL}/route/v1/foot/{_coords(pts)}?{params}")
    if not data or data.get("code") != "Ok" or not data.get("routes"):
        return None
    steps = []
    for leg in data["routes"][0].get("legs", []):
        steps.extend(leg.get("steps", []))
    return steps or None


# --- steps -> cues -----------------------------------------------------------

TURN_WORDS = {
    "uturn": "Turn around",
    "sharp right": "Sharp right",
    "right": "Turn right",
    "slight right": "Bear right",
    "straight": "Continue straight",
    "slight left": "Bear left",
    "left": "Turn left",
    "sharp left": "Sharp left",
}
TURN_TYPES = {"turn", "end of road", "fork", "merge", "on ramp", "off ramp", "roundabout", "rotary",
              "roundabout turn", "exit roundabout", "exit rotary", "new name", "continue"}


def _street(step: dict) -> str:
    name = (step.get("name") or "").strip()
    ref = (step.get("ref") or "").strip()
    return name or ref


def _compass(bearing: Optional[float]) -> str:
    if bearing is None:
        return ""
    dirs = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]
    return dirs[int(((bearing % 360) + 22.5) // 45) % 8]


def steps_to_cues(steps: List[dict]) -> List[dict]:
    cues: List[dict] = []
    for i, step in enumerate(steps):
        m = step.get("maneuver", {})
        kind, mod = m.get("type", ""), m.get("modifier", "")
        loc = m.get("location") or [None, None]
        street = _street(step)
        text = None
        icon = mod or "straight"

        if kind == "depart":
            if cues:          # depart of a later leg/matching = not a real turn
                continue
            heading = _compass(m.get("bearing_after"))
            text = f"Head {heading} on {street}" if street else f"Head {heading}"
            icon = "depart"
        elif kind == "arrive":
            if i != len(steps) - 1:
                continue
            text = "You've finished the route"
            icon = "finish"
        elif kind in TURN_TYPES:
            if mod in ("straight", "") and kind in ("continue", "new name", "fork", "merge"):
                # only worth a cue if the street name changes to a named one
                if kind == "new name" and street and (not cues or cues[-1]["street"] != street):
                    text = f"Continue onto {street}"
                else:
                    continue
            else:
                verb = TURN_WORDS.get(mod, "Turn")
                if mod == "uturn":
                    text = "Turn around" + (f" on {street}" if street else "")
                else:
                    text = f"{verb} onto {street}" if street else f"{verb} onto the path"
        else:
            continue

        if text is None or loc[0] is None:
            continue
        cue = {"text": text, "street": street, "icon": icon,
               "lat": round(loc[1], 6), "lon": round(loc[0], 6)}
        # merge cues that land on almost the same spot (keep the later, more specific one)
        if cues and meters((cues[-1]["lat"], cues[-1]["lon"]), (cue["lat"], cue["lon"])) < 15 \
                and cues[-1]["icon"] not in ("depart", "finish"):
            cues[-1] = cue
        else:
            cues.append(cue)
    return cues


def directions_for(path: List[Point]) -> Optional[dict]:
    """Cues for a [(lat, lon), ...] path, or None if OSRM is unavailable."""
    if len(path) < 2:
        return None
    key = hashlib.sha1(_coords(path).encode()).hexdigest()
    if key in _cache:
        return _cache[key]
    source = "match"
    steps = _osrm_match(path)
    if steps is None:
        source = "route"
        steps = _osrm_route(path)
    if steps is None:
        return None
    result = {"source": source, "cues": steps_to_cues(steps)}
    _cache[key] = result
    return result


TURN_COST_M = 150        # a turn is "worth" ~150 m: a slightly longer way with fewer turns wins
MAX_DETOUR = 1.2         # ...but never more than 20% longer than the shortest way


def _turns(route: dict) -> int:
    """Real turns in an OSRM route (not slight bends or name changes)."""
    n = 0
    for leg in route.get("legs", []):
        for st in leg.get("steps", []):
            m = st.get("maneuver", {})
            if m.get("type") in ("depart", "arrive", "new name", "continue") and \
                    m.get("modifier") in (None, "", "straight", "slight left", "slight right"):
                continue
            if m.get("modifier") in ("straight", "slight left", "slight right"):
                continue
            n += 1
    return n


def _simplest_foot_route(a: Point, b: Point) -> Optional[dict]:
    """The foot route a -> b with the fewest turns (OSRM's alternatives), as long as it's
    within 20% of the shortest. Shared by the card's line and the follow page's directions
    so both show the same way."""
    key = ("simple", round(a[0], 5), round(a[1], 5), round(b[0], 5), round(b[1], 5))
    if key in _cache:
        return _cache[key]
    params = urllib.parse.urlencode({"steps": "true", "overview": "full", "geometries": "geojson",
                                     "alternatives": "3"})
    try:     # short timeout: this runs for every pick while the recommendations load
        req = urllib.request.Request(
            f"{OSRM_URL}/route/v1/foot/{a[1]:.6f},{a[0]:.6f};{b[1]:.6f},{b[0]:.6f}?{params}",
            headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=4) as r:
            data = json.load(r)
    except Exception:
        data = None
    if not data or data.get("code") != "Ok" or not data.get("routes"):
        return None
    routes = data["routes"]
    shortest = min(float(r.get("distance", 0)) for r in routes)
    ok = [r for r in routes if float(r.get("distance", 0)) <= shortest * MAX_DETOUR]
    best = min(ok, key=lambda r: float(r.get("distance", 0)) + TURN_COST_M * _turns(r))
    _cache[key] = best
    return best


def walk_path(a: Point, b: Point) -> Tuple[List[Point], float]:
    """Foot route from a to b (lat, lon) as (path, metres): the way with the fewest turns.
    Falls back to a straight line (x1.3) if the routing server is slow or unavailable."""
    route = _simplest_foot_route(a, b)
    if route is None:
        return [a, b], meters(a, b) * 1.3
    return [(lat, lon) for lon, lat in route["geometry"]["coordinates"]], float(route["distance"])


def to_start(a: Point, b: Point) -> Optional[dict]:
    """Walking/jogging directions from where the runner is to the start of the route:
    {path: [(lat, lon)...], distance_m, cues: [...]}. None if routing is unavailable."""
    route = _simplest_foot_route(a, b)
    if route is None:
        return None
    steps = [st for leg in route.get("legs", []) for st in leg.get("steps", [])]
    cues = steps_to_cues(steps)
    if cues and cues[-1]["icon"] == "finish":
        cues[-1]["text"] = "You're at the start of the route"
    return {"path": [(lat, lon) for lon, lat in route["geometry"]["coordinates"]],
            "distance_m": round(float(route.get("distance", 0))), "cues": cues}
