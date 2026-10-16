"""
Round 2 of the route generator (after generate_park_routes.py):

  1. Park-to-park loops: from one park to a nearby park and back by a
     different way, preferring paths, parks and green streets
     ("Ernest E. Debs Regional Park to Ascot Hills Park Loop").
  2. Named trail runs: out-and-backs along named trails, motorways and fire
     roads ("Brand Motorway: 3.0 mi out").

Run from backend/ (works in chunks; run until it says "All done"):
    python3 scripts/generate_more_routes.py
Writes scripts/.shade_cache/more_routes.json. Load with:
    python3 scripts/load_park_routes.py --src more_routes.json --dry-run
"""
import json
import math
import os
import pickle
import sys
import time

import networkx as nx
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_park_routes as gp  # noqa: E402

CACHE = gp.CACHE
OUT = os.path.join(CACHE, "more_routes.json")
GREEN_CACHE = os.path.join(CACHE, "green_edges.pkl")
TIME_BUDGET_S = float(os.getenv("TIME_BUDGET_S", "140"))
MI = gp.MI
PAIR_MIN_M, PAIR_MAX_M = 1200, 4500          # straight-line distance between the two parks
MIN_GREEN = 0.40                              # share of the loop on paths / in green areas
TRAIL_WORDS = ("trail", "motorway", "fire road", "truck trail", "canyon", "ridge", "mtwy")
TRAIL_TARGETS_M = [1.5 * MI, 2 * MI, 3 * MI, 4 * MI]


