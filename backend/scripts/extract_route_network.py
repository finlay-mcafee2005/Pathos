"""
Step 1 of the park & path route generator: read the local OpenStreetMap file
and save a compact runnable network (paths + streets, split at junctions),
plus named parks, running tracks, schools and neighbourhood names.

Run from backend/ (1-2 minutes, needs `pip3 install osmium`):
    python3 scripts/extract_route_network.py
Writes scripts/.shade_cache/network.pkl, used by generate_park_routes.py
"""
import glob
import math
import os
import pickle
import sys
from collections import Counter

import osmium

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from osm_surface import classify_surface  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PBF = (sys.argv[1] if len(sys.argv) > 1 else
       (glob.glob(os.path.join(HERE, "..", "..", "osrm-data", "*.osm.pbf")) or [None])[0])
OUT = os.path.join(HERE, ".shade_cache", "network.pkl")

CENTER_LAT, CENTER_LON = 34.15, -118.22      # same area as the other generators
RADIUS_KM = 18
RUN_WAYS = {
    # highway: cost multiplier (lower = preferred when building loops)
    "footway": 1.0, "path": 1.0, "track": 1.0, "cycleway": 1.0, "pedestrian": 1.0, "bridleway": 1.0,
    "living_street": 1.6, "residential": 1.8, "service": 1.8, "unclassified": 1.9,
    "tertiary": 2.3, "secondary": 3.0,
}
PARK_TAGS = {("leisure", "park"), ("leisure", "nature_reserve"), ("leisure", "garden"),
             ("boundary", "protected_area")}


def km_from_center(lon, lat):
    dx = (lon - CENTER_LON) * 111.32 * math.cos(math.radians(CENTER_LAT))
    dy = (lat - CENTER_LAT) * 110.54
    return math.hypot(dx, dy)


def runnable(tags):
    hw = tags.get("highway")
    if hw not in RUN_WAYS:
        return False
    if tags.get("access") in ("private", "no") or tags.get("foot") in ("no", "private"):
        return False
    if tags.get("footway") == "crossing" or tags.get("area") == "yes":
        return False
    return True


class CountRefs(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.uses = Counter()

    def way(self, w):
        if runnable(w.tags):
            refs = [n.ref for n in w.nodes]
            for r in refs:
                self.uses[r] += 1
            if refs:                       # ends always count as junctions
                self.uses[refs[0]] += 1
                self.uses[refs[-1]] += 1


class Build(osmium.SimpleHandler):
    def __init__(self, uses):
        super().__init__()
        self.uses = uses
        self.nodes = {}            # junction id -> (lon, lat)
        self.edges = []            # (u, v, length_m, highway, surface, name, coords)
        self.parks = []            # (name, [rings of (lon, lat)])
        self.tracks = []           # [(lon, lat)...] closed running tracks
        self.schools = []          # (name, lon, lat)
        self.places = []           # (name, lon, lat) neighbourhoods/suburbs

    def node(self, n):
        t = n.tags
        if t.get("place") in ("neighbourhood", "suburb", "quarter") and t.get("name") and n.location.valid():
            if km_from_center(n.location.lon, n.location.lat) <= RADIUS_KM + 3:
                self.places.append((t["name"], n.location.lon, n.location.lat))

    def way(self, w):
        t = w.tags
        if runnable(t):
            pts = [(nd.ref, nd.lon, nd.lat) for nd in w.nodes if nd.location.valid()]
            if len(pts) < 2:
                return
            if all(km_from_center(lon, lat) > RADIUS_KM for _, lon, lat in pts):
                return
            hw = t.get("highway")
            surface = classify_surface(hw, t.get("surface"), t.get("footway"))
            if hw not in ("footway", "path", "track", "bridleway") and t.get("surface") is None:
                surface = "pavement"       # streets/cycleways without a tag are paved
            name = t.get("name")
            seg = [pts[0]]
            for p in pts[1:]:
                seg.append(p)
                if self.uses[p[0]] >= 2 or p is pts[-1]:
                    coords = [(lon, lat) for _, lon, lat in seg]
                    length = sum(hav(*coords[i], *coords[i + 1]) for i in range(len(coords) - 1))
                    if length > 0:
                        u, v = seg[0][0], seg[-1][0]
                        self.nodes[u] = coords[0]
                        self.nodes[v] = coords[-1]
                        self.edges.append((u, v, length, hw, surface, name, coords))
                    seg = [p]
        if t.get("leisure") == "track" and t.get("sport", "").find("running") >= 0 or \
                (t.get("leisure") == "track" and t.get("sport") in ("athletics", "running")):
            ring = [(nd.lon, nd.lat) for nd in w.nodes if nd.location.valid()]
            if len(ring) >= 4 and km_from_center(*ring[0]) <= RADIUS_KM:
                self.tracks.append(ring)

    def area(self, a):
        t = a.tags
        name = t.get("name")
        if t.get("amenity") in ("school", "college", "university") and name:
            try:
                ring = [(nd.lon, nd.lat) for nd in next(iter(a.outer_rings()))]
                lon = sum(p[0] for p in ring) / len(ring)
                lat = sum(p[1] for p in ring) / len(ring)
                self.schools.append((name, lon, lat))
            except StopIteration:
                pass
        if name and any(t.get(k) == v for k, v in PARK_TAGS):
            rings = []
            for outer in a.outer_rings():
                ring = [(nd.lon, nd.lat) for nd in outer if nd.location.valid()]
                if len(ring) >= 4:
                    rings.append(ring)
            if rings and any(km_from_center(*r[0]) <= RADIUS_KM + 2 for r in rings):
                self.parks.append((name, rings))


def hav(lon1, lat1, lon2, lat2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


if __name__ == "__main__":
    if not PBF:
        sys.exit("No .osm.pbf file found in osrm-data/.")
    print("Pass 1: counting junctions...")
    c = CountRefs()
    c.apply_file(PBF)
    print("Pass 2: building the network, parks and tracks...")
    b = Build(c.uses)
    b.apply_file(PBF, locations=True, idx="flex_mem")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        pickle.dump({"nodes": b.nodes, "edges": b.edges, "parks": b.parks, "tracks": b.tracks,
                     "schools": b.schools, "places": b.places}, f)
    print(f"Saved {len(b.nodes)} junctions, {len(b.edges)} segments, {len(b.parks)} named parks, "
          f"{len(b.tracks)} running tracks, {len(b.schools)} schools, {len(b.places)} neighbourhoods")
