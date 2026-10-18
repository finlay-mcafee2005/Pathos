"""
How messy a route's line is: 0 = a clean loop, lollipop or out-and-back;
higher = a jumble (the line keeps touching or crossing itself, runs along the
same streets several times, or zig-zags block by block).

Used by hide_messy_routes.py (to hide the messy ones already in the catalog)
and load_park_routes.py (so new ones like that never get added).

    mess_score(coords, surface)   coords = [(lon, lat), ...]
    MESSY = 2.0                   at or above this, the route is hidden

What counts (pavement / mixed routes; trails wind naturally, so only the first two):
  - each real X crossing (the line crossing itself at an angle)      1.5 each
  - each stretch run twice beyond a lollipop's stem (2 allowed)     1 each
  - each time the line comes back and briefly touches itself         1 each
  - zig-zagging: sharp turns beyond 4 per km                          0.6 each
"""
import math

from shapely.geometry import LineString
from shapely.strtree import STRtree

MESSY = 2.0
TOUCH_M = 15          # closer than this to an earlier part of the line = touching / running along it


def _project(coords):
    lat0 = sum(c[1] for c in coords) / len(coords)
    kx = 111320 * math.cos(math.radians(lat0))
    return [((x - coords[0][0]) * kx, (y - coords[0][1]) * 110540) for x, y in coords]


def shape_metrics(coords):
    if len(coords) < 3:
        return None
    line = LineString(_project(coords))
    L = line.length
    if L < 200:
        return None
    simple = list(line.simplify(8).coords)

    # real crossings (at an angle, not two pieces running side by side)
    segs = [LineString([a, b]) for a, b in zip(simple, simple[1:]) if a != b]
    tree = STRtree(segs)
    cross = 0
    for i, s in enumerate(segs):
        for j in tree.query(s):
            j = int(j)
            if j > i + 1 and s.crosses(segs[j]):
                (a0, a1), (b0, b1) = s.coords, segs[j].coords
                v1 = (a1[0] - a0[0], a1[1] - a0[1])
                v2 = (b1[0] - b0[0], b1[1] - b0[1])
                sin = abs(v1[0] * v2[1] - v1[1] * v2[0]) / (math.hypot(*v1) * math.hypot(*v2) + 1e-9)
                if sin > 0.5:
                    cross += 1

    # where the line comes back to (or runs along) an earlier part of itself
    step = 10.0
    n = int(L // step)
    pts = [line.interpolate(k * step).coords[0] for k in range(n + 1)]
    grid, flags = {}, []
    for k, (x, y) in enumerate(pts):
        cx, cy = int(x // TOUCH_M), int(y // TOUCH_M)
        hit = any(k - j > 10 and math.dist(pts[j], (x, y)) < TOUCH_M
                  for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in grid.get((cx + dx, cy + dy), ()))
        flags.append(hit)
        grid.setdefault((cx, cy), []).append(k)
    inner = flags[15:-15] if len(flags) > 40 else []     # not the loop closing on its start
    stretches = contacts = run = 0
    for f in inner + [False]:
        if f:
            run += 1
        else:
            stretches += run >= 5          # 50 m+ run twice
            contacts += run >= 1
            run = 0

    turns = 0
    for a, b, c in zip(simple, simple[1:], simple[2:]):
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 >= 20 and n2 >= 20 and (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2) < 0.5:
            turns += 1                     # sharper than 60 degrees
    return dict(cross=cross, stretches=stretches, contacts=contacts, turns_km=turns / (L / 1000))


def mess_score(coords, surface):
    m = shape_metrics(coords)
    if m is None:
        return 0.0
    # a lollipop's shared stem shows up as up to two run-twice stretches: that's fine
    score = 1.5 * m["cross"] + max(0, m["stretches"] - 2)
    if surface in ("pavement", "mixed", "track"):
        touches = m["contacts"] - m["stretches"]          # brief touches, not the stem
        score += touches + 0.6 * max(0, m["turns_km"] - 4)
    return round(score, 1)
