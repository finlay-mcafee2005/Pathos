"""
Measure how "quiet" and how easy to follow each route is, from OpenStreetMap:

  busy_pct           share of the route along a busy road (primary / secondary / trunk)
  freeway_crossings  how many times it crosses a freeway (over or under it)
  downtown_pct       share of the route inside downtown LA
  turns_per_km       sharp turns (over 60 degrees) per km - fewer = simpler to follow

The scoring engine uses these to prefer quiet side streets and simple routes,
and the check-in's "Quiet side streets only" option makes them a hard limit.

Uses the local map file in osrm-data/ (first run extracts the roads it needs to
.shade_cache/roads_local.json, about a minute). Run from backend/:
    DATABASE_URL=... python3 scripts/update_traffic.py --dry-run
    DATABASE_URL=... python3 scripts/update_traffic.py
Testing without the database (updates the audit's route cache only):
    python3 scripts/update_traffic.py --cache
"""
import glob
import json
import math
import os
import pickle
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree

HERE = os.path.dirname(__file__)
ROADS = os.path.join(HERE, ".shade_cache", "roads_local.json")
CACHE = os.path.join(HERE, "audit_output", "routes_cache.pkl")
BUSY = {"primary", "primary_link", "secondary", "secondary_link", "trunk", "trunk_link"}
FREEWAY = {"motorway", "motorway_link"}
BBOX = (-118.60, 33.90, -117.95, 34.40)          # lon/lat box around the routes
NEAR_BUSY_M = 15                                 # this close to a busy road = running along it
SAMPLE_M = 20
CROSSING_GROUP_M = 150                           # crossings this close together = one crossing
# downtown LA (roughly the 110 / 101 / LA River / 10 box)
DOWNTOWN = [(-118.2730, 34.0300), (-118.2360, 34.0300), (-118.2300, 34.0650), (-118.2560, 34.0700), (-118.2730, 34.0560)]
LAT0 = 34.15
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110540


def m(lon, lat):
    return lon * KX, lat * KY


def extract_roads():
    import osmium
    pbf = (glob.glob(os.path.join(HERE, "..", "..", "osrm-data", "*.osm.pbf")) or [None])[0]
    if not pbf:
        sys.exit("No .osm.pbf map file in osrm-data/.")
    busy, freeway = [], []

    class H(osmium.SimpleHandler):
        def way(self, w):
            hw = w.tags.get("highway")
            if hw not in BUSY and hw not in FREEWAY:
                return
            try:
                pts = [(n.lon, n.lat) for n in w.nodes]
            except osmium.InvalidLocationError:
                return
            if len(pts) < 2 or not any(BBOX[0] <= x <= BBOX[2] and BBOX[1] <= y <= BBOX[3] for x, y in pts):
                return
            (busy if hw in BUSY else freeway).append(pts)

    print("Reading the map file for busy roads and freeways (about a minute)...")
    H().apply_file(pbf, locations=True, idx="flex_mem")
    os.makedirs(os.path.dirname(ROADS), exist_ok=True)
    with open(ROADS, "w") as f:
        json.dump({"busy": busy, "freeway": freeway}, f)
    print(f"  {len(busy)} busy-road pieces, {len(freeway)} freeway pieces")


def load_index():
    if not os.path.exists(ROADS):
        extract_roads()
    d = json.load(open(ROADS))
    busy = [LineString([m(*p) for p in w]) for w in d["busy"]]
    fwy = [LineString([m(*p) for p in w]) for w in d["freeway"]]
    return busy, STRtree(busy), fwy, STRtree(fwy), Polygon([m(*p) for p in DOWNTOWN])


