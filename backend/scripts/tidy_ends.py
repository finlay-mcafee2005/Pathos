"""
Tidy two leftovers that make a route look odd, on every kind of route (trails too):

1. A little loop at the start: the line leaves the start on one street and comes back
   on another one nearby, so the first and last few hundred metres draw a small box
   before the real loop. That box becomes a plain way in and out: the way back to the
   start follows the way out (a short stem), so the route is one clean loop.
2. Dead-end tails: anywhere on a loop, a stretch run out and straight back the same way
   (up to 2 km each way). And short, straight dead-end dashes anywhere on a loop (out along a street or path and
   back, maybe on the other side of it), which the first spur cleanup missed.

3. A "loop" that's really out one side of a street or path and back the other side,
   with little jogs where it crosses over: it becomes one line out and back (the way
   with the fewest turns), so it's a plain out-and-back.

Run from backend/:
    python3 scripts/tidy_ends.py --cache --preview            # try on the audit cache
    DATABASE_URL=... python3 scripts/tidy_ends.py --preview   # drawings, nothing saved
    DATABASE_URL=... python3 scripts/tidy_ends.py             # save
    DATABASE_URL=... python3 scripts/tidy_ends.py --undo
Then re-measure:
    python3 scripts/update_elevation_dem.py
    python3 scripts/update_shade_canopy.py
    python3 scripts/update_scenic.py
    python3 scripts/update_traffic.py
    python3 scripts/update_route_shape.py
    python3 scripts/update_steepness.py --hide-trail 1
    python3 scripts/update_difficulty.py
"""
import json
import math
import os
import pickle
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import clean_route_spurs as spurs  # noqa: E402
from clean_route_spurs import densify, dist_m, length_m  # noqa: E402
from route_shape import mess_score  # noqa: E402

CACHE = os.path.join(HERE, "audit_output", "routes_cache.pkl")
BACKUP = os.path.join(HERE, "tidy_ends_backup.json")
OUT = os.path.join(HERE, "audit_output", "tidy_preview")

HEAD_M = 1200          # look this far from each end for the start box
JOIN_M = 20            # the way out and the way back meet again (closer than this)
SAME_M = 25            # ...and before that they're different streets (farther apart than this)
MIN_BOX_M = 250        # a box smaller than this isn't worth touching
MAX_BOX_SHARE = 0.25


def cumulative(pts):
    cum = [0.0]
    for a, b in zip(pts, pts[1:]):
        cum.append(cum[-1] + dist_m(a, b))
    return cum


def fix_start_box(pts):
    """Returns new points, or None if the start is already clean."""
    if dist_m(pts[0], pts[-1]) > 50:
        return None                         # not a loop (out-and-back / one-way)
    cum = cumulative(pts)
    total = cum[-1]
    head = [k for k in range(len(pts)) if cum[k] <= HEAD_M]
    tail = [k for k in range(len(pts)) if total - cum[k] <= HEAD_M]
    if not head or not tail or head[-1] >= tail[0]:
        return None
    best = None
    for i in reversed(head):                # farthest point out where the two ends meet again
        for j in tail:
            if dist_m(pts[i], pts[j]) < JOIN_M:
                best = (i, j)
                break
        if best:
            break
    if not best:
        return None
    i, j = best
    box = cum[i] + (total - cum[j])
    if box < MIN_BOX_M or box > MAX_BOX_SHARE * total:
        return None
    # already a stem (the way back follows the way out)? then there's no box
    apart = sum(1 for k in range(0, i + 1, 3)
                if min(dist_m(pts[k], pts[m]) for m in range(j, len(pts), 2)) > SAME_M)
    if apart < 0.3 * len(range(0, i + 1, 3)):
        return None
    way_in = pts[:i + 1]
    return way_in + pts[i + 1:j] + [pts[j]] + list(reversed(way_in))


