"""
Shade score for every route from a satellite tree-canopy height map
(Meta / WRI Global Canopy Height v2, ~1 m pixels, CC BY 4.0), instead of the
patchy OpenStreetMap tree data. Covers every street, park and canyon.

For points every 30 m along a route, we check whether trees at least 4 m tall
cover a quarter or more of the ground within ~4 m of the path. shade_pct = share of points that are.

First time only, on your Mac:
    pip3 install rasterio duckdb
Run from backend/:
    DATABASE_URL=... python3 scripts/update_shade_canopy.py --dry-run   # preview
    DATABASE_URL=... python3 scripts/update_shade_canopy.py             # save

Data: Tolan et al. 2024 / Brandt et al. 2026, via source.coop (tge-labs/meta-chm-v2).
Only the small pieces of the map near routes are downloaded (and cached by GDAL).
"""

import json
import math
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.tiff")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "5")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
os.environ.setdefault("GDAL_CACHEMAX", "512")
os.environ.setdefault("VSI_CACHE", "TRUE")

import numpy as np
import rasterio
from rasterio.windows import Window
from geoalchemy2.shape import to_shape
from shapely.geometry import LineString
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from app.models import Route

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")
DRY_RUN = "--dry-run" in sys.argv

TILES_INDEX = "https://data.source.coop/tge-labs/meta-chm-v2/tiles.parquet"
TILE_ZOOM = 10                 # the map is split into zoom-10 web map tiles
SAMPLE_M = 30                  # check a point every 30 m
NEAR_M = 4                     # look within 4 m of the path (trees right beside it)
MIN_TREE_M = 4                 # taller than 4 m = a tree (LA chaparral can reach 2-3 m)
MIN_COVER = 0.25               # ...covering at least a quarter of that patch, not one stray pixel
URL_CACHE = os.path.join(os.path.dirname(__file__), ".shade_cache", "canopy_tiles.json")
R = 6378137.0


