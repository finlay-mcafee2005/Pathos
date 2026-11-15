"""
Stoplights, intersections and busy-road crossings along each route, from OpenStreetMap:

  stops_per_km          traffic lights the route passes, per km (stop signs aren't counted:
                        OSM puts them on the side street, so most are for the other traffic)
  intersections_per_km  road junctions the route passes through, per km (side streets
                        it crosses or that join it; each is a place you may have to stop)
  busy_crossings        times it crosses a busy road (primary / secondary / trunk, e.g. York)
  unsafe_crossings      ...of those, how many have no crosswalk, light or stop sign within
                        ~30 m, so you'd be crossing traffic with nothing to help you

Testers' feedback: stopping at lights and street crossings broke up their runs, and one
route had them jaywalk across York. The scoring engine uses these to prefer routes with
fewer stops and to avoid unprotected crossings of busy roads.

OSM in LA maps traffic lights well but not every painted crosswalk, so a crossing with
no mapped crosswalk can still be flagged when one exists; lights and stop signs count
as safe too, which covers most of them.

Uses the local map file in osrm-data/ (first run extracts what it needs to
.shade_cache/crossings_local.json, a few minutes). Run from backend/:
    DATABASE_URL=... python3 scripts/update_crossings.py --dry-run
    DATABASE_URL=... python3 scripts/update_crossings.py
Testing without the database (updates the audit's route cache only):
    python3 scripts/update_crossings.py --cache
"""
import glob
import json
import math
import os
import pickle
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, ".shade_cache", "crossings_local.json")
CACHE = os.path.join(HERE, "audit_output", "routes_cache.pkl")
BBOX = (-118.60, 33.90, -117.95, 34.40)          # lon/lat box around the routes
BUSY = {"primary", "primary_link", "secondary", "secondary_link", "trunk", "trunk_link"}
# roads cars use: a junction of two of these is an intersection
DRIVE = BUSY | {"tertiary", "tertiary_link", "residential", "unclassified", "living_street"}
UNSAFE_CROSSING = {"no", "unmarked", "informal"}
STOP_NEAR_M = 12          # a light this close to the line is on the route
CROSS_CHECK_M = 25        # a crossing goes from >= SIDE_M on one side of the road to the other
SIDE_M = 6                #   (running along the road, or on top of its line, isn't crossing it)
JUNCTION_NEAR_M = 8       # a junction this close to the line is one the route passes through
SAFE_NEAR_M = 30          # a crosswalk / light / stop sign this close makes a crossing safe
GROUP_M = 30              # points closer than this count once (both sides of a junction)
CROSS_GROUP_M = 45        # busy crossings closer than this are one (divided roads)
LAT0 = 34.15
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110540


def m(lon, lat):
    return lon * KX, lat * KY


def inside(lon, lat):
    return BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