def green_edges(G):
    """Edge keys whose midpoint is in or beside a park / nature area / water (cached)."""
    if os.path.exists(GREEN_CACHE):
        return pickle.load(open(GREEN_CACHE, "rb"))
    d = json.load(open(os.path.join(CACHE, "scenic_local.json")))
    polys = []
    for ring in d["areas"]:
        try:
            p = Polygon([gp.m(*c) for c in ring])
            p = p if p.is_valid else p.buffer(0)
            if not p.is_empty:
                polys.append(p)
        except Exception:
            pass
    tree = STRtree(polys)
    green = set()
    for u, v, e in G.edges(data=True):
        c = e["coords"][len(e["coords"]) // 2]
        pt = Point(*gp.m(*c))
        if any(polys[int(i)].distance(pt) <= 25 for i in tree.query(pt.buffer(25))):
            green.add((min(u, v), max(u, v)))
    pickle.dump(green, open(GREEN_CACHE, "wb"))
    return green


def park_centers(parks):
    out = []
    for name, rings in parks:
        polys = [Polygon([gp.m(*c) for c in r]) for r in rings]
        polys = [p if p.is_valid else p.buffer(0) for p in polys]
        u = unary_union(polys)
        if u.area >= 20_000:                       # 2 ha+
            out.append((name, u))
    return out


def nearest_node(G, xy, cand):
    return min(cand, key=lambda n: math.dist(G.nodes[n]["xy"], xy))


def park_pair_loops(G, parks, green, done, t0):
    found = []
    centers = park_centers(parks)
    nodes_xy = [(n, G.nodes[n]["xy"]) for n in G.nodes]
    for i, (na, pa) in enumerate(centers):
        key = f"pair|{na}|{i}"
        if key in done:
            continue
        if time.time() - t0 > TIME_BUDGET_S:
            return found, False
        done.add(key)
        ca = pa.centroid
        partners = [(nb, pb) for nb, pb in centers if nb != na
                    and PAIR_MIN_M <= ca.distance(pb.centroid) <= PAIR_MAX_M]
        partners.sort(key=lambda t: ca.distance(t[1].centroid))
        if not partners:
            continue
        minx, miny, maxx, maxy = ca.buffer(PAIR_MAX_M + 1500).bounds
        sub = [n for n, (x, y) in nodes_xy if minx <= x <= maxx and miny <= y <= maxy]
        H = G.subgraph(sub)                    # a view: weights were set once on G
        za = pa.buffer(25)
        in_a = [n for n in sub if za.contains(Point(*G.nodes[n]["xy"]))]
        if not in_a:
            continue
        s = nearest_node(H, (ca.x, ca.y), in_a)
        made = 0
        for nb, pb in partners[:4]:
            zb = pb.buffer(25)
            in_b = [n for n in sub if zb.contains(Point(*G.nodes[n]["xy"]))]
            if not in_b:
                continue
            t = nearest_node(H, (pb.centroid.x, pb.centroid.y), in_b)
            try:
                out = nx.dijkstra_path(H, s, t, weight="w")
                pen = {(min(a, b), max(a, b)) for a, b in gp.path_edges(out)}
                back = nx.dijkstra_path(H, t, s, weight=lambda a, b, e: e["w"] * (6 if (min(a, b), max(a, b)) in pen else 1))
            except nx.NetworkXNoPath:
                continue
            nodes = out + back[1:]
            sm = gp.summarize(H, nodes)
            if not sm or not (2.5 * MI * 0.8 <= sm["length"] <= 8 * MI) or sm["retrace"] > gp.MAX_RETRACE:
                continue
            gshare = sum(H[a][b]["length"] for a, b in gp.path_edges(nodes) if H[a][b]["green"]) / sm["length"]
            if gshare < MIN_GREEN:
                continue
            found.append(dict(kind="park_pair", park=na, name=f"{na} to {nb} Loop",
                              coords=gp.stitch(H, nodes), length_m=round(sm["length"]), surface=sm["surface"],
                              in_park=round(gshare, 2), retrace=round(sm["retrace"], 2),
                              quality=round(0.8 * gshare + 0.4 * (1 - sm["retrace"]), 3), loop=True))
            made += 1
            if made >= 2:
                break
    return found, True


def trail_runs(G, places):
    by_name = {}
    for u, v, e in G.edges(data=True):
        n = e.get("name") or ""
        if e["hw"] in ("path", "track", "bridleway", "footway") and any(w in n.lower() for w in TRAIL_WORDS):
            by_name.setdefault(n, []).append((u, v))
    cx, cy = gp.m(-118.22, 34.15)
    runs = []
    for name, edges in by_name.items():
        H = G.edge_subgraph(edges).copy()
        if sum(e["length"] for _, _, e in H.edges(data=True)) < 2000:
            continue
        per = []
        for comp in nx.connected_components(H):
            C = H.subgraph(comp)
            if sum(e["length"] for _, _, e in C.edges(data=True)) < 2000:
                continue
            ends = [n for n in C.nodes if C.degree(n) == 1] or list(C.nodes)[:1]
            dist, paths = nx.single_source_dijkstra(C, ends[0], weight="length")
            spine = paths[max(dist, key=dist.get)]
            for L in TRAIL_TARGETS_M:
                j, acc = 0, 0.0
                while j < len(spine) - 1 and acc < L:
                    acc += C[spine[j]][spine[j + 1]]["length"]
                    j += 1
                if acc < 0.85 * L:
                    continue
                nodes = spine[:j + 1]
                coords = gp.stitch(C, nodes)
                if math.dist(gp.m(*coords[0]), (cx, cy)) > 15000:
                    continue
                sm = gp.summarize(C, nodes)
                per.append(dict(kind="trail_run", park=name, name=f"{name}: {sm['length'] / MI:.1f} mi out",
                                coords=coords, length_m=round(sm["length"]), surface=sm["surface"],
                                in_park=1.0, retrace=0.0, quality=1.0, loop=False))
        runs += per[:4]
    return runs


def main():
    t0 = time.time()
    state = json.load(open(OUT)) if os.path.exists(OUT) else {"done": [], "trails_done": False, "routes": []}
    G, d = gp.load()
    for n in G.nodes:
        lon, lat = d["nodes"][n]
        G.nodes[n]["xy_ll"] = (lon, lat)
        G.nodes[n]["xy"] = gp.m(lon, lat)
    green = green_edges(G)
    for u, v, e in G.edges(data=True):
        g = (min(u, v), max(u, v)) in green
        e["green"] = g or e["hw"] in ("footway", "path", "track", "cycleway", "pedestrian", "bridleway")
        e["w"] = e["length"] * gp.COST.get(e["hw"], 2.5) * (0.5 if g else 1.0)
    print(f"Network ready ({time.time() - t0:.0f}s, {len(green)} green segments)")
    if not state["trails_done"]:
        tr = trail_runs(G, d["places"])
        state["routes"] += tr
        state["trails_done"] = True
        print(f"  {len(tr)} named trail runs")
    done = set(state["done"])
    found, finished = park_pair_loops(G, d["parks"], green, done, t0)
    state["routes"] += found
    state["done"] = sorted(done)
    json.dump(state, open(OUT, "w"))
    print(f"  +{len(found)} park-to-park loops this run")
    print(f"\n{len(state['routes'])} candidate routes so far.")
    print("All done." if finished else "Run it again to continue.")


if __name__ == "__main__":
    main()
