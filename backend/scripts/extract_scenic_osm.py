"""
Pull "nice places to run" out of the local OpenStreetMap file: parks, nature
areas, water, open hillsides, and viewpoints/peaks. update_scenic.py uses it.

Run once from backend/ (about a minute; needs `pip3 install osmium`):
    python3 scripts/extract_scenic_osm.py
Writes scripts/.shade_cache/scenic_local.json
"""
import glob
import json
import os
import sys

import osmium

HERE = os.path.dirname(os.path.abspath(__file__))
PBF = (sys.argv[1] if len(sys.argv) > 1 else
       (glob.glob(os.path.join(HERE, "..", "..", "osrm-data", "*.osm.pbf")) or [None])[0])
OUT = os.path.join(HERE, ".shade_cache", "scenic_local.json")

GREEN = {
    "leisure": {"park", "nature_reserve", "garden", "golf_course"},
    "landuse": {"forest", "meadow", "recreation_ground", "reservoir", "basin"},
    "natural": {"wood", "scrub", "heath", "grassland", "water", "wetland", "beach", "cliff", "bare_rock"},
    "boundary": {"national_park", "protected_area"},
}
WATER_LINES = {"river", "stream", "canal"}
POINTS = {("tourism", "viewpoint"), ("natural", "peak"), ("natural", "waterfall")}


def is_green(tags):
    return any(tags.get(k) in v for k, v in GREEN.items())


class Grab(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.areas, self.lines, self.points = [], [], []

    def node(self, n):
        if n.location.valid() and any(n.tags.get(k) == v for k, v in POINTS):
            self.points.append([n.location.lon, n.location.lat])

    def way(self, w):
        if w.tags.get("waterway") in WATER_LINES:
            g = [[nd.lon, nd.lat] for nd in w.nodes if nd.location.valid()]
            if len(g) >= 2:
                self.lines.append(g)

    def area(self, a):
        if not is_green(a.tags):
            return
        for outer in a.outer_rings():
            ring = [[nd.lon, nd.lat] for nd in outer if nd.location.valid()]
            if len(ring) >= 4:
                self.areas.append(ring)


if __name__ == "__main__":
    if not PBF or not os.path.exists(PBF):
        sys.exit("Couldn't find the .osm.pbf file in osrm-data/.")
    h = Grab()
    h.apply_file(PBF, locations=True, idx="flex_mem")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"areas": h.areas, "water": h.lines, "points": h.points}, f)
    print(f"Saved {len(h.areas)} green/water areas, {len(h.lines)} streams/rivers, "
          f"{len(h.points)} viewpoints/peaks to {OUT}")
