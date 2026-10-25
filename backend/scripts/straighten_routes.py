"""
Take out odd jogs: places where a route wanders through a few blocks, a campus or a
parking lot and comes out not far from where it went in, when a direct street or path
joins the two points. The wander is replaced with that direct way, so the route has
fewer turns and is easier to follow.

How: walking along each route, at every junction it passes we look at the next ~1.2 km.
If the route takes L metres to get from junction A to junction B, but the network has a
way from A to B under 55% of L (and it saves at least 150 m), that bit is a jog and gets
swapped for the direct way. Kept as they are:
  - trails (they wind on purpose),
  - the turnaround of an out-and-back,
  - anything that would cut more than 25% off a route, make it messier,
    or move its start more than 400 m.
Undo (puts the original lines back, then re-run the re-measure scripts):
    DATABASE_URL=... python3 scripts/straighten_routes.py --undo

Needs scripts/.shade_cache/network.pkl (from extract_route_network.py). Run from backend/:
    DATABASE_URL=... python3 scripts/straighten_routes.py --preview   # drawings, nothing saved
    DATABASE_URL=... python3 scripts/straighten_routes.py             # save
    python3 scripts/straighten_routes.py --cache --preview             # test on the audit cache
Then re-measure (same as after the spur cleanup):
    python3 scripts/update_elevation_dem.py
    python3 scripts/update_shade_canopy.py
    python3 scripts/update_scenic.py
    python3 scripts/update_traffic.py
"""
import math
import os
import pickle
import sys

import networkx as nx
from shapely.geometry import Point
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from clean_route_spurs import densify, dist_m, length_m, remove_detours  # noqa: E402
from route_shape import mess_score, shape_metrics  # noqa: E402

NETWORK = os.path.join(HERE, ".shade_cache", "network.pkl")
CACHE = os.path.join(HERE, "audit_output", "routes_cache.pkl")
SNAP_M = 15             # route point this close to a junction = passes through it
MIN_JOG_M = 200         # shorter than this isn't worth touching
MAX_JOG_M = 1200
JOG_RATIO = 0.55        # direct way under 55% of the route's way = a jog
MIN_SAVING_M = 150
MAX_CUT_SHARE = 0.25
MAX_START_MOVE_M = 400  # the start (trailhead / parking) can't move farther than this
BACKUP = os.path.join(HERE, "straighten_backup.json")   # original lines, for --undo
# prefer quiet ways for the replacement (same idea as the generators)
COST = {"secondary": 1.6, "tertiary": 1.25, "service": 1.15}
LAT0 = 34.15
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110540


def load_network():
    d = pickle.load(open(NETWORK, "rb"))
    G = nx.Graph()
    for u, v, length, hw, surface, name, coords in d["edges"]:
        w = length * COST.get(hw, 1.0)
        if G.has_edge(u, v) and G[u][v]["weight"] <= w:
            continue
        G.add_edge(u, v, weight=w, length=length, coords=coords, u=u)
    ids = list(d["nodes"])
    pts = [Point(d["nodes"][n][0] * KX, d["nodes"][n][1] * KY) for n in ids]
    return G, d["nodes"], ids, STRtree(pts), pts


def snap(p, net):
    G, nodes, ids, tree, npts = net
    q = Point(p[0] * KX, p[1] * KY)
    best = None
    for i in tree.query(q.buffer(SNAP_M)):
        d = npts[int(i)].distance(q)
        if d <= SNAP_M and (best is None or d < best[0]):
            best = (d, ids[int(i)])
    return best[1] if best and best[1] in G else None


def path_coords(G, path):
    out = []
    for a, b in zip(path, path[1:]):
        e = G[a][b]
        c = list(e["coords"]) if e["u"] == a else list(reversed(e["coords"]))
        out.extend(c if not out else c[1:])
    return out


