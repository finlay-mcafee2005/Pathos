"""
Round 4 of the route generator: long loops (10, 12 and 14 mi) near Oxy, for long
runs. The cleanup (no stems, no jogs, no unrunnable hills) left few routes this long,
so long-run check-ins kept getting 2 laps of something shorter.

Each loop: out from a start point to a far turnaround, back a different way.
Preferences: paths, parks and quiet streets over busy roads; few turns; no stretch run
twice (stems are cut, same as loopify_routes.py); not jumbled (route_shape.py).
Start points: a grid every ~1.5 km within ~7 km of Oxy.

Run from backend/ (in chunks; run until "All done"):
    python3 scripts/generate_long_loops.py
Then load (dry run first) and measure, like the other rounds:
    DATABASE_URL=... python3 scripts/load_park_routes.py --src long_loops.json --max 120 --dry-run
    DATABASE_URL=... python3 scripts/load_park_routes.py --src long_loops.json --max 120
    (then the measuring scripts: see the end of this run's output)
"""
import json
import math
import os
import sys
import time

import networkx as nx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_park_routes as gp      # noqa: E402
import generate_more_routes as gm      # noqa: E402
from route_shape import mess_score, shape_metrics, MESSY  # noqa: E402
from loopify_routes import loopify  # noqa: E402
from clean_route_spurs import length_m  # noqa: E402

OUT = os.path.join(gp.CACHE, "long_loops.json")
TIME_BUDGET_S = float(os.getenv("TIME_BUDGET_S", "140"))
MI = gp.MI
OXY = (-118.2108, 34.1270)
GRID_M = 1500
RADIUS_M = 7000
TARGETS_M = [10 * MI, 12 * MI, 14 * MI]
BUSY = {"secondary": 2.2, "tertiary": 1.4}     # extra cost on top of gp.COST: stay off busy roads
MAX_TURNS_KM = 4.5
# spots where the first batch hit barely-runnable climbs (25%+, update_steepness.py):
# stairways / embankment paths. The generator now routes around them.
STEEP_SPOTS = [
    (34.18759, -118.26677), (34.14916, -118.22360), (34.20069, -118.27081), (34.09888, -118.19991),
    (34.12925, -118.28445), (34.18439, -118.27244), (34.13442, -118.29818), (34.18596, -118.25680),
    (34.13364, -118.31424), (34.08148, -118.19882), (34.13479, -118.33351), (34.09509, -118.21974),
    (34.19908, -118.21802), (34.19898, -118.21851), (34.19205, -118.20795), (34.11932, -118.28113),
    (34.10924, -118.21338), (34.07585, -118.19000),
]
AVOID_M = 120
MAX_BUSY = 0.30


