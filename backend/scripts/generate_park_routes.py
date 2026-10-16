"""
Step 2 of the park & path route generator: build running loops inside named
parks and out-and-back runs along named river / greenway paths, from the
network saved by extract_route_network.py. No database needed.

Loops are built the way running-route planners usually do it: go out to a
turnaround point by the nicest (park-preferring) way, then come back by a
different way (the outbound path is penalised), and keep loops that stay
mostly in the park and don't retrace much of themselves.

Run from backend/ (it works in chunks; run it until it says "All done"):
    python3 scripts/generate_park_routes.py
Writes scripts/.shade_cache/park_routes.json, loaded by load_park_routes.py
"""
import json
import math
import os
import pickle
import sys
import time

import networkx as nx
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".shade_cache")
NET = os.path.join(CACHE, "network.pkl")
OUT = os.path.join(CACHE, "park_routes.json")
TIME_BUDGET_S = float(os.getenv("TIME_BUDGET_S", "140"))

LAT0 = 34.15
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110540
MI = 1609.34
LOOP_TARGETS_M = [1.5 * MI, 2 * MI, 2.5 * MI, 3 * MI, 3.5 * MI, 4 * MI, 5 * MI, 6.5 * MI, 8 * MI, 10 * MI]
PATH_TARGETS_M = [1.0 * MI, 1.5 * MI, 2 * MI, 3 * MI, 4 * MI]     # one way (run as out-and-back)
MIN_PARK_M2 = 40_000             # 4 hectares
MIN_IN_PARK = 0.40               # share of a loop that must be in/along the park
MAX_RETRACE = 0.30               # share of a loop that may run the same path twice
LEN_TOL = 0.18
COST = {"footway": 1.0, "path": 1.0, "track": 1.0, "cycleway": 1.0, "pedestrian": 1.0, "bridleway": 1.0,
        "living_street": 1.6, "residential": 1.8, "service": 1.8, "unclassified": 1.9,
        "tertiary": 2.3, "secondary": 3.0}
GREENWAY_WORDS = ("river", "arroyo", "bike path", "bikeway", "greenway", "channel", "wash", "creek")


def m(lon, lat):
    return lon * KX, lat * KY


def load():
    with open(NET, "rb") as f:
        d = pickle.load(f)
    G = nx.Graph()
    for u, v, length, hw, surface, name, coords in d["edges"]:
        if u == v:
            continue
        old = G.get_edge_data(u, v)
        if old is None or old["length"] > length:
            G.add_edge(u, v, length=length, hw=hw, surface=surface, name=name, coords=coords)
    return G, d


def place_name(places, lon, lat):
    best, bd = None, 1e18
    x, y = m(lon, lat)
    for name, plon, plat in places:
        px, py = m(plon, plat)
        dd = (px - x) ** 2 + (py - y) ** 2
        if dd < bd:
            best, bd = name, dd
    return best if bd < 2500 ** 2 else None


def path_edges(nodes):
    return [(nodes[i], nodes[i + 1]) for i in range(len(nodes) - 1)]


def stitch(G, nodes):
    """Node list -> coordinate list following each edge's real geometry."""
    out = []
    for u, v in path_edges(nodes):
        c = G[u][v]["coords"]
        if m(*c[0]) != m(*G.nodes[u]["xy_ll"]):
            pass
        cu = G.nodes[u]["xy_ll"]
        seg = c if (abs(c[0][0] - cu[0]) + abs(c[0][1] - cu[1])) < (abs(c[-1][0] - cu[0]) + abs(c[-1][1] - cu[1])) else c[::-1]
        out.extend(seg if not out else seg[1:])
    return out


def summarize(G, nodes, inside=None):
    total = 0.0
    surf = {"pavement": 0.0, "trail": 0.0}
    in_park = 0.0
    seen, retrace = set(), 0.0
    for u, v in path_edges(nodes):
        e = G[u][v]
        L = e["length"]
        total += L
        surf[e["surface"] if e["surface"] in surf else "pavement"] += L
        key = (min(u, v), max(u, v))
        if key in seen:
            retrace += L
        seen.add(key)
        if inside is not None and e.get("inpark"):
            in_park += L
    if total == 0:
        return None
    t = surf["trail"] / total
    surface = "trail" if t >= 0.7 else "pavement" if t <= 0.3 else "mixed"
    return dict(length=total, surface=surface, in_park=in_park / total, retrace=retrace / total)