def straighten(coords, surface, net):
    """Returns (new coords, metres cut, number of jogs) or None if nothing to do."""
    if surface == "trail":
        return None
    G = net[0]
    pts = densify(coords, 10.0)
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + dist_m(a, b))
    total = cum[-1]
    if total < 1000:
        return None
    # a loop that starts in the middle of a jog (e.g. starts on campus, wanders out and back in):
    # look at it starting from the far side, then put the start back near where it was
    loop = dist_m(pts[0], pts[-1]) < 50
    start0 = pts[0]
    if loop:
        h = next(i for i, c in enumerate(cum) if c >= total / 2)
        pts = pts[h:-1] + pts[:h + 1]
        cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            cum.append(cum[-1] + dist_m(a, b))
    far = max(range(len(pts)), key=lambda i: dist_m(pts[0], pts[i]))
    sm = shape_metrics(coords)
    out_and_back = loop and sm and sm["stretches"] >= 3
    if out_and_back:
        return None           # out-and-backs and lollipops: leave alone
    # junctions the route passes, in order (one index per junction visit)
    stops, last = [], None
    for i, p in enumerate(pts):
        n = snap(p, net)
        if n is not None and n != last:
            stops.append((i, n))
        last = n if n is not None else last
    jogs = []
    k = 0
    while k < len(stops):
        i, a = stops[k]
        dists, paths = nx.single_source_dijkstra(G, a, cutoff=MAX_JOG_M * 1.6, weight="weight")
        best = None
        for m in range(k + 1, len(stops)):
            j, b = stops[m]
            L = cum[j] - cum[i]
            if L > MAX_JOG_M:
                break
            if L < MIN_JOG_M or b not in dists or (out_and_back and i <= far <= j):
                continue
            if i == 0 and j == len(pts) - 1:
                continue
            if dists[b] * 0.6 > JOG_RATIO * L:     # length >= weight / 1.6, so this can't pass
                continue
            path = paths[b]
            d = sum(G[x][y]["length"] for x, y in zip(path, path[1:]))
            if d <= JOG_RATIO * L and L - d >= MIN_SAVING_M and (best is None or L - d > best[0]):
                best = (L - d, i, j, path, m)
        if best:
            jogs.append(best[:4])
            k = best[4]
        else:
            k += 1
    if not jogs:
        return None
    jogs.sort(key=lambda t: -t[0])
    chosen, cut = [], 0.0
    for saving, i, j, path in jogs:
        if cut + saving <= MAX_CUT_SHARE * total:
            chosen.append((i, j, path)); cut += saving
    if not chosen:
        return None
    chosen.sort()
    new, prev = [], 0
    for i, j, path in chosen:
        new.extend(pts[prev:i + 1])
        new.extend(path_coords(G, path)[1:-1])
        prev = j
    new.extend(pts[prev:])
    if loop:                  # start again at the point nearest the old start
        s = min(range(len(new) - 1), key=lambda i: dist_m(new[i], start0))
        new = new[s:-1] + new[:s + 1]
    if dist_m(new[0], start0 if loop else coords[0]) > MAX_START_MOVE_M:
        return None
    new, _ = remove_detours(new)          # in case the shortcut left a dash-and-back
    if mess_score(new, surface) > mess_score(coords, surface):
        return None
    t0, t1 = shape_metrics(coords), shape_metrics(new)
    if t0 and t1 and t1["turns_km"] * length_m(new) > t0["turns_km"] * total:
        return None                       # more turns overall: not simpler
    return new, total - length_m(new), len(chosen)


NET = None


def _one(args):
    try:
        return straighten(args[0], args[1], NET)
    except Exception:
        return None


def write_previews(changes, before):
    out = os.path.join(HERE, "audit_output", "straighten_preview")
    os.makedirs(out, exist_ok=True)
    cards = []
    for n, (rid, name, km, new_km, cut, jogs, clean) in enumerate(changes):
        old = before[rid]
        xs = [p[0] for p in old]; ys = [p[1] for p in old]
        kx = math.cos(math.radians(sum(ys) / len(ys)))
        scale = 380 / max((max(xs) - min(xs)) * kx or 1e-6, (max(ys) - min(ys)) or 1e-6)

        def poly(ps):
            return " ".join(f"{20 + (x - min(xs)) * kx * scale:.1f},{20 + (max(ys) - y) * scale:.1f}" for x, y in ps)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="420" viewBox="0 0 420 420">'
               f'<rect width="420" height="420" fill="#fff"/>'
               f'<polyline points="{poly(old)}" fill="none" stroke="#f87171" stroke-width="7" stroke-linejoin="round"/>'
               f'<polyline points="{poly(clean)}" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linejoin="round"/>'
               f'<text x="10" y="410" font-family="sans-serif" font-size="12">{name[:38]}: {km * 0.621:.2f} -> {new_km * 0.621:.2f} mi</text></svg>')
        fn = f"route_{n:02d}.svg"
        open(os.path.join(out, fn), "w").write(svg)
        cards.append(f'<figure><img src="{fn}"><figcaption>{name}</figcaption></figure>')
    open(os.path.join(out, "index.html"), "w").write(
        "<html><body style='font-family:sans-serif'><p>Red = before, blue = after (jogs replaced with "
        "the direct way).</p><div style='display:flex;flex-wrap:wrap;gap:8px'>" + "".join(cards) + "</div></body></html>")
    print(f"\nPreview drawings: {out}/index.html")


