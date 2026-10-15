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
from types import SimpleNamespace
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
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".shade_cache")
TILE_DEG = 0.04            # ~4 km tiles
PAD_DEG = 0.004            # a little margin around each tile
SAMPLE_M = 30              # check a point every 30 m along the route
NEAR_WOOD_M = 12           # counts as shaded within this distance of a wood/forest
TREE_RADIUS_M = 7          # canopy radius around a mapped single tree
TREE_ROW_M = 8             # half-width of a mapped row of trees
MAX_WOOD_M2 = 1_000_000    # ignore wood/forest areas over 1 km²: in the LA mountains these are
                           # broad "forest" labels over open chaparral, not real canopy
DRY_RUN = "--dry-run" in sys.argv

QUERY = """[out:json][timeout:60];
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


OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def _download(s, w, n, e):
    """One bbox from Overpass, trying each mirror in turn. None if all are busy."""
    q = QUERY.replace("{b}", f"{s},{w},{n},{e}")
    for attempt in range(len(OVERPASS_MIRRORS)):
        url = OVERPASS_MIRRORS[attempt % len(OVERPASS_MIRRORS)]
        try:
            r = httpx.post(url, data={"data": q}, timeout=httpx.Timeout(60, connect=15),
                           headers={"User-Agent": "Pathos/1.0 (student running-route project)"})
            if r.status_code in (429, 502, 503, 504):
                print(f"    {url.split('/')[2]} busy ({r.status_code}), trying another server")
                time.sleep(4 + 3 * attempt)
                continue
            r.raise_for_status()
            time.sleep(1.5)                   # be polite to the free servers
            return r.json()
        except (httpx.HTTPError, ValueError) as ex:
            print(f"    {url.split('/')[2]} error ({type(ex).__name__}), trying another server")
            time.sleep(4 + 3 * attempt)
    return None


def fetch_tile(s, w, n, e, depth=0):
    """OSM tree data for a tile (cached). A tile that keeps timing out is split
    into 4 smaller ones. Returns None if it still can't be downloaded."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = os.path.join(CACHE_DIR, f"{s:.4f}_{w:.4f}_{n:.4f}_{e:.4f}.json")
    if os.path.exists(key):
        with open(key) as f:
            return json.load(f)
    data = _download(s, w, n, e)
    if data is None and depth < 1:
        print(f"    splitting this tile into 4 smaller pieces")
        mid_lat, mid_lon = (s + n) / 2, (w + e) / 2
        parts = [fetch_tile(a, b, c, d, depth + 1) for a, b, c, d in (
            (s, w, mid_lat, mid_lon), (s, mid_lon, mid_lat, e),
            (mid_lat, w, n, mid_lon), (mid_lat, mid_lon, n, e))]
        if any(p is None for p in parts):
            return None
        data = {"elements": [el for p in parts for el in p.get("elements", [])]}
    if data is not None:
        with open(key, "w") as f:
            json.dump(data, f)
    return data


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
                    poly = Polygon(pts)
                    if poly.area <= MAX_WOOD_M2:
                        shapes.append(poly.buffer(NEAR_WOOD_M))
            elif el["type"] == "relation":
                for m in el.get("members", []):
                    if m.get("role") == "outer" and m.get("geometry") and len(m["geometry"]) >= 4:
                        pts = [to_m(p["lon"], p["lat"], lat0) for p in m["geometry"]]
                        poly = Polygon(pts)
                        if poly.area <= MAX_WOOD_M2:
                            shapes.append(poly.buffer(NEAR_WOOD_M))
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
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS shade_pct FLOAT"))

    with Session(engine) as session:
        rows = session.exec(select(Route).where(Route.hidden.is_not(True))).all()
        routes = [SimpleNamespace(id=r.id, name=r.name, nickname=r.nickname) for r in rows]
        paths = {r.id: list(to_shape(r.gps_path).coords) for r in rows}
    # connection is closed now; the downloads below can take a long time
    if True:
        all_lat = [lat for c in paths.values() for _, lat in c]
        lat0 = sum(all_lat) / len(all_lat)

        # which tiles do the routes touch?
        tiles = {}
        route_tiles = {}
        for r in routes:
            for lon, lat in paths[r.id]:
                t = (math.floor(lat / TILE_DEG), math.floor(lon / TILE_DEG))
                tiles.setdefault(t, set()).add(r.id)
                route_tiles.setdefault(r.id, set()).add(t)
        print(f"{len(routes)} routes across {len(tiles)} map tiles  (database: {DATABASE_URL.split('@')[-1].split('/')[0]})")

        # shade geometry per tile
        tree_index = {}
        failed = set()
        for i, (ty, tx) in enumerate(sorted(tiles), 1):
            s, w = ty * TILE_DEG - PAD_DEG, tx * TILE_DEG - PAD_DEG
            n, e = (ty + 1) * TILE_DEG + PAD_DEG, (tx + 1) * TILE_DEG + PAD_DEG
            print(f"  tile {i}/{len(tiles)}  ({s:.3f},{w:.3f})")
            data = fetch_tile(s, w, n, e)
            if data is None:
                print("    couldn't download this tile; its routes are skipped this run (re-run later)")
                failed.add((ty, tx))
                continue
            shapes = shade_shapes(data, lat0)
            tree_index[(ty, tx)] = prep(unary_union(shapes)) if shapes else None

        results = []
        skipped = 0
        for r in routes:
            if failed and any(t in failed for t in route_tiles[r.id]):
                skipped += 1
                continue
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

        if skipped:
            print(f"\n{skipped} routes skipped because a map tile couldn't be downloaded. "
                  f"Run the script again later: finished tiles are cached.")
        if not results:
            print("Nothing to save yet.")
            return
        results.sort(key=lambda t: -t[1])
        print("\nMost shaded:")
        for r, pct in results[:10]:
            print(f"  {pct:5.0%}  {r.nickname or r.name}")
        avg = sum(p for _, p in results) / len(results)
        print(f"\nAverage shade: {avg:.0%}.  Routes 35%+ shaded: {sum(1 for _, p in results if p >= 0.35)}")

        if DRY_RUN:
            print("\nDry run: nothing saved. Run without --dry-run to save.")
            return
        with engine.begin() as conn:
            conn.execute(text("UPDATE route SET shade_pct = :pct WHERE id = :id"),
                         [{"id": r.id, "pct": pct} for r, pct in results])
        print(f"\nSaved shade for {len(results)} routes.")


if __name__ == "__main__":
    main()
