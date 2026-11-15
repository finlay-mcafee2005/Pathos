"""
Save an elevation profile for every route, for the "where are the climbs" chart on each
card (DJ, Maurice and Eduardo asked to see the climbs, not just a total).

Samples each path every 40 m from the same USGS 10 m elevation data the climb numbers
come from (update_elevation_dem.py), and stores the points with their elevation:

  elev_samples   JSON [[lon * 1e5, lat * 1e5, metres], ...] along the route, in order

Storing positions (not just a list of heights) lets the app build the profile for the run
as it's actually drawn: started at the parking spot, run out-and-back, or joined to
another route.

Needs rasterio (already installed for update_elevation_dem.py). Run from backend/:
    DATABASE_URL=... python3 scripts/update_elevation_profile.py --dry-run
    DATABASE_URL=... python3 scripts/update_elevation_profile.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import update_elevation_dem as dem      # noqa: E402  (exits early if DATABASE_URL isn't set)

from sqlalchemy import text            # noqa: E402
from sqlmodel import create_engine     # noqa: E402

EVERY = 2                              # dem.resample spaces points 20 m apart: keep every 2nd = 40 m


def fill_gaps(elev):
    """Fill missing readings by linear interpolation between the nearest known ones."""
    known = [i for i, e in enumerate(elev) if e is not None]
    if not known:
        return None
    out = list(elev)
    for i in range(len(out)):
        if out[i] is None:
            lo = max((k for k in known if k < i), default=None)
            hi = min((k for k in known if k > i), default=None)
            if lo is None:
                out[i] = out[hi]
            elif hi is None:
                out[i] = out[lo]
            else:
                out[i] = out[lo] + (out[hi] - out[lo]) * (i - lo) / (hi - lo)
    return out


def main():
    engine = create_engine(dem.DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS elev_samples TEXT"))
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, COALESCE(nickname, name), ST_AsText(gps_path) FROM route "
                                 "WHERE NOT COALESCE(hidden, FALSE)")).all()
    print(f"{len(rows)} routes")
    saved, skipped = [], 0
    for k, (rid, name, wkt) in enumerate(rows, 1):
        if not wkt or not wkt.startswith("LINESTRING"):
            skipped += 1
            continue
        coords = [tuple(map(float, p.split())) for p in wkt[wkt.index("(") + 1:-1].split(",")]
        pts = dem.resample(coords)[::EVERY]
        if len(pts) < 2:
            skipped += 1
            continue
        try:
            elev = dem.elevations(pts)
        except Exception as ex:
            print(f"  couldn't read elevation for {name}: {type(ex).__name__}: {ex}")
            skipped += 1
            continue
        if sum(e is None for e in elev) > 0.1 * len(elev):
            skipped += 1
            continue
        elev = fill_gaps(elev)
        saved.append((rid, json.dumps([[round(lon * 1e5), round(lat * 1e5), round(e, 1)]
                                       for (lon, lat), e in zip(pts, elev)], separators=(",", ":"))))
        if k % 100 == 0:
            print(f"  {k}/{len(rows)} routes")
    size = sum(len(s) for _, s in saved)
    print(f"\n{len(saved)} profiles ({size / 1e6:.1f} MB in all), {skipped} skipped.")
    if "--dry-run" in sys.argv:
        print("Dry run: nothing saved.")
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE route SET elev_samples = :s WHERE id = :id"),
                     [{"id": rid, "s": s} for rid, s in saved])
    print(f"Saved elevation profiles for {len(saved)} routes.")


if __name__ == "__main__":
    main()
