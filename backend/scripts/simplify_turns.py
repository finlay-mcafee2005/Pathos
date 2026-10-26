"""
Fewer turns: re-draw each road route between points ~0.7-1.6 km apart along it, using
the way with the fewest turns (a turn costs as much as ~150 m of extra running), so
routes follow a few long streets instead of zig-zagging block by block.

A piece is only swapped when the new way has fewer turns and is about as long
(at most 8% longer). The whole route is kept only if it ends up with fewer turns, isn't
messier (no new overlaps or crossings), keeps its start, and stays within 12% of its
old length. Trails, out-and-backs and lollipops are left alone.

Needs scripts/.shade_cache/network.pkl. Run from backend/:
    python3 scripts/simplify_turns.py --cache --preview          # try on the audit cache, drawings only
    DATABASE_URL=... python3 scripts/simplify_turns.py --preview # drawings, nothing saved
    DATABASE_URL=... python3 scripts/simplify_turns.py           # save
    DATABASE_URL=... python3 scripts/simplify_turns.py --undo    # put the old lines back
Then re-measure:
    python3 scripts/update_elevation_dem.py
    python3 scripts/update_shade_canopy.py
    python3 scripts/update_scenic.py
    python3 scripts/update_traffic.py
    python3 scripts/update_route_shape.py
    python3 scripts/update_steepness.py --hide-trail 1
    python3 scripts/update_difficulty.py
"""
import heapq
import json
import math
import os
import pickle
import sys
from collections import defaultdict

from shapely.geometry import Point
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from clean_route_spurs import densify, dist_m, length_m, remove_detours  # noqa: E402
from route_shape import mess_score, shape_metrics  # noqa: E402

NETWORK = os.path.join(HERE, ".shade_cache", "network.pkl")
CACHE = os.path.join(HERE, "audit_output", "routes_cache.pkl")
BACKUP = os.path.join(HERE, "simplify_turns_backup.json")
OUT = os.path.join(HERE, "audit_output", "turns_preview")

SPACINGS = (700, 1100, 1600)   # metres between the points kept from the old route
SNAP_M = 15
TURN_DEG = 40                  # a change of direction sharper than this = a turn
TURN_COST = 150                # metres a turn is "worth"
SEG_STRETCH = (0.75, 1.08)     # a new piece can be shorter, but at most 8% longer
TOTAL_STRETCH = (0.88, 1.12)
# prefer quiet streets; alleys / parking lots and big roads cost more
COST = {"secondary": 1.6, "tertiary": 1.2, "service": 1.6, "footway": 1.15, "path": 1.3,
        "track": 2.0, "bridleway": 2.0, "cycleway": 1.1}
SKIP_HW = {"track", "bridleway"}
LAT0 = 34.15
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110540


def _bear(a, b):
    return math.degrees(math.atan2((b[0] - a[0]) * KX, (b[1] - a[1]) * KY))


def _along(coords, m):
    """Point about m metres along coords from its first point."""
    done = 0.0
    for a, b in zip(coords, coords[1:]):
        d = dist_m(a, b)
        if done + d >= m:
            return b
        done += d
    return coords[-1]


def _diff(a, b):
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


def load_network():
    d = pickle.load(open(NETWORK, "rb"))
    edges, adj = [], defaultdict(list)
    for u, v, length, hw, surface, name, coords in d["edges"]:
        if hw in SKIP_HW or u == v or len(coords) < 2:
            continue
        i = len(edges)
        c = list(coords)
        edges.append((c, length))
        w = length * COST.get(hw, 1.0)
        rc = c[::-1]
        # (to, edge, forward, weight, length, bearing leaving, bearing arriving)
        adj[u].append((v, i, True, w, length, _bear(c[0], _along(c, 25)), _bear(_along(rc, 25), c[-1])))
        adj[v].append((u, i, False, w, length, _bear(rc[0], _along(rc, 25)), _bear(_along(c, 25), rc[-1])))
    ids = list(adj)
    pts = [Point(d["nodes"][n][0] * KX, d["nodes"][n][1] * KY) for n in ids]
    return edges, adj, d["nodes"], ids, STRtree(pts), pts


