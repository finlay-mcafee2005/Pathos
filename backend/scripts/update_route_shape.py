"""
Measure each loop's "stem": the stretch at the start that the route runs out along and
comes back on at the end (a lollipop: out along a street, round a loop, back the same way).

  stem_km  one-way length of that shared start/end stretch (0 = a plain loop)

The app uses it for laps and lap instructions: with a stem, 2 laps means
"out 0.5 mi -> loop x2 -> back 0.5 mi", not running the whole thing (stem and all) twice.

Run from backend/ (after any route cleanup):
    DATABASE_URL=... python3 scripts/update_route_shape.py --dry-run
    DATABASE_URL=... python3 scripts/update_route_shape.py
    python3 scripts/update_route_shape.py --cache        # test on the audit cache
"""
import math
import os
import pickle
import sys

from shapely.geometry import LineString

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "audit_output", "routes_cache.pkl")
STEP_M = 5.0
SAME_M = 15          # out and back this close = the same street
MIN_STEM_M = 100     # shorter: just the start corner
MIN_LOOP_M = 300
CLOSED_M = 150       # start and end this close = a loop-shaped route


def stem_km(coords):
    if len(coords) < 3:
        return 0.0
    lat0 = sum(c[1] for c in coords) / len(coords)
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540
    line = LineString([(x * kx, y * ky) for x, y in coords])
    L = line.length
    if L < 2 * MIN_STEM_M + MIN_LOOP_M or math.dist(line.coords[0], line.coords[-1]) > CLOSED_M:
        return 0.0
    n = int(L // STEP_M)
    pts = [line.interpolate(i * L / n) for i in range(n + 1)]
    k = 0
    while k < n // 2 and pts[k].distance(pts[n - k]) <= SAME_M:
        k += 1
    stem = k * L / n
    if stem < MIN_STEM_M or L - 2 * stem < MIN_LOOP_M:
        return 0.0
    return round(stem / 1000, 3)


def main():
    if "--cache" in sys.argv:
        rows = pickle.load(open(CACHE, "rb"))
        for r in rows:
            r["stem_km"] = stem_km(r["coords"])
        pickle.dump(rows, open(CACHE, "wb"))
        withs = [r for r in rows if r["stem_km"]]
        print(f"{len(withs)} of {len(rows)} routes have a stem (saved to the audit cache only).")
        for r in sorted(withs, key=lambda r: -r["stem_km"])[:10]:
            print(f"  {r['stem_km'] * 0.621:.2f} mi stem  {r['nickname'] or r['name']}")
        return
    if "DATABASE_URL" not in os.environ:
        sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
    from sqlalchemy import create_engine, text
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS stem_km FLOAT"))
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, COALESCE(nickname, name), ST_AsText(gps_path) FROM route "
                                 "WHERE NOT COALESCE(hidden, FALSE)")).all()
    results = []
    for rid, name, wkt in rows:
        if wkt and wkt.startswith("LINESTRING"):
            co = [tuple(map(float, p.split())) for p in wkt[wkt.index("(") + 1:-1].split(",")]
            results.append((rid, name, stem_km(co)))
    withs = [r for r in results if r[2]]
    print(f"{len(withs)} of {len(results)} routes have a stem.")
    for _, name, s in sorted(withs, key=lambda r: -r[2])[:10]:
        print(f"  {s * 0.621:.2f} mi stem  {name}")
    if "--dry-run" in sys.argv:
        print("\nDry run: nothing saved.")
        return
    with engine.begin() as conn:
        for rid, _, s in results:
            conn.execute(text("UPDATE route SET stem_km = :s WHERE id = :id"), {"s": s, "id": rid})
    print(f"\nSaved stem lengths for {len(results)} routes.")


if __name__ == "__main__":
    main()