def main():
    t0 = time.time()
    state = json.load(open(OUT)) if os.path.exists(OUT) else {"done": [], "routes": []}
    G, d = gp.load()
    for n in G.nodes:
        lon, lat = d["nodes"][n]
        G.nodes[n]["xy_ll"] = (lon, lat)
        G.nodes[n]["xy"] = gp.m(lon, lat)
    green = gm.green_edges(G)
    for u, v, e in G.edges(data=True):
        g = (min(u, v), max(u, v)) in green
        e["green"] = g or e["hw"] in ("footway", "path", "track", "cycleway", "pedestrian", "bridleway")
        e["w"] = e["length"] * gp.COST.get(e["hw"], 2.5) * BUSY.get(e["hw"], 1.0) * (0.5 if e["green"] else 1.0)
    # route around the known too-steep spots: any edge passing within AVOID_M is (nearly) off limits
    spots = [gp.m(lon, lat) for lat, lon in STEEP_SPOTS]
    blocked = 0
    for u, v, e in G.edges(data=True):
        pts = [gp.m(*c) for c in e["coords"]]
        if any(math.dist(p, s) <= AVOID_M for p in pts for s in spots):
            e["w"] *= 200
            e["steep"] = True
            blocked += 1
    print(f"Network ready ({time.time() - t0:.0f}s); {blocked} segments near known steep spots avoided")

    cx, cy = gp.m(*OXY)
    xy = [(n, G.nodes[n]["xy"]) for n in G.nodes]
    steps = int(RADIUS_M // GRID_M)
    grid = [(cx + i * GRID_M, cy + j * GRID_M)
            for i in range(-steps, steps + 1) for j in range(-steps, steps + 1)
            if math.hypot(i * GRID_M, j * GRID_M) <= RADIUS_M]
    grid.sort(key=lambda p: math.dist(p, (cx, cy)))          # closest to Oxy first
    done = set(state["done"])
    finished = True
    for gx, gy in grid:
        key = f"{gx:.0f},{gy:.0f}"
        if key in done:
            continue
        if time.time() - t0 > TIME_BUDGET_S:
            finished = False
            break
        done.add(key)
        box = [n for n, (x, y) in xy if abs(x - gx) <= 13000 and abs(y - gy) <= 13000]
        H = G.subgraph(box)
        near = sorted((n for n, (x, y) in xy if abs(x - gx) <= 400 and abs(y - gy) <= 400 and n in H),
                      key=lambda n: math.dist(G.nodes[n]["xy"], (gx, gy)))
        if not near:
            continue
        s = near[0]
        pred, dist = nx.dijkstra_predecessor_and_distance(H, s, weight="w", cutoff=2.5 * max(TARGETS_M))
        real = {s: 0.0}                     # real metres along the cheapest path, built in one pass
        for n in sorted(dist, key=dist.get):
            if n != s:
                p0 = pred[n][0]
                real[n] = real[p0] + H[p0][n]["length"]

        def path_to(t):
            out = [t]
            while out[-1] != s:
                out.append(pred[out[-1]][0])
            return out[::-1]
        lon0, lat0 = G.nodes[s]["xy_ll"]
        place = gp.place_name(d["places"], lon0, lat0) or min(       # no place within 2.5 km: the nearest one
            d["places"], key=lambda pl: ((pl[1] - lon0) * math.cos(math.radians(lat0))) ** 2 + (pl[2] - lat0) ** 2)[0]
        for L in TARGETS_M:
            cands = [n for n, dd in real.items() if 0.38 * L <= dd <= 0.50 * L]
            # far away AND spread around the compass, so the loops differ
            cands.sort(key=lambda n: -math.dist(H.nodes[n]["xy"], H.nodes[s]["xy"]))
            picked, best = [], None
            for t in cands:
                ang = math.atan2(H.nodes[t]["xy"][1] - gy, H.nodes[t]["xy"][0] - gx)
                if any(abs((ang - a + math.pi) % (2 * math.pi) - math.pi) < 0.6 for a in picked):
                    continue
                picked.append(ang)
                if len(picked) > 6:
                    break
                out = path_to(t)
                pen = {(min(a, b), max(a, b)) for a, b in gp.path_edges(out)}
                try:
                    back = nx.dijkstra_path(H, t, s, weight=lambda a, b, e: e["w"] * (8 if (min(a, b), max(a, b)) in pen else 1))
                except nx.NetworkXNoPath:
                    continue
                nodes = out + back[1:]
                if any(H[a][b].get("steep") for a, b in gp.path_edges(nodes)):
                    continue                            # no way around the steep spot from here
                sm = gp.summarize(H, nodes)
                if not sm or sm["retrace"] > 0.15:
                    continue
                coords = gp.stitch(H, nodes)
                cut = loopify(coords, sm["surface"])           # no stems
                if cut:
                    coords = cut[0]
                km = length_m(coords)
                if abs(km - L) > 0.12 * L:
                    continue
                if mess_score(coords, sm["surface"]) >= MESSY:
                    continue
                shp = shape_metrics(coords)
                turns = shp["turns_km"] if shp else 9
                if turns > MAX_TURNS_KM:
                    continue
                edges = gp.path_edges(nodes)
                total = sum(H[a][b]["length"] for a, b in edges)
                busy = sum(H[a][b]["length"] for a, b in edges if H[a][b]["hw"] in BUSY) / total
                gshare = sum(H[a][b]["length"] for a, b in edges if H[a][b]["green"]) / total
                if busy > MAX_BUSY:
                    continue
                q = 0.45 * gshare + 0.25 * (1 - turns / MAX_TURNS_KM) + 0.2 * (1 - busy / MAX_BUSY) \
                    + 0.1 * (1 - sm["retrace"])
                if best is None or q > best[0]:
                    best = (q, coords, sm, gshare, km)
            if best:
                q, coords, sm, gshare, km = best
                state["routes"].append(dict(kind="long_loop", park=f"{place}|{key}|{L:.0f}",
                                            name=f"{place} Long Loop", coords=coords, length_m=round(km),
                                            surface=sm["surface"], in_park=round(gshare, 2),
                                            retrace=round(sm["retrace"], 2), quality=round(q, 3), loop=True))
    state["done"] = sorted(done)
    json.dump(state, open(OUT, "w"))
    left = sum(1 for gx, gy in grid if f"{gx:.0f},{gy:.0f}" not in done)
    by = {}
    for r in state["routes"]:
        b = round(r["length_m"] / MI)
        by[b] = by.get(b, 0) + 1
    print(f"{len(state['routes'])} long loops so far (by miles: {dict(sorted(by.items()))}); "
          f"{left} start points left.")
    if finished and left == 0:
        print("All done. Next: python3 scripts/load_park_routes.py --src long_loops.json --max 120 --dry-run")


if __name__ == "__main__":
    main()