def snap(p, net):
    _, adj, nodes, ids, tree, npts = net
    q = Point(p[0] * KX, p[1] * KY)
    best = None
    for i in tree.query(q.buffer(SNAP_M)):
        dd = npts[int(i)].distance(q)
        if dd <= SNAP_M and (best is None or dd < best[0]):
            best = (dd, ids[int(i)])
    return best[1] if best else None


def fewest_turns(net, a, b, h_in, h_out, max_len):
    """Cheapest way a -> b where each turn costs TURN_COST; h_in = the heading arriving at a,
    h_out = the heading leaving b (so the joins count too). No U-turns."""
    edges, adj = net[0], net[1]
    start = (a, None)
    best = {start: 0.0}
    info = {start: (None, None, 0.0, h_in)}       # state -> (prev state, (edge, fwd), length, heading)
    heap = [(0.0, 0, start)]
    tick = 0
    while heap:
        cost, _, st = heapq.heappop(heap)
        if cost > best.get(st, 1e18):
            continue
        node = st[0]
        _, _, L, h = info[st]
        if node == b and st != start:
            if h_out is not None and _diff(h, h_out) > TURN_DEG:
                cost += TURN_COST
            # walk back
            path, s = [], st
            while info[s][0] is not None:
                path.append(info[s][1]); s = info[s][0]
            path.reverse()
            coords = []
            for e, fwd in path:
                c = edges[e][0] if fwd else edges[e][0][::-1]
                coords.extend(c if not coords else c[1:])
            return coords, L
        for v, e, fwd, w, ln, hb, ha in adj[node]:
            if L + ln > max_len:
                continue
            turn = 0.0
            if h is not None:
                dd = _diff(h, hb)
                if dd > 150:
                    continue                    # no U-turns
                if dd > TURN_DEG:
                    turn = TURN_COST
            ns = (v, e)
            nc = cost + w + turn
            if nc < best.get(ns, 1e18):
                best[ns] = nc
                info[ns] = (st, (e, fwd), L + ln, ha)
                tick += 1
                heapq.heappush(heap, (nc, tick, ns))
    return None


def count_turns(pts):
    """Real turns: corners sharper than 50 degrees once the line is smoothed to 10 m
    (so gentle curves and GPS wiggle don't count), with at least 15 m on each side."""
    from shapely.geometry import LineString
    if len(pts) < 3:
        return 0
    simple = list(LineString([(x * KX, y * KY) for x, y in pts]).simplify(10).coords)
    turns = 0
    for a, b, c in zip(simple, simple[1:], simple[2:]):
        v1 = (b[0] - a[0], b[1] - a[1]); v2 = (c[0] - b[0], c[1] - b[1])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 >= 15 and n2 >= 15 and (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2) < math.cos(math.radians(50)):
            turns += 1
    return turns