def end_spurs(pts, join_m=14):
    """Straight dead-end dashes anywhere on a loop (out along a street and back,
    maybe on the other side of it). Hairpins and switchbacks aren't straight, so they stay."""
    cum = cumulative(pts)
    total = cum[-1]
    far = max(range(len(pts)), key=lambda k: dist_m(pts[0], pts[k]))   # out-and-back turnaround
    keep, cut, i = [], 0.0, 0
    while i < len(pts):
        keep.append(i)
        near_end = True          # anywhere along the loop (straight dashes only, so hairpins stay)
        best = None
        if near_end:
            k = i + 6
            while k < len(pts) and cum[k] - cum[i] <= 900:
                if cum[k] - cum[i] >= 80 and dist_m(pts[i], pts[k]) < join_m and not (i < far < k):
                    t = max(range(i, k + 1), key=lambda m: dist_m(pts[i], pts[m]))
                    reach = dist_m(pts[i], pts[t])
                    if reach >= 0.4 * (cum[k] - cum[i]) and \
                            reach >= 0.85 * (cum[t] - cum[i]) and reach >= 0.85 * (cum[k] - cum[t]):
                        best = k
                k += 1
        if best is not None and best < len(pts) - 1:
            cut += cum[best] - cum[i]
            i = best + 1
        else:
            i += 1
    if keep[-1] != len(pts) - 1:
        keep.append(len(pts) - 1)
    return [pts[k] for k in keep], cut


def dead_ends(pts):
    """Long dead-end tails on a loop: the line goes out along a street or trail and comes
    straight back along the very same way (up to 2 km each way). Only exact retraces count,
    so switchbacks and hairpins (whose legs are apart) are never touched."""
    cum = cumulative(pts)
    total = cum[-1]
    keep, cut, i = [], 0.0, 0
    old = spurs.RETRACE_M
    spurs.RETRACE_M = 12
    try:
        while i < len(pts):
            keep.append(i)
            best = None
            if i > 0:
                k = i + 8
                while k < len(pts) - 1 and cum[k] - cum[i] <= 4000:
                    if cum[k] - cum[i] >= 150 and dist_m(pts[i], pts[k]) < 12 \
                            and spurs.is_retrace(pts, cum, i, k):
                        best = k
                    k += 1
            if best is not None and cut + cum[best] - cum[i] <= 0.35 * total:
                cut += cum[best] - cum[i]
                i = best + 1
            else:
                i += 1
    finally:
        spurs.RETRACE_M = old
    if keep[-1] != len(pts) - 1:
        keep.append(len(pts) - 1)
    return [pts[k] for k in keep], cut


SIDE_M = 45            # the way back runs this close to the way out (other side of the street)
SIDE_SHARE = 0.85     # ...for this much of the route = it's really an out-and-back
NET = None            # street network, for redrawing the way out (loaded once, in main)


