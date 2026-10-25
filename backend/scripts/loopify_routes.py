"""
Clean loops and clean out-and-backs only: cut the "stems" off loops.

A stem is a stretch the route runs out along and then straight back the same way:
a tail sticking out of a loop (like a lollipop stick), or a dash up a street and back
in the middle of a loop. Pavement, mixed and track routes that are a loop plus stems
become just the loop, and the start moves to the nearest point on the loop.
(--reroute instead tries to come back a different way on nearby streets; in testing only
~1 in 40 stems had one, and those mostly came out messier, so it's off by default.)

Left alone:
  - real out-and-backs (the whole route goes out and comes back the same way),
  - routes where the loop would be under 1.2 km (an out-and-back with a little
    turnaround loop at the end: better left as it is),
  - trails (a stem there is often the only way in from the trailhead).

Run from backend/:
    DATABASE_URL=... python3 scripts/loopify_routes.py --preview   # drawings, nothing saved
    DATABASE_URL=... python3 scripts/loopify_routes.py             # save
    python3 scripts/loopify_routes.py --cache --preview             # test on the audit cache
    DATABASE_URL=... python3 scripts/loopify_routes.py --undo       # put the originals back
Then re-measure:
    python3 scripts/update_elevation_dem.py
    python3 scripts/update_shade_canopy.py
    python3 scripts/update_scenic.py
    python3 scripts/update_traffic.py
"""
import json
import math
import os
import pickle
import sys

import networkx as nx
from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from clean_route_spurs import dist_m, length_m  # noqa: E402
from route_shape import mess_score  # noqa: E402

CACHE = os.path.join(HERE, "audit_output", "routes_cache.pkl")
BACKUP = os.path.join(HERE, "loopify_backup.json")
STEP_M = 5.0
SAME_M = 12           # out and back this close = the same street
MIN_STEM_M = 40       # shorter than this: just the corner of a junction
MIN_LOOP_SHARE = 0.40
MIN_LOOP_M = 1200
CLOSED_M = 60         # start and end this close = a loop-shaped route
REROUTE_MIN_M = 200   # stems at least this long: try to come back a different way
REROUTE_MAX = 2.5     # the new way back can be up to this x the stem
REROUTE_MIN = 0.6
OVERLAP_M = 20        # new way back this close to the rest of the route = reusing it
NETWORK = os.path.join(HERE, ".shade_cache", "network.pkl")
LAT0 = 34.15
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110540
NET = None


def network():
    """Street/path graph (from extract_route_network.py), loaded once."""
    global NET
    if NET is None:
        d = pickle.load(open(NETWORK, "rb"))
        G = nx.Graph()
        for u, v, length, hw, surface, name, coords in d["edges"]:
            if not G.has_edge(u, v) or G[u][v]["length"] > length:
                G.add_edge(u, v, length=length, coords=coords, u=u,
                           line=LineString([(x * KX, y * KY) for x, y in coords]))
        ids = [n for n in d["nodes"] if n in G]
        npts = [Point(d["nodes"][n][0] * KX, d["nodes"][n][1] * KY) for n in ids]
        edges = list(G.edges())
        NET = (G, ids, npts, STRtree(npts), edges, STRtree([G[a][b]["line"] for a, b in edges]))
    return NET


def nearest_node(p, within):
    G, ids, npts, ntree, *_ = network()
    q = Point(p[0] * KX, p[1] * KY)
    best = min(((npts[int(i)].distance(q), ids[int(i)]) for i in ntree.query(q.buffer(within))), default=None)
    return best[1] if best and best[0] <= within else None