def loops_for_park(G, name, rings, done_names):
    polys = []
    for r in rings:
        p = Polygon([m(*c) for c in r])
        if not p.is_valid:
            p = p.buffer(0)
        polys.append(p)
    park = unary_union(polys)
    if park.area < MIN_PARK_M2:
        return []
    zone = prep(park.buffer(25))
    minx, miny, maxx, maxy = park.bounds
    pad = 4000
    sub_nodes = [n for n, d in G.nodes(data=True)
                 if minx - pad <= d["xy"][0] <= maxx + pad and miny - pad <= d["xy"][1] <= maxy + pad]
    H = G.subgraph(sub_nodes).copy()
    in_len = 0.0
    for u, v, e in H.edges(data=True):
        c = e["coords"][len(e["coords"]) // 2]
        e["inpark"] = zone.contains(Point(*m(*c)))
        if e["inpark"]:
            in_len += e["length"]
        e["w"] = e["length"] * COST.get(e["hw"], 2.5) * (0.45 if e["inpark"] else 1.0)
    if in_len < 600:
        return []
    park_nodes = [n for n in H.nodes if zone.contains(Point(*H.nodes[n]["xy"]))]
    if not park_nodes:
        return []
    # up to 5 well-spread start points inside the park
    starts = [park_nodes[0]]
    while len(starts) < 5:
        far = max(park_nodes, key=lambda n: min(math.dist(H.nodes[n]["xy"], H.nodes[s]["xy"]) for s in starts))
        if min(math.dist(H.nodes[far]["xy"], H.nodes[s]["xy"]) for s in starts) < 400:
            break
        starts.append(far)
    found = []
    for s in starts:
        dist_w, paths = nx.single_source_dijkstra(H, s, weight="w", cutoff=3 * max(LOOP_TARGETS_M))
        real = {n: sum(H[a][b]["length"] for a, b in path_edges(p)) for n, p in paths.items()}
        for L in LOOP_TARGETS_M:
            if L > 2.6 * max(in_len, 1) + 2000:      # far too long for this park
                continue
            cands = [n for n, d in real.items() if 0.35 * L <= d <= 0.55 * L]
            cands.sort(key=lambda n: (not H.nodes[n].get("_in", zone.contains(Point(*H.nodes[n]["xy"]))),
                                      -math.dist(H.nodes[n]["xy"], H.nodes[s]["xy"])))
            best = None
            for t in cands[:8]:
                out = paths[t]
                pen = {(min(a, b), max(a, b)) for a, b in path_edges(out)}

                def w2(a, b, e, pen=pen):
                    return e["w"] * (6.0 if (min(a, b), max(a, b)) in pen else 1.0)
                try:
                    back = nx.dijkstra_path(H, t, s, weight=w2)
                except nx.NetworkXNoPath:
                    continue
                nodes = out + back[1:]
                sm = summarize(H, nodes, inside=True)
                if not sm or abs(sm["length"] - L) > LEN_TOL * L:
                    continue
                if sm["in_park"] < MIN_IN_PARK or sm["retrace"] > MAX_RETRACE:
                    continue
                q = sm["in_park"] + 0.5 * (1 - sm["retrace"]) + (0.2 if sm["surface"] != "pavement" else 0)
                if best is None or q > best[0]:
                    best = (q, nodes, sm)
            if best:
                q, nodes, sm = best
                coords = stitch(H, nodes)
                line = LineString([m(*c) for c in coords])
                if any(line.buffer(30).contains(LineString([m(*c) for c in f["coords"]]).interpolate(0.5, normalized=True))
                       and abs(f["length_m"] - sm["length"]) < 0.2 * sm["length"] for f in found):
                    continue
                found.append(dict(kind="park_loop", park=name, name=f"{name} Loop", coords=coords,
                                  length_m=round(sm["length"]), surface=sm["surface"],
                                  in_park=round(sm["in_park"], 2), retrace=round(sm["retrace"], 2),
                                  quality=round(q, 3), loop=True))
    return found


def greenway_runs(G, places):
    """Out-and-back runs along long named river/greenway paths (within the app's area)."""
    by_name = {}
    for u, v, e in G.edges(data=True):
        n = (e.get("name") or "")
        low = n.lower()
        if e["hw"] in ("cycleway", "footway", "path", "pedestrian") and any(w in low for w in GREENWAY_WORDS) \
                and not any(bad in low for bad in ("road", "unmaintained", "street", "avenue", "drive")):
            by_name.setdefault(n, []).append((u, v))
    cx, cy = m(-118.22, 34.15)
    runs = []
    for name, edges in by_name.items():
        H = G.edge_subgraph(edges).copy()
        if sum(e["length"] for _, _, e in H.edges(data=True)) < 2000:
            continue
        per_name = []
        for comp in nx.connected_components(H):
            C = H.subgraph(comp)
            if sum(e["length"] for _, _, e in C.edges(data=True)) < 1500:
                continue
            ends = [n for n in C.nodes if C.degree(n) == 1] or list(C.nodes)[:1]
            dist, paths = nx.single_source_dijkstra(C, ends[0], weight="length")
            spine = paths[max(dist, key=dist.get)]
            for L in PATH_TARGETS_M:
                i = 0
                while i < len(spine) - 1:
                    # walk forward from spine[i] until the segment reaches L
                    j, acc = i, 0.0
                    while j < len(spine) - 1 and acc < L:
                        acc += C[spine[j]][spine[j + 1]]["length"]
                        j += 1
                    if acc < 0.85 * L:
                        break
                    nodes = spine[i:j + 1]
                    coords = stitch(C, nodes)
                    sx, sy = m(*coords[0])
                    if math.hypot(sx - cx, sy - cy) <= 15000:
                        sm = summarize(C, nodes)
                        pa = place_name(places, *coords[0])
                        pb = place_name(places, *coords[-1])
                        where = f"{pa} to {pb}" if pa and pb and pa != pb else (f"near {pa or pb}" if (pa or pb) else "")
                        per_name.append(dict(kind="greenway", park=name,
                                             name=f"{name}: {where}" if where else name,
                                             coords=coords, length_m=round(sm["length"]), surface=sm["surface"],
                                             in_park=1.0, retrace=0.0, quality=1.2, loop=False))
                    # next start ~L further along (no heavy overlap between segments)
                    k, acc2 = i, 0.0
                    while k < len(spine) - 1 and acc2 < L:
                        acc2 += C[spine[k]][spine[k + 1]]["length"]
                        k += 1
                    i = k
        per_name.sort(key=lambda r: -r["length_m"])
        runs += per_name[:8]              # at most 8 runs per named path
    return runs


def main():
    t0 = time.time()
    state = {"parks_done": [], "greenways_done": False, "routes": []}
    if os.path.exists(OUT):
        with open(OUT) as f:
            state = json.load(f)
    G, d = load()
    for n in G.nodes:
        lon, lat = d["nodes"][n]
        G.nodes[n]["xy_ll"] = (lon, lat)
        G.nodes[n]["xy"] = m(lon, lat)
    print(f"Network: {G.number_of_nodes()} junctions, {G.number_of_edges()} segments "
          f"({time.time() - t0:.0f}s)")
    if not state["greenways_done"]:
        g = greenway_runs(G, d["places"])
        state["routes"] += g
        state["greenways_done"] = True
        print(f"  {len(g)} greenway runs")
    parks = sorted(d["parks"], key=lambda p: p[0])
    done = set(state["parks_done"])
    for name, rings in parks:
        key = name + "|" + f"{rings[0][0][0]:.4f},{rings[0][0][1]:.4f}"
        if key in done:
            continue
        if time.time() - t0 > TIME_BUDGET_S:
            break
        try:
            found = loops_for_park(G, name, rings, done)
        except Exception as ex:
            print(f"  skipped {name}: {type(ex).__name__}: {ex}")
            found = []
        state["routes"] += found
        state["parks_done"].append(key)
        done.add(key)
        if found:
            print(f"  {name}: {len(found)} loops")
    with open(OUT, "w") as f:
        json.dump(state, f)
    left = sum(1 for name, rings in parks
               if name + "|" + f"{rings[0][0][0]:.4f},{rings[0][0][1]:.4f}" not in done)
    print(f"\n{len(state['routes'])} candidate routes so far; {left} parks left.")
    print("All done." if left == 0 else "Run it again to continue.")


if __name__ == "__main__":
    main()
