"""
Pull tree / woodland data out of the local OpenStreetMap file (the same one OSRM
uses) so update_shade.py doesn't need the busy Overpass servers.

Run once from backend/ (takes a few minutes):
    python3 scripts/extract_shade_osm.py
Writes scripts/.shade_cache/osm_local.json, which update_shade.py uses automatically.
"""
import glob
import json
import os
import sys

import osmium

HERE = os.path.dirname(os.path.abspath(__file__))
PBF = (sys.argv[1] if len(sys.argv) > 1 else
       (glob.glob(os.path.join(HERE, "..", "..", "osrm-data", "*.osm.pbf")) or [None])[0])
OUT = os.path.join(HERE, ".shade_cache", "osm_local.json")
WOOD = lambda t: t.get("natural") == "wood" or t.get("landuse") == "forest"


class Grab(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.els = []

    def node(self, n):
        if n.tags.get("natural") == "tree" and n.location.valid():
            self.els.append({"type": "node", "lon": n.location.lon, "lat": n.location.lat,
                             "tags": {"natural": "tree"}})

    def way(self, w):
        t = w.tags
        if t.get("natural") == "tree_row":
            geom = [{"lon": nd.lon, "lat": nd.lat} for nd in w.nodes if nd.location.valid()]
            if len(geom) >= 2:
                self.els.append({"type": "way", "tags": {"natural": "tree_row"}, "geometry": geom})

    def area(self, a):
        # every wood/forest polygon, closed ways and multipolygon relations alike,
        # already assembled into proper rings by osmium
        if not WOOD(a.tags):
            return
        rings = []
        for outer in a.outer_rings():
            rings.append([{"lon": nd.lon, "lat": nd.lat} for nd in outer if nd.location.valid()])
        rings = [r for r in rings if len(r) >= 4]
        if rings:
            self.els.append({"type": "relation", "tags": {"natural": "wood"},
                             "members": [{"role": "outer", "geometry": r} for r in rings]})


if __name__ == "__main__":
    if not PBF or not os.path.exists(PBF):
        sys.exit("Couldn't find the .osm.pbf file in osrm-data/. Pass its path as an argument.")
    print(f"Reading {os.path.basename(PBF)} (a few minutes)...")
    h = Grab()
    h.apply_file(PBF, locations=True, idx="flex_mem")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump({"elements": h.els}, f)
    kinds = {}
    for e in h.els:
        kinds[e["type"]] = kinds.get(e["type"], 0) + 1
    print(f"Saved {len(h.els)} shapes ({kinds.get('node',0)} trees, {kinds.get('way',0)} tree rows, "
          f"{kinds.get('relation',0)} wooded areas) to {OUT}")