def measure(coords, index):
    busy, busy_tree, fwy, fwy_tree, downtown = index
    line = LineString([m(*p) for p in coords])
    L = line.length
    if L < 50:
        return None
    n = max(2, int(L // SAMPLE_M))
    pts = [line.interpolate(k * L / n) for k in range(n + 1)]
    near = 0
    for p in pts:
        if any(busy[int(i)].distance(p) <= NEAR_BUSY_M for i in busy_tree.query(p.buffer(NEAR_BUSY_M))):
            near += 1
    # freeway crossings: where the line crosses a freeway, grouping nearby hits (both directions, ramps)
    hits = []
    for i in fwy_tree.query(line):
        inter = line.intersection(fwy[int(i)])
        for g in getattr(inter, "geoms", [inter]):
            if not g.is_empty:
                c = g.centroid
                hits.append((c.x, c.y))
    groups = []
    for h in hits:
        if not any(math.dist(h, g) < CROSSING_GROUP_M for g in groups):
            groups.append(h)
    in_dt = sum(downtown.contains(p) for p in pts) / len(pts)
    # sharp turns on a lightly simplified line (ignores GPS wiggle and gentle curves)
    c = list(line.simplify(10).coords)
    turns = 0
    for a, b, e in zip(c, c[1:], c[2:]):
        v1 = (b[0] - a[0], b[1] - a[1]); v2 = (e[0] - b[0], e[1] - b[1])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 >= 30 and n2 >= 30 and (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2) < 0.5:
            turns += 1
    return dict(busy_pct=round(near / len(pts), 3), freeway_crossings=len(groups),
                downtown_pct=round(in_dt, 3), turns_per_km=round(turns / (L / 1000), 2))


def summary(results):
    vals = [r for _, _, r in results if r]
    if not vals:
        return
    def q(key, p):
        s = sorted(v[key] for v in vals); return s[int(p * (len(s) - 1))]
    print(f"\n{len(vals)} routes measured.")
    print(f"  on busy roads: median {q('busy_pct', .5):.0%}, 75th pct {q('busy_pct', .75):.0%}, 90th pct {q('busy_pct', .9):.0%}")
    print(f"  cross a freeway: {sum(v['freeway_crossings'] > 0 for v in vals)} routes")
    print(f"  any part downtown: {sum(v['downtown_pct'] > 0 for v in vals)} routes")
    print(f"  sharp turns per mile: median {q('turns_per_km', .5) * 1.609:.1f}, 90th pct {q('turns_per_km', .9) * 1.609:.1f}")
    worst = sorted(results, key=lambda t: -(t[2] or {}).get("busy_pct", 0))[:8]
    print("  most time on busy roads:")
    for _, name, r in worst:
        print(f"    {r['busy_pct']:.0%}  {name}")


def main():
    index = load_index()
    if "--cache" in sys.argv:
        rows = pickle.load(open(CACHE, "rb"))
        results = []
        for r in rows:
            res = measure(r["coords"], index)
            if res:
                r.update(res)
            results.append((r["id"], r["nickname"] or r["name"], res))
        pickle.dump(rows, open(CACHE, "wb"))
        summary(results)
        print("\nSaved to the audit cache only (no database).")
        return
    if "DATABASE_URL" not in os.environ:
        sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
    from sqlalchemy import create_engine, text
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as conn:
        for col, typ in [("busy_pct", "FLOAT"), ("freeway_crossings", "INTEGER"),
                         ("downtown_pct", "FLOAT"), ("turns_per_km", "FLOAT")]:
            conn.execute(text(f"ALTER TABLE route ADD COLUMN IF NOT EXISTS {col} {typ}"))
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, COALESCE(nickname, name), ST_AsText(gps_path) FROM route "
                                 "WHERE NOT COALESCE(hidden, FALSE)")).all()
    results = []
    for k, (rid, name, wkt) in enumerate(rows, 1):
        if k % 200 == 0:
            print(f"  {k}/{len(rows)} measured")
        if not wkt or not wkt.startswith("LINESTRING"):
            continue
        co = [tuple(map(float, p.split())) for p in wkt[wkt.index("(") + 1:-1].split(",")]
        results.append((rid, name, measure(co, index)))
    summary(results)
    if "--dry-run" in sys.argv:
        print("\nDry run: nothing saved.")
        return
    with engine.begin() as conn:
        for rid, _, r in results:
            if r:
                conn.execute(text("UPDATE route SET busy_pct=:b, freeway_crossings=:f, downtown_pct=:d, "
                                  "turns_per_km=:t WHERE id=:id"),
                             {"b": r["busy_pct"], "f": r["freeway_crossings"], "d": r["downtown_pct"],
                              "t": r["turns_per_km"], "id": rid})
    print(f"\nSaved road and turn measures for {sum(1 for *_, r in results if r)} routes.")


if __name__ == "__main__":
    main()
