"""
Where to park for each route: a parking lot or trailhead on (or right next to) the
route, so drive-to runs start there instead of the middle of a residential street
("at a random person's house").

Nothing about the route line changes. We save, per route:
  start_label   "Fryman Trailhead", "Parking: Griffith Park lot", or "Street parking"
  park_lat/lon  the lot or trailhead (the "Drive to the start" link goes here)
  start_street  the nearest intersection to the start, e.g. "Colorado Blvd & Eagle Rock Blvd"
                (run-from-home cards say "Joins the route at ...")
When someone drives to a route, the app starts the loop at the point nearest the lot
(an out-and-back from whichever end is nearer). Running from home is unchanged.

Run from backend/ (first run reads the map file, ~1 minute):
    DATABASE_URL=... python3 scripts/update_starts.py --dry-run
    DATABASE_URL=... python3 scripts/update_starts.py
    python3 scripts/update_starts.py --cache                        # test on the audit cache
"""
import glob
import json
import math
import os
import pickle
import sys

from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
PLACES = os.path.join(HERE, ".shade_cache", "parking_local.json")
CACHE = os.path.join(HERE, "audit_output", "routes_cache.pkl")
BBOX = (-118.60, 33.90, -117.95, 34.40)
NEAR_LINE_M = 150         # a lot / trailhead this close to the route counts as "at" it
ALREADY_OK_M = 120        # the current start is already this close to one: leave it
LAT0 = 34.15
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110540


def m(lon, lat):
    return lon * KX, lat * KY


def extract():
    import osmium
    pbf = (glob.glob(os.path.join(HERE, "..", "..", "osrm-data", "*.osm.pbf")) or [None])[0]
    if not pbf:
        sys.exit("No .osm.pbf map file in osrm-data/.")
    out = []

    def keep(tags):
        if tags.get("access") in ("private", "no", "customers", "permit", "residents"):
            return None
        if tags.get("highway") == "trailhead":
            return "trailhead"
        if tags.get("amenity") == "parking" and tags.get("parking") not in ("underground", "multi-storey"):
            return "parking"
        return None

    class H(osmium.SimpleHandler):
        def node(self, n):
            kind = keep(n.tags)
            if kind and n.location.valid():
                lon, lat = n.location.lon, n.location.lat
                if BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]:
                    out.append([kind, n.tags.get("name"), lon, lat])

        def way(self, w):
            kind = keep(w.tags)
            if not kind:
                return
            try:
                pts = [(nd.lon, nd.lat) for nd in w.nodes]
            except osmium.InvalidLocationError:
                return
            if not pts:
                return
            lon, lat = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
            if BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]:
                out.append([kind, w.tags.get("name"), lon, lat])

    print("Reading the map file for parking lots and trailheads (about a minute)...")
    H().apply_file(pbf, locations=True, idx="flex_mem")
    os.makedirs(os.path.dirname(PLACES), exist_ok=True)
    json.dump(out, open(PLACES, "w"))
    print(f"  {sum(1 for o in out if o[0] == 'parking')} parking lots, {sum(1 for o in out if o[0] == 'trailhead')} trailheads")


PARK_NEAR_M = 60          # an unnamed lot this close to a named park is that park's lot


def load_places():
    """Trailheads, named lots, and unnamed lots at a park (labelled with the park's name).
    Other unnamed lots (shops, offices, apartments) are left out: not somewhere to park for a run."""
    if not os.path.exists(PLACES):
        extract()
    raw = json.load(open(PLACES))
    from shapely.geometry import Polygon
    net = os.path.join(HERE, ".shade_cache", "network.pkl")
    parks, ptree = [], None
    if os.path.exists(net):
        for name, rings in pickle.load(open(net, "rb")).get("parks", []):
            for ring in rings:
                if len(ring) >= 4:
                    poly = Polygon([m(*c) for c in ring]).buffer(0)
                    if not poly.is_empty:
                        parks.append((name, poly))
        ptree = STRtree([p for _, p in parks]) if parks else None
    places = []
    for kind, name, lon, lat in raw:
        if kind == "parking" and not name:
            if ptree is None:
                continue
            pt = Point(*m(lon, lat))
            hits = [parks[int(i)] for i in ptree.query(pt.buffer(PARK_NEAR_M))
                    if parks[int(i)][1].distance(pt) <= PARK_NEAR_M]
            if not hits:
                continue
            name = f"{hits[0][0]} lot"
        places.append([kind, name, lon, lat])
    pts = [Point(*m(p[2], p[3])) for p in places]
    print(f"  {len(places)} places to park for a run (trailheads, named lots, park lots)")
    return places, pts, STRtree(pts)


def is_loop(coords):
    (a, b), (c, d) = coords[0], coords[-1]
    return math.dist(m(a, b), m(c, d)) <= 150


def label(place):
    kind, name = place[0], place[1]
    if kind == "trailhead":
        return f"{name} trailhead" if name and "trailhead" not in name.lower() else (name or "Trailhead")
    return f"Parking: {name}"