def undo():
    import json
    from sqlalchemy import create_engine, text
    saved = json.load(open(BACKUP))
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as conn:
        for rid, (wkt, km) in saved.items():
            conn.execute(text("UPDATE route SET gps_path = ST_GeomFromText(:w, 4326), distance_km = :d, "
                              "shade_pct = NULL WHERE id = :id"), {"w": wkt, "d": km, "id": rid})
    print(f"Put back the original lines for {len(saved)} routes. Re-run the re-measure scripts.")


def main():
    if "--undo" in sys.argv:
        return undo()
    net = load_network()
    use_cache = "--cache" in sys.argv
    if use_cache:
        cache_rows = pickle.load(open(CACHE, "rb"))
        rows = [(r["id"], r["nickname"] or r["name"], r["distance_km"], r["surface_type"], r["coords"])
                for r in cache_rows if not r.get("hidden")]
    else:
        if "DATABASE_URL" not in os.environ:
            sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
        from sqlalchemy import create_engine, text
        engine = create_engine(os.environ["DATABASE_URL"])
        with engine.connect() as conn:
            raw = conn.execute(text("SELECT id, COALESCE(nickname, name), distance_km, surface_type, "
                                    "ST_AsText(gps_path) FROM route WHERE NOT COALESCE(hidden, FALSE)")).all()
        rows = []
        for rid, name, km, surf, wkt in raw:
            if wkt and wkt.startswith("LINESTRING"):
                rows.append((rid, name, km, surf,
                             [tuple(map(float, p.split())) for p in wkt[wkt.index("(") + 1:-1].split(",")]))
    changes, before = [], {}
    global NET
    NET = net
    from multiprocessing import get_context
    print(f"Checking {len(rows)} routes...", flush=True)
    with get_context("fork").Pool(max(1, (os.cpu_count() or 2))) as pool:
        results = pool.map(_one, [(c, s) for _, _, _, s, c in rows], chunksize=8)
    for (rid, name, km, surf, coords), res in zip(rows, results):
        if res:
            new, cut, jogs = res
            before[rid] = coords
            changes.append((rid, name, km, length_m(new) / 1000, cut, jogs, new))
    changes.sort(key=lambda c: -c[4])
    print(f"\n{len(rows)} routes checked; {len(changes)} have jogs to take out "
          f"({sum(c[5] for c in changes)} jogs, {sum(c[4] for c in changes) / 1609.34:.0f} mi of wandering).")
    for rid, name, km, new_km, cut, jogs, _ in changes[:25]:
        print(f"  {name[:42]:<42} {km * 0.621:5.2f} -> {new_km * 0.621:5.2f} mi  ({jogs} jog{'s' if jogs > 1 else ''})")
    if "--preview" in sys.argv or "--dry-run" in sys.argv:
        if "--preview" in sys.argv:
            write_previews(changes, before)
        pickle.dump(changes, open(os.path.join(HERE, "audit_output", "straighten_changes.pkl"), "wb"))
        print("\nPreview only: nothing saved.")
        return
    if use_cache:
        by = {c[0]: c for c in changes}
        for r in cache_rows:
            if r["id"] in by:
                r["coords"] = by[r["id"]][6]; r["distance_km"] = round(by[r["id"]][3], 3)
        pickle.dump(cache_rows, open(CACHE, "wb"))
        print("Saved to the audit cache only.")
        return
    import json
    old = json.load(open(BACKUP)) if os.path.exists(BACKUP) else {}
    for rid, name, km, *_ in changes:          # keep the very first original if run twice
        old.setdefault(str(rid), ["LINESTRING(" + ", ".join(f"{x:.7f} {y:.7f}" for x, y in before[rid]) + ")", km])
    json.dump(old, open(BACKUP, "w"))
    with engine.begin() as conn:
        for rid, name, km, new_km, cut, jogs, clean in changes:
            wkt = "LINESTRING(" + ", ".join(f"{x:.7f} {y:.7f}" for x, y in clean) + ")"
            conn.execute(text("UPDATE route SET gps_path = ST_GeomFromText(:w, 4326), distance_km = :d, "
                              "shade_pct = NULL WHERE id = :id"), {"w": wkt, "d": round(new_km, 3), "id": rid})
    print(f"\nStraightened {len(changes)} routes. Now re-run update_elevation_dem.py, update_shade_canopy.py, "
          f"update_scenic.py and update_traffic.py.")


if __name__ == "__main__":
    main()
