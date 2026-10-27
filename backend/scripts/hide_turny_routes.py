"""
Hide routes with more than 4 turns per mile, so every route is simple to follow.
Run it after simplify_turns.py (and --strong), which redraw what they can first.

How turns are counted: corners sharper than 60 degrees that are at a junction, where you
have to pick a way (every street corner counts). A road curving or a trail bending round
a hillside isn't a turn you can get wrong, so those don't count.

Nothing is deleted: routes are set hidden, and --undo un-hides exactly the ones this
script hid. Run from backend/ (needs scripts/.shade_cache/network.pkl):
    DATABASE_URL=... python3 scripts/hide_turny_routes.py --preview   # list + drawings, nothing saved
    DATABASE_URL=... python3 scripts/hide_turny_routes.py             # hide them
    DATABASE_URL=... python3 scripts/hide_turny_routes.py --undo
    python3 scripts/hide_turny_routes.py --cache --preview             # try on the audit cache
"""
import json
import math
import os
import pickle
import sys
from collections import Counter

from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
NETWORK = os.path.join(HERE, ".shade_cache", "network.pkl")
CACHE = os.path.join(HERE, "audit_output", "routes_cache.pkl")
RECORD = os.path.join(HERE, "turny_hidden.json")
OUT = os.path.join(HERE, "audit_output", "turny_preview")
MAX_PER_MILE = float(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 4.0
JUNCTION_M = 25
LAT0 = 34.15
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110540


def junctions():
    d = pickle.load(open(NETWORK, "rb"))
    deg = Counter()
    for u, v, *_ in d["edges"]:
        if u != v:
            deg[u] += 1
            deg[v] += 1
    pts = [Point(d["nodes"][n][0] * KX, d["nodes"][n][1] * KY) for n, k in deg.items() if k >= 3]
    return pts, STRtree(pts)


def turns_per_mile(coords, surface, junc):
    line = LineString([(x * KX, y * KY) for x, y in coords])
    L = line.length
    if L < 200:
        return 0.0
    c = list(line.simplify(10).coords)
    turns = 0
    for a, b, e in zip(c, c[1:], c[2:]):
        v1 = (b[0] - a[0], b[1] - a[1]); v2 = (e[0] - b[0], e[1] - b[1])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 >= 30 and n2 >= 30 and (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2) < 0.5:
            p = Point(b)
            pts, tree = junc
            if not any(pts[int(i)].distance(p) <= JUNCTION_M for i in tree.query(p.buffer(JUNCTION_M))):
                continue          # a bend in the road or trail, not a junction
            turns += 1
    return turns / (L / 1609.34)


def write_previews(items):
    os.makedirs(OUT, exist_ok=True)
    cards = []
    for n, (name, surf, tpm, co) in enumerate(items):
        xs = [p[0] for p in co]; ys = [p[1] for p in co]
        kx = math.cos(math.radians(sum(ys) / len(ys)))
        sc = 260 / max((max(xs) - min(xs)) * kx or 1e-6, (max(ys) - min(ys)) or 1e-6)
        pts = " ".join(f"{15 + (x - min(xs)) * kx * sc:.1f},{15 + (max(ys) - y) * sc:.1f}" for x, y in co)
        fn = f"route_{n:03d}.svg"
        open(os.path.join(OUT, fn), "w").write(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="290" height="310"><rect width="290" height="310" fill="#fff"/>'
            f'<polyline points="{pts}" fill="none" stroke="#2563eb" stroke-width="2"/>'
            f'<text x="8" y="302" font-family="sans-serif" font-size="11">{name[:34]} ({surf}): {tpm:.1f}/mi</text></svg>')
        cards.append(f'<img src="{fn}">')
    open(os.path.join(OUT, "index.html"), "w").write(
        "<html><body style='font-family:sans-serif'><p>Routes that would be hidden (most turns first).</p>"
        "<div style='display:flex;flex-wrap:wrap;gap:6px'>" + "".join(cards) + "</div></body></html>")
    print(f"\nDrawings: {OUT}/index.html")


def main():
    from sqlalchemy import create_engine, text
    if "--undo" in sys.argv:
        ids = json.load(open(RECORD)) if os.path.exists(RECORD) else []
        engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
        with engine.begin() as conn:
            for i in ids:
                conn.execute(text("UPDATE route SET hidden = FALSE WHERE id = CAST(:id AS uuid)"), {"id": i})
        print(f"Un-hid {len(ids)} routes.")
        return
    use_cache = "--cache" in sys.argv
    if use_cache:
        rows = [(r["id"], r["nickname"] or r["name"], r["surface_type"], r["coords"])
                for r in pickle.load(open(CACHE, "rb")) if not r.get("hidden")]
    else:
        if "DATABASE_URL" not in os.environ:
            sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
        engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
        with engine.connect() as conn:
            raw = conn.execute(text("SELECT id, COALESCE(nickname, name), surface_type, ST_AsText(gps_path) "
                                    "FROM route WHERE NOT COALESCE(hidden, FALSE)")).all()
        rows = [(rid, name, surf, [tuple(map(float, p.split())) for p in wkt[wkt.index("(") + 1:-1].split(",")])
                for rid, name, surf, wkt in raw if wkt and wkt.startswith("LINESTRING")]
    print(f"Measuring {len(rows)} routes...", flush=True)
    junc = junctions()
    measured = [(rid, name or "", surf or "unknown", turns_per_mile(co, surf, junc), co) for rid, name, surf, co in rows]
    hide = sorted([m for m in measured if m[3] > MAX_PER_MILE], key=lambda m: -m[3])
    by = Counter(m[2] for m in measured)
    hid = Counter(m[2] for m in hide)
    print(f"\nOver {MAX_PER_MILE:g} turns per mile: {len(hide)} of {len(measured)} routes")
    for s in sorted(by):
        print(f"  {s:<9} hide {hid.get(s, 0):4d}  keep {by[s] - hid.get(s, 0):4d}")
    for rid, name, surf, tpm, _ in hide[:25]:
        print(f"  {tpm:4.1f}/mi  {surf:<8} {name[:48]}")
    if "--preview" in sys.argv or "--dry-run" in sys.argv or use_cache:
        if "--preview" in sys.argv:
            write_previews([(n, s, t, co) for _, n, s, t, co in hide])
        print("\nPreview only: nothing saved.")
        return
    old = json.load(open(RECORD)) if os.path.exists(RECORD) else []
    json.dump(sorted(set(old) | {str(m[0]) for m in hide}), open(RECORD, "w"))
    ids = [str(m[0]) for m in hide]
    import time
    for k in range(0, len(ids), 200):
        for attempt in range(1, 5):
            try:
                with engine.begin() as conn:
                    conn.execute(text("UPDATE route SET hidden = TRUE WHERE id = CAST(:id AS uuid)"),
                                 [{"id": i} for i in ids[k:k + 200]])
                break
            except Exception:
                if attempt == 4:
                    raise
                print(f"  database connection dropped, retrying ({attempt}/3)...")
                engine.dispose()
                time.sleep(3)
    print(f"\nHid {len(hide)} routes.")


if __name__ == "__main__":
    main()