def street_index():
    """Junctions with the street names that meet there, from the route network."""
    net = os.path.join(HERE, ".shade_cache", "network.pkl")
    d = pickle.load(open(net, "rb"))
    names = {}
    for u, v, length, hw, surface, name, coords in d["edges"]:
        if name and hw not in ("footway", "path", "track", "cycleway", "service", "bridleway"):
            names.setdefault(u, set()).add(name)
            names.setdefault(v, set()).add(name)
    ids = [n for n in names if n in d["nodes"]]
    pts = [Point(*m(*d["nodes"][n])) for n in ids]
    return ids, pts, STRtree(pts), names


def short_street(name):
    for a, b in ((" Boulevard", " Blvd"), (" Avenue", " Ave"), (" Street", " St"), (" Drive", " Dr"),
                 (" Road", " Rd"), (" Place", " Pl"), (" Terrace", " Ter"), (" Parkway", " Pkwy")):
        if name.endswith(a):
            return name[: -len(a)] + b
    return name


def start_street(coords, sidx, within=150):
    ids, pts, tree, names = sidx
    p = Point(*m(*coords[0]))
    best = None
    for i in tree.query(p.buffer(within)):
        n = ids[int(i)]
        if len(names[n]) >= 2:
            d = pts[int(i)].distance(p)
            if d <= within and (best is None or d < best[0]):
                best = (d, n)
    if not best:
        return None
    a, b = sorted(names[best[1]])[:2]
    return f"{short_street(a)} & {short_street(b)}"


def best_place(coords, index):
    """The trailhead / lot to park at for this route (or None), and how far it is from the line."""
    places, pts, tree = index
    line = LineString([m(*c) for c in coords])
    near = []
    for i in tree.query(line.buffer(NEAR_LINE_M)):
        d = pts[int(i)].distance(line)
        if d <= NEAR_LINE_M:
            p = places[int(i)]
            # trailheads first, then the closest lot
            near.append((0 if p[0] == "trailhead" else 1, d, int(i)))
    if not near:
        return None
    return places[min(near)[2]]


def wkt(coords):
    return "LINESTRING(" + ", ".join(f"{x:.7f} {y:.7f}" for x, y in coords) + ")"


def main():
    index = load_places()
    if "--cache" in sys.argv:
        rows = [(r["id"], r["nickname"] or r["name"], r["coords"])
                for r in pickle.load(open(CACHE, "rb")) if not r.get("hidden")]
    else:
        if "DATABASE_URL" not in os.environ:
            sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
        from sqlalchemy import create_engine, text
        engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
        with engine.begin() as conn:
            for col, typ in [("start_label", "VARCHAR"), ("park_lat", "FLOAT"), ("park_lon", "FLOAT"),
                             ("start_street", "VARCHAR")]:
                conn.execute(text(f"ALTER TABLE route ADD COLUMN IF NOT EXISTS {col} {typ}"))
        with engine.connect() as conn:
            raw = conn.execute(text("SELECT id, COALESCE(nickname, name), ST_AsText(gps_path) FROM route "
                                    "WHERE NOT COALESCE(hidden, FALSE)")).all()
        rows = [(rid, name, [tuple(map(float, p.split())) for p in w[w.index("(") + 1:-1].split(",")])
                for rid, name, w in raw if w and w.startswith("LINESTRING")]
    results = [(rid, name, coords, best_place(coords, index)) for rid, name, coords in rows]
    sidx = street_index()
    streets = {rid: start_street(coords, sidx) for rid, name, coords in rows}
    print(f"  nearest intersection found for {sum(1 for v in streets.values() if v)} of {len(rows)} starts, e.g. "
          + "; ".join([v for v in streets.values() if v][:4]))
    found = [r for r in results if r[3]]
    far = [r for r in found if math.dist(m(*r[2][0]), m(r[3][2], r[3][3])) > ALREADY_OK_M]
    print(f"\n{len(results)} routes: {len(found)} have a trailhead or lot on the route "
          f"({len(far)} of them don't start there yet: drive-to runs will now start at the lot); "
          f"{len(results) - len(found)} have street parking only.")
    for rid, name, coords, place in far[:15]:
        print(f"  {math.dist(m(*coords[0]), m(place[2], place[3])):5.0f} m from the old start  {name}  ->  {label(place)}")
    if "--dry-run" in sys.argv or "--cache" in sys.argv:
        print("\nNothing saved.")
        return
    with engine.begin() as conn:
        for rid, name, coords, place in results:
            conn.execute(text("UPDATE route SET start_label = :l, park_lat = :la, park_lon = :lo, "
                              "start_street = :s WHERE id = :id"),
                         {"l": label(place) if place else "Street parking", "la": place[3] if place else None,
                          "lo": place[2] if place else None, "s": streets.get(rid), "id": rid})
    print(f"\nSaved where to park for {len(results)} routes.")


if __name__ == "__main__":
    main()