def simplify(coords, surface, net, spacing):
    pts = densify(coords, 10.0)
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + dist_m(a, b))
    total = cum[-1]
    stops, last = [], None
    for i, p in enumerate(pts):
        n = snap(p, net)
        if n is not None and n != last:
            stops.append((i, n))
        last = n if n is not None else last
    if len(stops) < 3:
        return None
    # the junctions we keep: roughly every `spacing` metres, plus the first and last
    anchors = [stops[0]]
    for i, n in stops[1:-1]:
        if cum[i] - cum[anchors[-1][0]] >= spacing:
            anchors.append((i, n))
    if cum[stops[-1][0]] - cum[anchors[-1][0]] < spacing * 0.4 and len(anchors) > 1:
        anchors.pop()
    anchors.append(stops[-1])
    new, changed = [], 0
    new.extend(pts[:anchors[0][0] + 1])
    for (i, a), (j, b) in zip(anchors, anchors[1:]):
        old = pts[i:j + 1]
        L = cum[j] - cum[i]
        h_in = _bear(pts[max(0, i - 3)], pts[i]) if i >= 3 else None
        h_out = _bear(pts[j], pts[min(len(pts) - 1, j + 3)]) if j + 3 < len(pts) else None
        ctx_a = pts[max(0, i - 4):i]
        ctx_b = pts[j + 1:j + 5]
        res = fewest_turns(net, a, b, h_in, h_out, L * SEG_STRETCH[1]) if a != b else None
        if res and len(res[0]) > 1:
            c, ln = res
            if SEG_STRETCH[0] * L <= ln <= SEG_STRETCH[1] * L and \
                    count_turns(ctx_a + c + ctx_b) < count_turns(ctx_a + old + ctx_b):
                new.extend(c[1:-1] if new else c[:-1])
                new.append(pts[j])
                changed += 1
                continue
        new.extend(old[1:])
    new.extend(pts[anchors[-1][0] + 1:])
    if not changed:
        return None
    new, _ = remove_detours(new)
    nl = length_m(new)
    if not (TOTAL_STRETCH[0] * total <= nl <= TOTAL_STRETCH[1] * total):
        return None
    if dist_m(new[0], coords[0]) > 60 or dist_m(new[-1], coords[-1]) > 60:
        return None
    if mess_score(new, surface) > mess_score(coords, surface):
        return None
    m = shape_metrics(new)
    if m and (m["cross"] > (shape_metrics(coords) or {"cross": 0})["cross"]):
        return None
    t0, t1 = count_turns(coords), count_turns(new)
    if t0 - t1 < max(3, 0.15 * t0):
        return None                       # not enough simpler to be worth changing
    s0, s1 = shape_metrics(coords), shape_metrics(new)
    if s0 and s1 and s1["turns_km"] * nl > s0["turns_km"] * total:
        return None
    return new, t0, t1


def overlap_share(coords):
    """Share of the line that runs along a part of itself 150 m+ earlier (a stem or an out-and-back)."""
    pts = densify(coords, 10.0)
    grid, hits = {}, 0
    for k, (x, y) in enumerate(pts):
        gx, gy = int(x * KX // 15), int(y * KY // 15)
        if any(k - j > 15 and dist_m(pts[j], (x, y)) < 15
               for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in grid.get((gx + dx, gy + dy), ())):
            hits += 1
        grid.setdefault((gx, gy), []).append(k)
    return hits / max(1, len(pts))


NET = None


def _one(args):
    coords, surface = args
    if surface != "pavement":
        return None
    loop = dist_m(coords[0], coords[-1]) < 50
    if not loop or overlap_share(coords) > 0.3:
        return None          # out-and-backs and lollipops (much of the line run twice): leave alone
    best = None
    for s in SPACINGS:
        try:
            r = simplify(coords, surface, NET, s)
        except Exception:
            r = None
        if r and (best is None or r[2] < best[2]):
            best = r
    return best


def write_previews(changes):
    os.makedirs(OUT, exist_ok=True)
    cards = []
    for n, (rid, name, km, old, new, t0, t1) in enumerate(changes):
        xs = [p[0] for p in old + new]; ys = [p[1] for p in old + new]
        kx = math.cos(math.radians(sum(ys) / len(ys)))
        sc = 380 / max((max(xs) - min(xs)) * kx or 1e-6, (max(ys) - min(ys)) or 1e-6)

        def poly(ps):
            return " ".join(f"{20 + (x - min(xs)) * kx * sc:.1f},{20 + (max(ys) - y) * sc:.1f}" for x, y in ps)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="440" viewBox="0 0 420 440">'
               f'<rect width="420" height="440" fill="#fff"/>'
               f'<polyline points="{poly(old)}" fill="none" stroke="#f87171" stroke-width="6" stroke-linejoin="round"/>'
               f'<polyline points="{poly(new)}" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linejoin="round"/>'
               f'<text x="10" y="425" font-family="sans-serif" font-size="12">{name[:34]}: {t0} -> {t1} turns, '
               f'{length_m(old) / 1609.34:.2f} -> {length_m(new) / 1609.34:.2f} mi</text></svg>')
        fn = f"route_{n:03d}.svg"
        open(os.path.join(OUT, fn), "w").write(svg)
        cards.append(f'<img src="{fn}" width="300">')
    open(os.path.join(OUT, "index.html"), "w").write(
        "<html><body style='font-family:sans-serif'><p>Red = before, blue = after (fewer turns).</p>"
        "<div style='display:flex;flex-wrap:wrap;gap:6px'>" + "".join(cards) + "</div></body></html>")
    print(f"\nPreview drawings: {OUT}/index.html")