def merc(lon, lat):
    return (R * math.radians(lon),
            R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def quadkey(lon, lat, z=TILE_ZOOM):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    s = math.sin(math.radians(lat))
    y = int((0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n)
    qk = ""
    for i in range(z, 0, -1):
        d, mask = 0, 1 << (i - 1)
        if x & mask:
            d += 1
        if y & mask:
            d += 2
        qk += str(d)
    return qk


def tile_urls(keys):
    """quadkey -> COG url, from the dataset's tile index (cached locally)."""
    cache = {}
    if os.path.exists(URL_CACHE):
        with open(URL_CACHE) as f:
            cache = json.load(f)
    missing = [k for k in keys if k not in cache]
    if missing:
        import duckdb
        print(f"Looking up {len(missing)} map tiles in the canopy index...")
        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs;")
        rows = con.execute(
            f"SELECT lpad(CAST(quadkey AS VARCHAR), {TILE_ZOOM}, '0') AS qk, cog_url "
            f"FROM read_parquet('{TILES_INDEX}') WHERE lpad(CAST(quadkey AS VARCHAR), {TILE_ZOOM}, '0') IN ("
            + ",".join("?" * len(missing)) + ")", missing).fetchall()
        for qk, url in rows:
            cache[str(qk)] = url
        for k in missing:
            cache.setdefault(k, None)         # no canopy tile there (e.g. ocean)
        os.makedirs(os.path.dirname(URL_CACHE), exist_ok=True)
        with open(URL_CACHE, "w") as f:
            json.dump(cache, f)
    return {k: cache.get(k) for k in keys}


def to_gdal(url):
    """Read over plain HTTPS (no AWS account needed)."""
    if url.startswith("s3://"):
        bucket, _, key = url[5:].partition("/")
        if bucket == "us-west-2.opendata.source.coop":
            url = f"https://data.source.coop/{key}"
        else:
            url = f"https://{bucket}.s3.amazonaws.com/{key}"
    return "/vsicurl/" + url


_open = {}


def dataset(url):
    if url not in _open:
        _open[url] = rasterio.open(to_gdal(url))
    return _open[url]


def sample_points(coords):
    """Points every SAMPLE_M along the route, as (lon, lat)."""
    lat0 = sum(c[1] for c in coords) / len(coords)
    kx = 111320 * math.cos(math.radians(lat0))
    line = LineString([(lon * kx, lat * 110540) for lon, lat in coords])
    if line.length == 0:
        return [coords[0]]
    n = max(2, int(line.length // SAMPLE_M) + 1)
    pts = [line.interpolate(i * line.length / (n - 1)) for i in range(n)]
    return [(p.x / kx, p.y / 110540) for p in pts]


def shaded_flags(points, ds):
    """True/False per point: does tree canopy cover a real share of the ground around it?"""
    xs, ys = zip(*(merc(lon, lat) for lon, lat in points))
    px = abs(ds.transform.a)
    lat_c = sum(p[1] for p in points) / len(points)
    r = max(1, math.ceil(NEAR_M / (px * math.cos(math.radians(lat_c)))))   # ground metres -> pixels
    rows, cols = rasterio.transform.rowcol(ds.transform, xs, ys)
    rows, cols = np.array(rows), np.array(cols)
    r0, r1 = max(0, rows.min() - r), min(ds.height, rows.max() + r + 1)
    c0, c1 = max(0, cols.min() - r), min(ds.width, cols.max() + r + 1)
    if r1 <= r0 or c1 <= c0:
        return [False] * len(points)
    if (r1 - r0) * (c1 - c0) <= 40_000_000:       # one read for the whole route
        arr = ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0))
        get = lambda rr, cc: arr[max(0, rr - r - r0):rr + r + 1 - r0, max(0, cc - r - c0):cc + r + 1 - c0]
    else:                                          # very spread out: read around each point
        get = lambda rr, cc: ds.read(1, window=Window(cc - r, rr - r, 2 * r + 1, 2 * r + 1), boundless=True, fill_value=0)
    out = []
    for rr, cc in zip(rows, cols):
        if not (0 <= rr < ds.height and 0 <= cc < ds.width):
            out.append(False)
            continue
        win = get(int(rr), int(cc))
        out.append(bool(win.size and (win >= MIN_TREE_M).mean() >= MIN_COVER))
    return out


def main():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS shade_pct FLOAT"))
    with Session(engine) as session:
        rows = session.exec(select(Route).where(Route.hidden.is_not(True))).all()
        routes = [SimpleNamespace(id=r.id, name=r.nickname or r.name,
                                  coords=list(to_shape(r.gps_path).coords)) for r in rows]
    # database connection closed; the map reads below can take a while
    print(f"{len(routes)} routes  (database: {DATABASE_URL.split('@')[-1].split('/')[0]})")

    samples = {r.id: sample_points(r.coords) for r in routes}
    keys = sorted({quadkey(lon, lat) for pts in samples.values() for lon, lat in pts})
    urls = tile_urls(keys)
    print(f"{len(keys)} canopy map tiles cover the routes ({sum(1 for u in urls.values() if u)} available)")

    results, skipped = [], 0
    for i, r in enumerate(routes, 1):
        pts = samples[r.id]
        by_tile = {}
        for p in pts:
            by_tile.setdefault(quadkey(*p), []).append(p)
        shaded = known = 0
        try:
            for qk, tp in by_tile.items():
                if not urls.get(qk):
                    continue
                flags = shaded_flags(tp, dataset(urls[qk]))
                shaded += sum(flags)
                known += len(flags)
        except Exception as ex:
            print(f"  couldn't read the map for {r.name}: {type(ex).__name__}: {ex}")
            skipped += 1
            continue
        if known < 0.8 * len(pts):
            skipped += 1
            continue
        results.append((r, round(shaded / known, 3)))
        if i % 50 == 0:
            print(f"  {i}/{len(routes)} routes done")

    if skipped:
        print(f"\n{skipped} routes skipped (map unavailable). Run again later to fill them in.")
    if not results:
        print("Nothing to save.")
        return
    results.sort(key=lambda t: -t[1])
    print("\nMost shaded:")
    for r, pct in results[:12]:
        print(f"  {pct:5.0%}  {r.name}")
    print("\nLeast shaded:")
    for r, pct in results[-5:]:
        print(f"  {pct:5.0%}  {r.name}")
    avg = sum(p for _, p in results) / len(results)
    print(f"\nAverage shade: {avg:.0%}.  Routes 35%+ shaded: {sum(1 for _, p in results if p >= 0.35)} of {len(results)}")

    if DRY_RUN:
        print("\nDry run: nothing saved. Run without --dry-run to save.")
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE route SET shade_pct = :pct WHERE id = :id"),
                     [{"id": r.id, "pct": pct} for r, pct in results])
    print(f"\nSaved shade for {len(results)} routes.")


if __name__ == "__main__":
    main()
