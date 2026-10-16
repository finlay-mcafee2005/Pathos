"""
Round 3 of the route generator: "green loops" from neighbourhoods all over the
area - 3 to 7 mile loops that prefer paths, parks, the river and tree-lined
streets over plain grids - plus longer LA River / Arroyo runs (up to 6 mi out).

Start points are a grid every ~1.5 km across the app's area, so every
neighbourhood gets nearby options (helps rough days, when people stay close).

Run from backend/ (in chunks; run until "All done"):
    python3 scripts/generate_green_loops.py
Load with:
    python3 scripts/load_park_routes.py --src green_loops.json --max 400 --dry-run
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

OUT = os.path.join(gp.CACHE, "green_loops.json")
TIME_BUDGET_S = float(os.getenv("TIME_BUDGET_S", "140"))
MI = gp.MI
GRID_M = 1500
RADIUS_M = 13000
TARGETS_M = [3 * MI, 4 * MI, 5 * MI, 6 * MI, 7 * MI]
MIN_GREEN = 0.35


def main():
    t0 = time.time()
    state = json.load(open(OUT)) if os.path.exists(OUT) else {"done": [], "long_done": False, "routes": []}
    G, d = gp.load()
    for n in G.nodes:
        lon, lat = d["nodes"][n]
        G.nodes[n]["xy_ll"] = (lon, lat)
        G.nodes[n]["xy"] = gp.m(lon, lat)
    green = gm.green_edges(G)
    for u, v, e in G.edges(data=True):
        g = (min(u, v), max(u, v)) in green
        e["green"] = g or e["hw"] in ("footway", "path", "track", "cycleway", "pedestrian", "bridleway")
        e["w"] = e["length"] * gp.COST.get(e["hw"], 2.5) * (0.45 if e["green"] else 1.0)
    print(f"Network ready ({time.time() - t0:.0f}s)")

    if not state["long_done"]:
        gp.PATH_TARGETS_M = [5 * MI, 6 * MI]            # longer river/greenway runs this round
        long_runs = gp.greenway_runs(G, d["places"])
        state["routes"] += long_runs
        state["long_done"] = True
        print(f"  {len(long_runs)} long river/greenway runs")

    cx, cy = gp.m(-118.22, 34.15)
    xy = [(n, G.nodes[n]["xy"]) for n in G.nodes]
    grid = [(cx + i * GRID_M, cy + j * GRID_M)
            for i in range(-9, 10) for j in range(-9, 10)
            if math.hypot(i * GRID_M, j * GRID_M) <= RADIUS_M]
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
        box = [n for n, (x, y) in xy if abs(x - gx) <= 6000 and abs(y - gy) <= 6000]
        if len(box) < 50:
            continue
        H = G.subgraph(box)
        # start at a junction near the grid point that touches something green
        near = sorted((n for n, (x, y) in xy if abs(x - gx) <= 400 and abs(y - gy) <= 400),
                      key=lambda n: (not any(H[n][k]["green"] for k in H[n]) if n in H else True,
                                     math.dist(G.nodes[n]["xy"], (gx, gy))))
        if not near or near[0] not in H:
            continue
        s = near[0]
        _, paths = nx.single_source_dijkstra(H, s, weight="w", cutoff=2.2 * max(TARGETS_M))
        real = {n: sum(H[a][b]["length"] for a, b in gp.path_edges(p)) for n, p in paths.items()}
        place = gp.place_name(d["places"], *G.nodes[s]["xy_ll"]) or "Neighborhood"
        for L in TARGETS_M:
            cands = [n for n, dd in real.items() if 0.38 * L <= dd <= 0.52 * L]
            cands.sort(key=lambda n: -math.dist(H.nodes[n]["xy"], H.nodes[s]["xy"]))
            best = None
            for t in cands[:6]:
                out = paths[t]
                pen = {(min(a, b), max(a, b)) for a, b in gp.path_edges(out)}
                try:
                    back = nx.dijkstra_path(H, t, s, weight=lambda a, b, e: e["w"] * (6 if (min(a, b), max(a, b)) in pen else 1))
                except nx.NetworkXNoPath:
                    continue
                nodes = out + back[1:]
                sm = gp.summarize(H, nodes)
                if not sm or abs(sm["length"] - L) > gp.LEN_TOL * L or sm["retrace"] > gp.MAX_RETRACE:
                    continue
                gshare = sum(H[a][b]["length"] for a, b in gp.path_edges(nodes) if H[a][b]["green"]) / sm["length"]
                if gshare < MIN_GREEN:
                    continue
                q = 0.8 * gshare + 0.4 * (1 - sm["retrace"])
                if best is None or q > best[0]:
                    best = (q, nodes, sm, gshare)
            if best:
                q, nodes, sm, gshare = best
                state["routes"].append(dict(kind="green_loop", park=f"{place}|{key}", name=f"{place} Green Loop",
                                            coords=gp.stitch(H, nodes), length_m=round(sm["length"]),
                                            surface=sm["surface"], in_park=round(gshare, 2),
                                            retrace=round(sm["retrace"], 2), quality=round(q, 3), loop=True))
    state["done"] = sorted(done)
    json.dump(state, open(OUT, "w"))
    left = sum(1 for gx, gy in grid if f"{gx:.0f},{gy:.0f}" not in done)
    print(f"{len(state['routes'])} candidate routes so far; {left} of {len(grid)} start points left.")
    print("All done." if finished and left == 0 else "Run it again to continue.")


if __name__ == "__main__":
    main()