def extract():
    import osmium
    pbf = (glob.glob(os.path.join(HERE, "..", "..", "osrm-data", "*.osm.pbf")) or [None])[0]
    if not pbf:
        sys.exit("No .osm.pbf map file in osrm-data/.")
    signals, stop_signs, safe = [], [], []      # lights; stop signs; marked crossings
    busy = []
    node_count, node_loc = {}, {}

    class H(osmium.SimpleHandler):
        def node(self, n):
            if not n.location.valid() or not inside(n.location.lon, n.location.lat):
                return
            hw, cr = n.tags.get("highway"), n.tags.get("crossing")
            p = (n.location.lon, n.location.lat)
            if hw == "traffic_signals" or cr == "traffic_signals":
                signals.append(p)
            elif hw == "stop":
                stop_signs.append(p)
            elif hw == "crossing" and cr not in UNSAFE_CROSSING:
                safe.append(p)

        def way(self, w):
            hw = w.tags.get("highway")
            # a mapped crosswalk drawn as a short footway across the road
            if hw == "footway" and w.tags.get("footway") == "crossing" \
                    and w.tags.get("crossing") not in UNSAFE_CROSSING:
                try:
                    pts = [(n.lon, n.lat) for n in w.nodes]
                except osmium.InvalidLocationError:
                    return
                if pts and inside(*pts[0]):
                    mid = pts[len(pts) // 2]
                    safe.append(mid)
                return
            if hw not in DRIVE:
                return
            try:
                pts = [(n.ref, n.lon, n.lat) for n in w.nodes]
            except osmium.InvalidLocationError:
                return
            if not any(inside(x, y) for _, x, y in pts):
                return
            for ref, x, y in pts:
                node_count[ref] = node_count.get(ref, 0) + 1
                node_loc[ref] = (x, y)
            if hw in BUSY:
                busy.append([(x, y) for _, x, y in pts])

    print("Reading the map file for lights, crosswalks and junctions (a few minutes)...")
    H().apply_file(pbf, locations=True, idx="flex_mem")
    junctions = [node_loc[r] for r, c in node_count.items() if c >= 2]
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w") as f:
        json.dump({"signals": signals, "stop_signs": stop_signs, "safe": safe, "busy": busy,
                   "junctions": junctions}, f)
    print(f"  {len(signals)} lights, {len(stop_signs)} stop signs, {len(safe)} crosswalks, {len(junctions)} junctions, "
          f"{len(busy)} busy-road pieces")


def load_index():
    from shapely.geometry import LineString, Point
    from shapely.strtree import STRtree
    d = json.load(open(DATA)) if os.path.exists(DATA) else {}
    if "signals" not in d:            # older cache that lumped lights and stop signs together
        extract()
        d = json.load(open(DATA))
    pts = lambda key: [Point(m(*p)) for p in d[key]]
    signals, junctions = pts("signals"), pts("junctions")
    safe = pts("safe") + signals + pts("stop_signs")      # anything that helps you cross
    busy = [LineString([m(*p) for p in w]) for w in d["busy"] if len(w) >= 2]
    return {"stops": (signals, STRtree(signals)), "safe": (safe, STRtree(safe)),
            "junctions": (junctions, STRtree(junctions)), "busy": (busy, STRtree(busy))}


def _near(line, layer, dist):
    geoms, tree = layer
    return [geoms[int(i)] for i in tree.query(line.buffer(dist))
            if geoms[int(i)].distance(line) <= dist]


def _group(points, dist):
    """Points along a route, counting each cluster once."""
    kept = []
    for p in points:
        if not any(math.dist((p.x, p.y), (k.x, k.y)) < dist for k in kept):
            kept.append(p)
    return kept


def measure(coords, index):
    from shapely.geometry import LineString, Point
    line = LineString([m(*p) for p in coords])
    km = line.length / 1000
    if km < 0.05:
        return None
    stops = _group(_near(line, index["stops"], STOP_NEAR_M), GROUP_M)
    junctions = _group(_near(line, index["junctions"], JUNCTION_NEAR_M), GROUP_M)

    # where the route crosses a busy road: it has to be clearly on one side of the road
    # 25 m before and clearly on the other side 25 m after. Routes are drawn on road
    # centrelines, so a route running ALONG York touches York's line over and over;
    # none of those are crossings.
    busy, tree = index["busy"]
    hits = []
    L = line.length
    for i in tree.query(line):
        road = busy[int(i)]
        inter = line.intersection(road)
        for g in getattr(inter, "geoms", [inter]):
            if g.is_empty or g.geom_type != "Point":
                continue
            t = line.project(g)
            if t < CROSS_CHECK_M or t > L - CROSS_CHECK_M:
                continue
            a, b = line.interpolate(t - CROSS_CHECK_M), line.interpolate(t + CROSS_CHECK_M)
            near = [busy[int(j)] for j in tree.query(LineString([a, b]).buffer(SIDE_M))]
            if min((r.distance(a) for r in near), default=1e9) < SIDE_M \
                    or min((r.distance(b) for r in near), default=1e9) < SIDE_M:
                continue          # on or right beside the road: running along it / turning off it
            if LineString([a, b]).intersects(road):
                hits.append(g)
    crossings = _group(hits, CROSS_GROUP_M)
    safe_pts = index["safe"]
    unsafe = 0
    for c in crossings:
        zone = c.buffer(SAFE_NEAR_M)
        if not any(safe_pts[0][int(i)].distance(c) <= SAFE_NEAR_M for i in safe_pts[1].query(zone)):
            unsafe += 1
    return dict(stops_per_km=round(len(stops) / km, 2), intersections_per_km=round(len(junctions) / km, 2),
                busy_crossings=len(crossings), unsafe_crossings=unsafe)


def summary(results):
    vals = [r for _, _, r in results if r]
    if not vals:
        return
    def q(key, p):
        s = sorted(v[key] for v in vals); return s[int(p * (len(s) - 1))]
    print(f"\n{len(vals)} routes measured.")
    print(f"  traffic lights per mile: median {q('stops_per_km', .5) * 1.609:.1f}, "
          f"90th pct {q('stops_per_km', .9) * 1.609:.1f}")
    print(f"  intersections per mile: median {q('intersections_per_km', .5) * 1.609:.1f}, "
          f"90th pct {q('intersections_per_km', .9) * 1.609:.1f}")
    print(f"  cross a busy road: {sum(v['busy_crossings'] > 0 for v in vals)} routes; "
          f"with no crosswalk or light: {sum(v['unsafe_crossings'] > 0 for v in vals)} routes")
    worst = sorted(results, key=lambda t: -(t[2] or {}).get("unsafe_crossings", 0))[:8]
    print("  most unprotected busy crossings:")
    for _, name, r in worst:
        if r and r["unsafe_crossings"]:
            print(f"    {r['unsafe_crossings']}  {name}")


COLS = [("stops_per_km", "FLOAT"), ("intersections_per_km", "FLOAT"),
        ("busy_crossings", "INTEGER"), ("unsafe_crossings", "INTEGER")]


def main():
    if "--extract" in sys.argv or not os.path.exists(DATA):
        extract()
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
        for col, typ in COLS:
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
                conn.execute(text("UPDATE route SET stops_per_km=:s, intersections_per_km=:i, "
                                  "busy_crossings=:b, unsafe_crossings=:u WHERE id=:id"),
                             {"s": r["stops_per_km"], "i": r["intersections_per_km"],
                              "b": r["busy_crossings"], "u": r["unsafe_crossings"], "id": rid})
    print(f"\nSaved stops and crossings for {sum(1 for *_, r in results if r)} routes.")


if __name__ == "__main__":
    main()
