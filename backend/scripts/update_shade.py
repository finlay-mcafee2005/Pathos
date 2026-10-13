"""
Estimates how shaded each route is, from OpenStreetMap tree data, and saves
it as route.shade_pct (0 to 1). On hot days the recommender favors shady
routes and goes easier on their heat penalty.

How: for each map tile that has routes, download woods, forests, tree rows
and individual trees from the Overpass API, then sample each route every
~30 m and count the share of points that are under or right next to trees.

OSM tree data in LA is decent in parks and canyons but thin on streets
(street trees are rarely mapped), so treat road routes' shade as a floor.

Run from backend/:
    python3 scripts/update_shade.py --dry-run      # compute and print, save nothing
    python3 scripts/update_shade.py                # save to the database
    DATABASE_URL=... python3 scripts/update_shade.py   # live database

Downloads are cached in scripts/.shade_cache/, so re-runs are fast.
"""

import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from geoalchemy2.shape import to_shape
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from app.models import Route

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".shade_cache")
TILE_DEG = 0.04            # ~4 km tiles
PAD_DEG = 0.004            # a little margin around each tile
SAMPLE_M = 30              # check a point every 30 m along the route
NEAR_WOOD_M = 12           # counts as shaded within this distance of a wood/forest
TREE_RADIUS_M = 7          # canopy radius around a mapped single tree
TREE_ROW_M = 8             # half-width of a mapped row of trees
DRY_RUN = "--dry-run" in sys.argv

QUERY = """[out:json][timeout:90];
(
  way["natural"="wood"]({b});
  way["landuse"="forest"]({b});
  relation["natural"="wood"]({b});
  relation["landuse"="forest"]({b});
  way["natural"="tree_row"]({b});
  node["natural"="tree"]({b});
);
out geom;"""


def to_m(lon, lat, lat0):
    """Small-area projection to metres (good enough at city scale)."""
    return lon * 111320 * math.cos(math.radians(lat0)), lat * 110540


def fetch_tile(s, w, n, e):
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = os.path.join(CACHE_DIR, f"{s:.3f}_{w:.3f}.json")
    if os.path.exists(key):
        with open(key) as f:
            return json.load(f)
    q = QUERY.replace("{b}", f"{s},{w},{n},{e}")
    for attempt in range(6):
        try:
            r = httpx.post(OVERPASS_URL, data={"data": q}, timeout=120,
                           headers={"User-Agent": "Pathos/1.0 (student running-route project)"})
            if r.status_code in (429, 502, 503, 504):
                wait = 10 * (attempt + 1)
                print(f"    Overpass busy ({r.status_code}), waiting {wait}s")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            with open(key, "w") as f:
                json.dump(data, f)
            time.sleep(2)            # be polite to the free server
            return data
        except httpx.HTTPError as ex:
            print(f"    network error: {ex}; retrying")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("Overpass kept failing; try again later (cached tiles are kept).")


def shade_shapes(data, lat0):
    shapes = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        try:
            if el["type"] == "node":
                x, y = to_m(el["lon"], el["lat"], lat0)
                shapes.append(Point(x, y).buffer(TREE_RADIUS_M))
            elif el["type"] == "way" and "geometry" in el:
                pts = [to_m(p["lon"], p["lat"], lat0) for p in el["geometry"]]
                if tags.get("natural") == "tree_row":
                    if len(pts) >= 2:
                        shapes.append(LineString(pts).buffer(TREE_ROW_M))
                elif len(pts) >= 4:
                    shapes.append(Polygon(pts).buffer(NEAR_WOOD_M))
            elif el["type"] == "relation":
                for m in el.get("members", []):
                    if m.get("role") == "outer" and m.get("geometry") and len(m["geometry"]) >= 4:
                        pts = [to_m(p["lon"], p["lat"], lat0) for p in m["geometry"]]
                        shapes.append(Polygon(pts).buffer(NEAR_WOOD_M))
        except Exception:
            continue             # skip broken geometry
    return [g for g in shapes if g.is_valid and not g.is_empty]


def sample_line(coords_m, step):
    line = LineString(coords_m)
    if line.length == 0:
        return [Point(coords_m[0])]
    n = max(2, int(line.length // step) + 1)
    return [line.interpolate(i * line.length / (n - 1)) for i in range(n)]


def main():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS shade_pct FLOAT"))

    with Session(engine) as session:
        routes = session.exec(select(Route).where(Route.hidden.is_not(True))).all()
        paths = {r.id: list(to_shape(r.gps_path).coords) for r in routes}
        all_lat = [lat for c in paths.values() for _, lat in c]
        lat0 = sum(all_lat) / len(all_lat)

        # which tiles do the routes touch?
        tiles = {}
        for r in routes:
            for lon, lat in paths[r.id]:
                tiles.setdefault((math.floor(lat / TILE_DEG), math.floor(lon / TILE_DEG)), set()).add(r.id)
        print(f"{len(routes)} routes across {len(tiles)} map tiles")

        # shade geometry per tile
        tree_index = {}
        for i, (ty, tx) in enumerate(sorted(tiles), 1):
            s, w = ty * TILE_DEG - PAD_DEG, tx * TILE_DEG - PAD_DEG
            n, e = (ty + 1) * TILE_DEG + PAD_DEG, (tx + 1) * TILE_DEG + PAD_DEG
            print(f"  tile {i}/{len(tiles)}  ({s:.3f},{w:.3f})")
            shapes = shade_shapes(fetch_tile(s, w, n, e), lat0)
            tree_index[(ty, tx)] = prep(unary_union(shapes)) if shapes else None

        results = []
        for r in routes:
            coords_m = [to_m(lon, lat, lat0) for lon, lat in paths[r.id]]
            pts = sample_line(coords_m, SAMPLE_M)
            shaded = 0
            # look each sample point up in the tile it falls in
            for p in pts:
                lon = p.x / (111320 * math.cos(math.radians(lat0)))
                lat = p.y / 110540
                idx = tree_index.get((math.floor(lat / TILE_DEG), math.floor(lon / TILE_DEG)))
                if idx is not None and idx.covers(p):
                    shaded += 1
            pct = round(shaded / len(pts), 3)
            results.append((r, pct))

        results.sort(key=lambda t: -t[1])
        print("\nMost shaded:")
        for r, pct in results[:10]:
            print(f"  {pct:5.0%}  {r.nickname or r.name}")
        avg = sum(p for _, p in results) / len(results)
        print(f"\nAverage shade: {avg:.0%}.  Routes 35%+ shaded: {sum(1 for _, p in results if p >= 0.35)}")

        if DRY_RUN:
            print("\nDry run: nothing saved. Run without --dry-run to save.")
            return
        for r, pct in results:
            r.shade_pct = pct
            session.add(r)
        session.commit()
        print(f"\nSaved shade for {len(results)} routes.")


if __name__ == "__main__":
    main()