def side_share(pts, cum, near=SIDE_M):
    """Share of the line that has another part of the route (300 m+ further along) within
    `near`: near 1 = out one side of a street or path and back the other side."""
    import math as _m
    SIDE = near
    cell = SIDE
    kx = 111320 * _m.cos(_m.radians(pts[0][1]))
    grid = {}
    xy = [(x * kx, y * 110540) for x, y in pts]
    for k, (x, y) in enumerate(xy):
        grid.setdefault((int(x // cell), int(y // cell)), []).append(k)
    hits = 0
    for k, (x, y) in enumerate(xy):
        gx, gy = int(x // cell), int(y // cell)
        if any(abs(cum[j] - cum[k]) > 300 and _m.hypot(xy[j][0] - x, xy[j][1] - y) < SIDE
               for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in grid.get((gx + dx, gy + dy), ())):
            hits += 1
    return hits / len(pts)


def collapse_sides(pts):
    """A 'loop' that's really out one side of a street and back the other (with little jogs
    where it crosses over): make it a plain out-and-back on one line, the way with the
    fewest turns from the start to the far end, then back the same way."""
    cum = cumulative(pts)
    if cum[-1] < 800 or side_share(pts, cum) < SIDE_SHARE:
        return None
    if side_share(pts, cum, 6) >= 0.6:
        return None               # already a clean out-and-back (back the very same way)
    # the far end: where the way out turns into the way back - around halfway along, the
    # point farthest from the start
    mid = [k for k in range(len(pts)) if 0.3 * cum[-1] <= cum[k] <= 0.7 * cum[-1]]
    far = max(mid, key=lambda k: dist_m(pts[0], pts[k]))
    out = pts[:far + 1]
    if NET is not None:
        import simplify_turns as st
        a, b = st.snap(pts[0], NET), st.snap(pts[far], NET)
        if a is not None and b is not None and a != b:
            res = st.fewest_turns(NET, a, b, None, None, cum[far] * 1.15)
            if res and 0.8 * cum[far] <= res[1] <= 1.15 * cum[far] and \
                    st.count_turns(res[0]) <= st.count_turns(out):
                out = [pts[0]] + list(res[0]) + [pts[far]]
    if len(out) < 2:
        return None
    line = out + list(reversed(out))[1:]
    # the one line must still cover the whole route (nothing cut off, no bit left out)
    from shapely.geometry import LineString, Point
    kx = 111320 * math.cos(math.radians(pts[0][1]))
    ls = LineString([(x * kx, y * 110540) for x, y in out])
    covered = sum(ls.distance(Point(x * kx, y * 110540)) <= 50 for x, y in pts[::3]) / len(pts[::3])
    return line if covered >= 0.97 else None


def tidy(coords, surface):
    if dist_m(coords[0], coords[-1]) > 50:
        return None              # out-and-backs and one-way trails: their ends are the point
    pts = densify(coords, 10.0)
    changed = []
    straight = collapse_sides(pts)
    if straight:
        L0 = length_m(coords)
        if 0.85 * L0 <= length_m(straight) <= 1.15 * L0:   # one line, not a shortcut
            return straight, ["one line out and back"]
    # the dash must come back to (almost) the same spot: switchback legs are 15 m+ apart on a
    # hillside, and jumping across them would cut the slope
    new, cut = end_spurs(pts, 9 if surface == "trail" else 14)
    if cut >= 60:
        changed.append(f"spur {cut:.0f} m")
        pts = new
    new, cut = dead_ends(pts)
    if cut >= 150:
        changed.append(f"dead end {cut:.0f} m")
        pts = new
    box = fix_start_box(pts)
    if box:
        changed.append("start box")
        pts = box
    if not changed:
        return None
    if mess_score(pts, surface) > mess_score(coords, surface) + 1.0:   # a stem adds a little overlap
        return None
    L0, L1 = length_m(coords), length_m(pts)
    if not ((0.62 if any(c.startswith("dead end") for c in changed) else 0.8) * L0 <= L1 <= 1.1 * L0) \
            or dist_m(pts[0], coords[0]) > 60:
        return None
    # thin the 10 m points back out on straight bits
    from shapely.geometry import LineString
    kx = 111320 * math.cos(math.radians(pts[0][1]))
    simple = LineString([(x * kx, y * 110540) for x, y in pts]).simplify(1.5)
    pts = [(x / kx, y / 110540) for x, y in simple.coords]
    return pts, changed


def _one(args):
    try:
        return tidy(*args)
    except Exception:
        return None


def to_wkt(c):
    return "LINESTRING(" + ", ".join(f"{x:.7f} {y:.7f}" for x, y in c) + ")"


def write_previews(changes):
    os.makedirs(OUT, exist_ok=True)
    cards = []
    for n, (rid, name, km, old, new, what) in enumerate(changes):
        xs = [p[0] for p in old]; ys = [p[1] for p in old]
        kx = math.cos(math.radians(sum(ys) / len(ys)))
        sc = 380 / max((max(xs) - min(xs)) * kx or 1e-6, (max(ys) - min(ys)) or 1e-6)

        def poly(ps):
            return " ".join(f"{20 + (x - min(xs)) * kx * sc:.1f},{20 + (max(ys) - y) * sc:.1f}" for x, y in ps)
        s0 = old[0]
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="440" viewBox="0 0 420 440">'
               f'<rect width="420" height="440" fill="#fff"/>'
               f'<polyline points="{poly(old)}" fill="none" stroke="#f87171" stroke-width="6" stroke-linejoin="round"/>'
               f'<polyline points="{poly(new)}" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linejoin="round"/>'
               f'<circle cx="{20 + (s0[0] - min(xs)) * kx * sc:.1f}" cy="{20 + (max(ys) - s0[1]) * sc:.1f}" r="5" fill="#111"/>'
               f'<text x="10" y="425" font-family="sans-serif" font-size="12">{name[:40]}: {", ".join(what)}</text></svg>')
        fn = f"route_{n:03d}.svg"
        open(os.path.join(OUT, fn), "w").write(svg)
        cards.append(f'<img src="{fn}" width="300">')
    open(os.path.join(OUT, "index.html"), "w").write(
        "<html><body style='font-family:sans-serif'><p>Red = before, blue = after, dot = start.</p>"
        "<div style='display:flex;flex-wrap:wrap;gap:6px'>" + "".join(cards) + "</div></body></html>")
    print(f"\nPreview drawings: {OUT}/index.html")


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
        engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
        with engine.connect() as conn:
            raw = conn.execute(text("SELECT id, COALESCE(nickname, name), distance_km, surface_type, "
                                    "ST_AsText(gps_path) FROM route WHERE NOT COALESCE(hidden, FALSE)")).all()
        rows = [(rid, name, km, surf, [tuple(map(float, p.split())) for p in wkt[wkt.index("(") + 1:-1].split(",")])
                for rid, name, km, surf, wkt in raw if wkt and wkt.startswith("LINESTRING")]
    if "--only" in sys.argv:
        word = sys.argv[sys.argv.index("--only") + 1].lower()
        rows = [r for r in rows if word in (r[1] or "").lower()]
    global NET
    import simplify_turns as st
    print("Loading the street network...", flush=True)
    NET = st.load_network()
    from multiprocessing import get_context
    print(f"Checking {len(rows)} routes...", flush=True)
    with get_context("fork").Pool(max(1, os.cpu_count() or 2)) as pool:
        results = pool.map(_one, [(c, s) for _, _, _, s, c in rows], chunksize=8)
    changes = [(rid, name, km, coords, res[0], res[1])
               for (rid, name, km, surf, coords), res in zip(rows, results) if res]
    boxes = sum("start box" in c[5] for c in changes)
    lines = sum("one line out and back" in c[5] for c in changes)
    print(f"  ({lines} two-sided loops made into one line out and back)")
    print(f"\n{len(rows)} routes checked; {len(changes)} tidied "
          f"({boxes} start boxes, {lines} made one line, {len(changes) - boxes - lines} with dead ends / dashes).")
    for rid, name, km, old, new, what in changes[:30]:
        print(f"  {(name or '')[:42]:<42} {', '.join(what)}")
    if "--preview" in sys.argv or "--dry-run" in sys.argv or use_cache:
        if "--preview" in sys.argv:
            write_previews(changes)
        print("\nPreview only: nothing saved.")
        return
    old = json.load(open(BACKUP)) if os.path.exists(BACKUP) else {}
    for rid, name, km, oc, *_ in changes:
        old.setdefault(str(rid), [to_wkt(oc), km])
    json.dump(old, open(BACKUP, "w"))
    rows_out = [{"w": to_wkt(new), "d": round(length_m(new) / 1000, 3), "id": rid}
                for rid, name, km, oc, new, what in changes]
    import time
    for k in range(0, len(rows_out), 100):
        for attempt in range(1, 5):
            try:
                with engine.begin() as conn:
                    conn.execute(text("UPDATE route SET gps_path = ST_GeomFromText(:w, 4326), distance_km = :d, "
                                      "shade_pct = NULL WHERE id = :id"), rows_out[k:k + 100])
                break
            except Exception:
                if attempt == 4:
                    raise
                print(f"  database connection dropped, retrying ({attempt}/3)...")
                engine.dispose()
                time.sleep(3)
    print(f"\nTidied {len(changes)} routes. Now run the re-measure scripts listed at the top of this file.")


if __name__ == "__main__":
    main()