def way_back(p, j, t, keep):
    """A different way from near the stem's tip p[j] back to its base p[j+t] (indices mod n),
    or None. keep = the rest of the route (projected LineString), which it mustn't reuse."""
    G, ids, npts, ntree, edges, etree = network()
    n = len(p)
    arm = t * STEP_M
    out = [p[(j - t + d) % n] for d in range(t + 1)]          # base -> tip
    # the tip may be past the last junction (a dead end): come back from the last junction on the way out
    for back in range(0, t // 2):
        a = nearest_node(out[-1 - back], 20)
        if a is not None:
            break
    else:
        return None
    b = nearest_node(out[0], 25)
    if b is None or a == b:
        return None
    stem = LineString([(x * KX, y * KY) for x, y in out]).buffer(OVERLAP_M)
    rest = keep.buffer(OVERLAP_M)
    banned = set()
    for i in etree.query(stem):
        e = edges[int(i)]
        if G[e[0]][e[1]]["line"].within(stem):
            banned |= {e, e[::-1]}
    reused = set()
    for i in etree.query(rest):
        e = edges[int(i)]
        if G[e[0]][e[1]]["line"].intersects(rest):
            reused |= {e, e[::-1]}

    def w(u, v, d):
        if (u, v) in banned:
            return None                       # don't come back the same way
        return d["length"] * (4 if (u, v) in reused else 1)
    try:
        _, path = nx.single_source_dijkstra(G, a, target=b, cutoff=REROUTE_MAX * arm * 4, weight=w)
    except (nx.NetworkXNoPath, KeyError):
        return None
    coords = []
    for x, y in zip(path, path[1:]):
        e = G[x][y]
        c = list(e["coords"]) if e["u"] == x else list(reversed(e["coords"]))
        coords.extend(c if not coords else c[1:])
    L = length_m(coords)
    if not (REROUTE_MIN * arm <= L <= REROUTE_MAX * arm):
        return None
    line = LineString([(x * KX, y * KY) for x, y in coords])
    if line.intersection(rest).length > 0.2 * line.length:
        return None                           # mostly on streets the route already uses
    return out[:len(out) - back] + coords[1:]


def resample(coords):
    """Points every STEP_M metres along the line (in lon/lat)."""
    lat0 = sum(c[1] for c in coords) / len(coords)
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540
    line = LineString([(x * kx, y * ky) for x, y in coords])
    n = max(2, int(line.length // STEP_M))
    pts = [line.interpolate(i * line.length / n).coords[0] for i in range(n + 1)]
    return [(x / kx, y / ky) for x, y in pts]


def find_stems(p):
    """p = closed ring (last point == first dropped). Returns [(tip, arm)] in index steps:
    the route goes from p[tip-arm] out to p[tip] and straight back to p[tip+arm] (indices mod n)."""
    n = len(p)
    stems = []
    for j in range(n):
        if dist_m(p[(j - 1) % n], p[(j + 1) % n]) > 6:        # not a turnaround
            continue
        t = 1
        while t < n // 2 and dist_m(p[(j - t) % n], p[(j + t) % n]) <= SAME_M:
            t += 1
        if t * STEP_M >= MIN_STEM_M:
            stems.append((j, t))
    # one per stem: keep the longest arm among overlapping candidates
    stems.sort(key=lambda s: -s[1])
    kept, used = [], set()
    for j, t in stems:
        span = {(j + d) % n for d in range(-t, t + 1)}
        if span & used:
            continue
        kept.append((j, t))
        used |= span
    return kept


SLIVER_M = 20         # out and back on two streets / sides of a road less than ~40 m apart = a stem too
GAP_M = 45            # after cutting, the two ends of a stem have to meet up this closely


def trim_slivers(ring):
    """Second pass for stems the first one misses: out on one side of a divided road and back on
    the other, or a stem with a little loop at its tip. Treats the loop as a shape, shaves off
    anything narrower than ~40 m sticking out of (or into) it, and keeps the route's own points
    along what's left. ring = closed list of (lon, lat), first == last."""
    lat0 = sum(c[1] for c in ring) / len(ring)
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540
    xy = [(x * kx, y * ky) for x, y in ring]
    poly = Polygon(xy).buffer(0)
    if poly.is_empty:
        return ring
    core = poly.buffer(-SLIVER_M).buffer(SLIVER_M)
    if core.is_empty:
        return ring
    if core.geom_type == "MultiPolygon":
        core = max(core.geoms, key=lambda g: g.area)
    edge = core.exterior
    keep = [edge.distance(Point(q)) <= 15 for q in xy]
    if all(keep) or not any(keep):
        return ring
    # start from a point on the loop, so a stem at the start is handled like any other
    k = keep.index(True)
    ring, keep = ring[k:-1] + ring[:k + 1], keep[k:-1] + keep[:k + 1]
    out, i, n = [], 0, len(ring)
    while i < n:
        if keep[i]:
            out.append(ring[i]); i += 1
            continue
        j = i
        while j < n and not keep[j]:
            j += 1
        # a real stem: its two ends meet up; otherwise it's part of the loop, keep it
        if out and j < n and dist_m(out[-1], ring[j]) <= GAP_M:
            i = j
        else:
            out.extend(ring[i:j]); i = j
    if dist_m(out[0], out[-1]) > 1:
        out.append(out[0])
    return out


CLEAN_MESS = 1.0      # a rerouted stem has to leave a clean route, or we just cut it


REROUTE = "--reroute" in sys.argv   # off by default: tried, but few stems have a clean way back


def loopify(coords, surface, reroute=None):
    """Returns (new coords, metres cut, stems, stems turned into loops) or None."""
    if reroute is None:
        reroute = REROUTE
    if surface == "trail" or len(coords) < 3 or dist_m(coords[0], coords[-1]) > CLOSED_M:
        return None
    total = length_m(coords)
    p = resample(coords)[:-1]
    n = len(p)
    stems = find_stems(p)
    drop = set()
    for j, t in stems:
        drop |= {(j + d) % n for d in range(-t + 1, t)}     # keep p[j-t] (= p[j+t])
    keep_idx = [i for i in range(n) if i not in drop]
    keep_line = LineString([(p[i][0] * KX, p[i][1] * KY) for i in keep_idx]) if len(keep_idx) > 1 else None
    # long stems: try to make them loops instead of cutting them
    insert, looped = {}, 0
    for j, t in stems:
        if reroute and t * STEP_M >= REROUTE_MIN_M and keep_line is not None:
            alt = way_back(p, j, t, keep_line)
            if alt:
                insert[(j - t) % n] = alt[1:-1]
                looped += 1
    ring = []
    for i in keep_idx:
        ring.append(p[i])
        ring.extend(insert.get(i, []))
    if len(ring) < 10:
        return None
    ring.append(ring[0])
    ring = trim_slivers(ring)
    loop_len = length_m(ring)
    if loop_len < MIN_LOOP_M:
        return None                                       # a tiny loop: it's an out-and-back with a turnaround, leave it
    # start at the loop point nearest the old start
    s = min(range(len(ring) - 1), key=lambda i: dist_m(ring[i], coords[0]))
    ring = ring[s:-1] + ring[:s + 1]
    # thin out: keep a point every ~10 m and wherever the direction changes
    thin = [ring[0]]
    for a, b in zip(ring[1:-1], ring[2:]):
        if dist_m(thin[-1], a) >= 10:
            thin.append(a)
    thin.append(ring[-1])
    if total - length_m(thin) < MIN_STEM_M:
        return None                       # nothing worth changing
    if looped and mess_score(thin, surface) > CLEAN_MESS:
        return loopify(coords, surface, reroute=False)    # the new loops made it messy: just cut
    if mess_score(thin, surface) > min(mess_score(coords, surface), CLEAN_MESS):
        return None                       # only keep it if the result is a clean loop
    return thin, total - length_m(thin), len(stems), looped


def _one(args):
    try:
        return loopify(*args)
    except Exception:
        return None


def write_previews(changes, before):
    out = os.path.join(HERE, "audit_output", "loopify_preview")
    os.makedirs(out, exist_ok=True)
    cards = []
    for n, (rid, name, km, new_km, cut, stems, clean) in enumerate(changes):
        old = before[rid]
        xs = [q[0] for q in old]; ys = [q[1] for q in old]
        kx = math.cos(math.radians(sum(ys) / len(ys)))
        scale = 380 / max((max(xs) - min(xs)) * kx or 1e-6, (max(ys) - min(ys)) or 1e-6)

        def poly(ps):
            return " ".join(f"{20 + (x - min(xs)) * kx * scale:.1f},{20 + (max(ys) - y) * scale:.1f}" for x, y in ps)
        x0, y0 = poly([clean[0]]).split(",")
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="420" viewBox="0 0 420 420">'
               f'<rect width="420" height="420" fill="#fff"/>'
               f'<polyline points="{poly(old)}" fill="none" stroke="#f87171" stroke-width="7" stroke-linejoin="round"/>'
               f'<polyline points="{poly(clean)}" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linejoin="round"/>'
               f'<circle cx="{x0}" cy="{y0}" r="5" fill="#16a34a"/>'
               f'<text x="10" y="410" font-family="sans-serif" font-size="12">{name[:38]}: {km * 0.621:.2f} -> {new_km * 0.621:.2f} mi</text></svg>')
        fn = f"route_{n:03d}.svg"
        open(os.path.join(out, fn), "w").write(svg)
        cards.append(f'<figure><img src="{fn}"><figcaption>{name}</figcaption></figure>')
    open(os.path.join(out, "index.html"), "w").write(
        "<html><body style='font-family:sans-serif'><p>Red = before, blue = after (stems cut off), "
        "green dot = new start.</p><div style='display:flex;flex-wrap:wrap;gap:8px'>" + "".join(cards) + "</div></body></html>")
    print(f"\nPreview drawings: {out}/index.html")


def undo():
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
        rows = [(rid, name, km, surf, [tuple(map(float, q.split())) for q in wkt[wkt.index("(") + 1:-1].split(",")])
                for rid, name, km, surf, wkt in raw if wkt and wkt.startswith("LINESTRING")]
    changes, before = [], {}
    n_looped = 0
    network()
    from multiprocessing import get_context
    print(f"Checking {len(rows)} routes...", flush=True)
    with get_context("fork").Pool(os.cpu_count() or 2) as pool:
        results = pool.map(_one, [(c, s) for _, _, _, s, c in rows], chunksize=8)
    for (rid, name, km, surf, coords), res in zip(rows, results):
        if res:
            new, cut, stems, looped = res
            before[rid] = coords
            changes.append((rid, name, km, length_m(new) / 1000, cut, stems, new))
            n_looped += looped
    changes.sort(key=lambda c: -c[4])
    print(f"{len(rows)} routes checked; {len(changes)} loops have stems to cut "
          f"({sum(c[5] for c in changes)} stems: {n_looped} turned into loops, the rest cut; "
          f"{sum(c[4] for c in changes) / 1609.34:.0f} mi shorter in total).")
    for rid, name, km, new_km, cut, stems, _ in changes[:25]:
        print(f"  {name[:42]:<42} {km * 0.621:5.2f} -> {new_km * 0.621:5.2f} mi  ({stems} stem{'s' if stems > 1 else ''})")
    if "--preview" in sys.argv or "--dry-run" in sys.argv:
        if "--preview" in sys.argv:
            write_previews(changes, before)
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
    old = json.load(open(BACKUP)) if os.path.exists(BACKUP) else {}
    for rid, name, km, *_ in changes:
        old.setdefault(str(rid), ["LINESTRING(" + ", ".join(f"{x:.7f} {y:.7f}" for x, y in before[rid]) + ")", km])
    json.dump(old, open(BACKUP, "w"))
    with engine.begin() as conn:
        for rid, name, km, new_km, cut, stems, clean in changes:
            wkt = "LINESTRING(" + ", ".join(f"{x:.7f} {y:.7f}" for x, y in clean) + ")"
            conn.execute(text("UPDATE route SET gps_path = ST_GeomFromText(:w, 4326), distance_km = :d, "
                              "shade_pct = NULL WHERE id = :id"), {"w": wkt, "d": round(new_km, 3), "id": rid})
    print(f"\nCut stems off {len(changes)} loops. Now re-run update_elevation_dem.py, update_shade_canopy.py, "
          f"update_scenic.py and update_traffic.py.")


if __name__ == "__main__":
    main()