def to_wkt(c):
    return "LINESTRING(" + ", ".join(f"{x:.7f} {y:.7f}" for x, y in c) + ")"


def main():
    from sqlalchemy import create_engine, text
    if "--undo" in sys.argv:
        saved = json.load(open(BACKUP))
        engine = create_engine(os.environ["DATABASE_URL"])
        with engine.begin() as conn:
            for rid, (wkt, km) in saved.items():
                conn.execute(text("UPDATE route SET gps_path = ST_GeomFromText(:w, 4326), distance_km = :d, "
                                  "shade_pct = NULL WHERE id = :id"), {"w": wkt, "d": km, "id": rid})
        print(f"Put back {len(saved)} routes. Re-run the re-measure scripts.")
        return
    use_cache = "--cache" in sys.argv
    if use_cache:
        rows = [(r["id"], r["nickname"] or r["name"], r["distance_km"], r["surface_type"], r["coords"])
                for r in pickle.load(open(CACHE, "rb")) if not r.get("hidden")]
    else:
        if "DATABASE_URL" not in os.environ:
            sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
        engine = create_engine(os.environ["DATABASE_URL"])
        with engine.connect() as conn:
            raw = conn.execute(text("SELECT id, COALESCE(nickname, name), distance_km, surface_type, "
                                    "ST_AsText(gps_path) FROM route WHERE NOT COALESCE(hidden, FALSE)")).all()
        rows = [(rid, name, km, surf, [tuple(map(float, p.split())) for p in wkt[wkt.index("(") + 1:-1].split(",")])
                for rid, name, km, surf, wkt in raw if wkt and wkt.startswith("LINESTRING")]
    if "--only" in sys.argv:
        word = sys.argv[sys.argv.index("--only") + 1].lower()
        rows = [r for r in rows if word in (r[1] or "").lower()]
    if "--limit" in sys.argv:
        rows = rows[:int(sys.argv[sys.argv.index("--limit") + 1])]
    global NET
    print("Loading the street network...", flush=True)
    NET = load_network()
    from multiprocessing import get_context
    print(f"Checking {len(rows)} routes...", flush=True)
    with get_context("fork").Pool(max(1, os.cpu_count() or 2)) as pool:
        results = pool.map(_one, [(c, s) for _, _, _, s, c in rows], chunksize=4)
    changes = [(rid, name, km, coords, res[0], res[1], res[2])
               for (rid, name, km, surf, coords), res in zip(rows, results) if res]
    changes.sort(key=lambda c: -(c[5] - c[6]))
    print(f"\n{len(rows)} routes checked; {len(changes)} can be simpler "
          f"({sum(c[5] - c[6] for c in changes)} turns fewer in all).")
    for rid, name, km, old, new, t0, t1 in changes[:25]:
        print(f"  {(name or '')[:42]:<42} {t0:3d} -> {t1:3d} turns   {length_m(old) / 1609.34:5.2f} -> {length_m(new) / 1609.34:5.2f} mi")
    if "--preview" in sys.argv or "--dry-run" in sys.argv or use_cache:
        if "--preview" in sys.argv:
            write_previews(changes)
        print("\nPreview only: nothing saved.")
        return
    old = json.load(open(BACKUP)) if os.path.exists(BACKUP) else {}
    for rid, name, km, oc, *_ in changes:
        old.setdefault(str(rid), [to_wkt(oc), km])
    json.dump(old, open(BACKUP, "w"))
    with engine.begin() as conn:
        for rid, name, km, oc, new, t0, t1 in changes:
            conn.execute(text("UPDATE route SET gps_path = ST_GeomFromText(:w, 4326), distance_km = :d, "
                              "shade_pct = NULL WHERE id = :id"),
                         {"w": to_wkt(new), "d": round(length_m(new) / 1000, 3), "id": rid})
    print(f"\nSimplified {len(changes)} routes. Now run the re-measure scripts listed at the top of this file.")


if __name__ == "__main__":
    main()
