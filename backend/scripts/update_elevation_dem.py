"""
Re-measure every route's climb from USGS 10 m elevation data (3DEP 1/3
arc-second), read straight from USGS's public cloud files, instead of the
old 20-points-per-route lookup on a ~100 m grid.

  - samples the path every 20 m (by distance, not by map vertex)
  - ignores bumps smaller than 3 m (DEM noise, overpasses), the usual way
    GPS watches avoid inflating climb
  - updates elevation_gain_m, elevation_loss_m and difficulty

First time only: pip3 install rasterio   (already done for the shade script)
Run from backend/:
    DATABASE_URL=... python3 scripts/update_elevation_dem.py --dry-run   # compare, save nothing
    DATABASE_URL=... python3 scripts/update_elevation_dem.py             # save
"""

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
from rasterio.warp import transform as warp_transform
from geoalchemy2.shape import to_shape
from shapely.geometry import LineString
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from app.models import Route
from app.scoring.difficulty import classify_difficulty

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")

if "DATABASE_URL" not in os.environ:
    sys.exit("DATABASE_URL isn't set, so this would use your local database. In this Terminal window, run:\n"
             '  export DATABASE_URL="<your Supabase link>"\nthen run this script again.')
DRY_RUN = "--dry-run" in sys.argv
STEP_M = 20                 # sample spacing along the path
NOISE_M = 3.0               # ignore ups/downs smaller than this
TILE_URL = ("https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/"
            "{name}/USGS_13_{name}.tif")


def tile_name(lon, lat):
    """USGS 1x1 degree tiles are named by their north-west corner, e.g. n35w119."""
    return f"n{math.floor(lat) + 1:02d}w{-math.floor(lon):03d}"


def is_loop(coords):
    (lon1, lat1), (lon2, lat2) = coords[0], coords[-1]
    return abs(lat1 - lat2) < 0.0015 and abs(lon1 - lon2) < 0.0018   # ~150 m (same as update_elevation.py)


def resample(coords):
    lat0 = sum(c[1] for c in coords) / len(coords)
    kx = 111320 * math.cos(math.radians(lat0))
    line = LineString([(lon * kx, lat * 110540) for lon, lat in coords])
    if line.length == 0:
        return [coords[0]]
    n = max(2, int(line.length // STEP_M) + 1)
    pts = [line.interpolate(i * line.length / (n - 1)) for i in range(n)]
    return [(p.x / kx, p.y / 110540) for p in pts]


def gain_loss(elev, threshold=NOISE_M):
    """Climb and descent, counting a change only once it exceeds `threshold`
    from the last turning point (hysteresis), so DEM noise doesn't add up."""
    gain = loss = 0.0
    if not elev:
        return gain, loss
    ref = elev[0]
    for e in elev[1:]:
        d = e - ref
        if d >= threshold:
            gain += d
            ref = e
        elif d <= -threshold:
            loss += -d
            ref = e
    return gain, loss


_open = {}


def dem(name):
    if name not in _open:
        _open[name] = rasterio.open("/vsicurl/" + TILE_URL.format(name=name))
    return _open[name]


def elevations(points):
    """Elevation (m) for each (lon, lat), grouped by USGS tile, one window read per tile."""
    out = [None] * len(points)
    by_tile = {}
    for i, (lon, lat) in enumerate(points):
        by_tile.setdefault(tile_name(lon, lat), []).append(i)
    for name, idx in by_tile.items():
        ds = dem(name)
        lons = [points[i][0] for i in idx]
        lats = [points[i][1] for i in idx]
        if ds.crs and not ds.crs.is_geographic:
            lons, lats = warp_transform("EPSG:4326", ds.crs, lons, lats)
        rows, cols = rasterio.transform.rowcol(ds.transform, lons, lats)
        rows, cols = np.array(rows), np.array(cols)
        r0, r1 = max(0, rows.min() - 1), min(ds.height, rows.max() + 2)
        c0, c1 = max(0, cols.min() - 1), min(ds.width, cols.max() + 2)
        arr = ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0), masked=True)
        for k, i in enumerate(idx):
            rr, cc = rows[k] - r0, cols[k] - c0
            if 0 <= rr < arr.shape[0] and 0 <= cc < arr.shape[1] and not np.ma.is_masked(arr[rr, cc]):
                out[i] = float(arr[rr, cc])
    return out


def main():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS elevation_loss_m FLOAT"))
    with Session(engine) as session:
        rows = session.exec(select(Route)).all()
        routes = [SimpleNamespace(id=r.id, name=r.nickname or r.name, distance_km=r.distance_km,
                                  coords=list(to_shape(r.gps_path).coords),
                                  old_gain=r.elevation_gain_m or 0.0, old_loss=r.elevation_loss_m,
                                  old_diff=r.difficulty) for r in rows]
    print(f"{len(routes)} routes  (database: {DATABASE_URL.split('@')[-1].split('/')[0]})")

    results, skipped = [], 0
    for i, r in enumerate(routes, 1):
        pts = resample(r.coords)
        try:
            elev = elevations(pts)
        except Exception as ex:
            print(f"  couldn't read elevation for {r.name}: {type(ex).__name__}: {ex}")
            skipped += 1
            continue
        good = [e for e in elev if e is not None]
        if len(good) < 0.9 * len(elev):
            skipped += 1
            continue
        gain, loss = gain_loss(good)
        if is_loop(r.coords):
            diff = classify_difficulty(r.distance_km, gain)
        else:                                  # point-to-point is run out-and-back
            diff = classify_difficulty(r.distance_km * 2, gain + loss)
        results.append((r, round(max(gain, 0.1), 1), round(loss, 1), diff))
        if i % 50 == 0:
            print(f"  {i}/{len(routes)} routes measured")

    def both_ways(g, l, d):
        return (g + (l if l is not None else g)) / 2 / d if d else 0
    changes = sorted(results, key=lambda t: -abs(both_ways(t[1], t[2], t[0].distance_km)
                                                 - both_ways(t[0].old_gain, t[0].old_loss, t[0].distance_km)))
    print("\nBiggest changes (climb per km, averaged both ways):")
    for r, g, l, d in changes[:15]:
        old = both_ways(r.old_gain, r.old_loss, r.distance_km)
        new = both_ways(g, l, r.distance_km)
        print(f"  {old:5.0f} -> {new:5.0f} m/km   {r.old_diff:>8} -> {d:<8}  {r.name}")
    flips = sum(1 for r, g, l, d in results if d != r.old_diff)
    print(f"\n{len(results)} measured, {skipped} skipped. Difficulty changes for {flips} routes.")

    if DRY_RUN:
        print("Dry run: nothing saved. Run without --dry-run to save.")
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE route SET elevation_gain_m = :g, elevation_loss_m = :l, difficulty = :d "
                          "WHERE id = :id"),
                     [{"id": r.id, "g": g, "l": l, "d": d} for r, g, l, d in results])
    print(f"Saved climb and difficulty for {len(results)} routes.")


if __name__ == "__main__":
    main()
