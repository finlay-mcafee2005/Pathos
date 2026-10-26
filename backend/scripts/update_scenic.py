"""
Decide which routes are "scenic" from what they actually pass, instead of the
old rule (every trail = scenic, road loops = scenic if near a famous anchor).

A route is scenic if at least 40% of it runs through or right beside parks,
nature areas, open hillsides or water (within 25 m; 40 m of a river or
stream) or under tree canopy (the route's shade_pct), or at least 20% does
and it passes a viewpoint, peak or waterfall (within 200 m), or it's a trail that
reaches one. Also saves
scenic_pct (0-1) for reference.

Tree canopy counts because OpenStreetMap often doesn't map wooded canyons
(e.g. Flint Canyon, Chantry Flat) as parks, and the national forest outline
is cut off at the edge of our map file.

First: python3 scripts/extract_scenic_osm.py   (already run once; makes scenic_local.json)
Run from backend/:
    DATABASE_URL=... python3 scripts/update_scenic.py --dry-run
    DATABASE_URL=... python3 scripts/update_scenic.py
"""
import json
import math
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from geoalchemy2.shape import to_shape
from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from app.models import Route

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")

if "DATABASE_URL" not in os.environ:
    sys.exit("DATABASE_URL isn't set, so this would use your local database. In this Terminal window, run:\n"
             '  export DATABASE_URL="<your Supabase link>"\nthen run this script again.')
DRY_RUN = "--dry-run" in sys.argv
DATA = os.path.join(os.path.dirname(__file__), ".shade_cache", "scenic_local.json")
SAMPLE_M = 30
NEAR_GREEN_M = 25
NEAR_WATER_M = 40
NEAR_VIEW_M = 200
SCENIC_SHARE = 0.40
SCENIC_SHARE_WITH_VIEW = 0.20
LAT0 = 34.15
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110540


def m(lon, lat):
    return lon * KX, lat * KY


def build_index():
    with open(DATA) as f:
        d = json.load(f)
    green = []
    for ring in d["areas"]:
        try:
            p = Polygon([m(*c) for c in ring])
            if not p.is_valid:
                p = p.buffer(0)
            if not p.is_empty:
                green.append(p)
        except Exception:
            pass
    water = [LineString([m(*c) for c in line]) for line in d["water"] if len(line) >= 2]
    views = [Point(*m(*c)) for c in d["points"]]
    return (STRtree(green), green), (STRtree(water), water), (STRtree(views), views)


def near(tree_geoms, pt, dist):
    tree, geoms = tree_geoms
    for i in tree.query(pt.buffer(dist)):
        if geoms[int(i)].distance(pt) <= dist:
            return True
    return False


def samples(coords):
    line = LineString([m(*c) for c in coords])
    if line.length == 0:
        return [Point(line.coords[0])]
    n = max(2, int(line.length // SAMPLE_M) + 1)
    return [line.interpolate(i * line.length / (n - 1)) for i in range(n)]


def main():
    if not os.path.exists(DATA):
        sys.exit("Run python3 scripts/extract_scenic_osm.py first.")
    print("Loading parks, water and viewpoints...")
    green, water, views = build_index()
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    # only add the column if it's missing (ALTER TABLE waits for every other open use of the
    # table, so it can time out while anything else is reading or saving routes)
    with engine.begin() as conn:
        has = conn.execute(text("SELECT 1 FROM information_schema.columns "
                                "WHERE table_name = 'route' AND column_name = 'scenic_pct'")).first()
        if not has:
            conn.execute(text("ALTER TABLE route ADD COLUMN scenic_pct FLOAT"))
    with Session(engine) as session:
        rows = session.exec(select(Route)).all()
        routes = [SimpleNamespace(id=r.id, name=r.nickname or r.name, old=bool(r.scenic),
                                  surface=r.surface_type, shade=getattr(r, "shade_pct", None) or 0.0,
                                  coords=list(to_shape(r.gps_path).coords)) for r in rows]
    print(f"{len(routes)} routes  (database: {DATABASE_URL.split('@')[-1].split('/')[0]})")

    results = []
    for i, r in enumerate(routes, 1):
        pts = samples(r.coords)
        nice = sum(1 for p in pts if near(green, p, NEAR_GREEN_M) or near(water, p, NEAR_WATER_M))
        share = max(nice / len(pts), r.shade)        # parks/water, or tree canopy
        view = any(near(views, p, NEAR_VIEW_M) for p in pts)
        # a trail that reaches a viewpoint or summit is scenic even through unmapped
        # open chaparral (e.g. San Gabriel Peak, Ken Burton)
        scenic = share >= SCENIC_SHARE or (view and (share >= SCENIC_SHARE_WITH_VIEW or (r.surface == "trail" and share >= 0.10)))
        results.append((r, round(share, 3), view, scenic))
        if i % 100 == 0:
            print(f"  {i}/{len(routes)}")

    gained = [t for t in results if t[3] and not t[0].old]
    lost = [t for t in results if not t[3] and t[0].old]
    by_surface = {}
    for r, share, view, sc in results:
        a = by_surface.setdefault(r.surface or "unknown", [0, 0])
        a[0] += sc
        a[1] += 1
    print(f"\nScenic before: {sum(r.old for r, *_ in results)} of {len(results)}   "
          f"after: {sum(t[3] for t in results)}")
    print("After, by surface: " + ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in sorted(by_surface.items())))
    print(f"\nNewly scenic ({len(gained)}), e.g.:")
    for r, share, view, _ in sorted(gained, key=lambda t: -t[1])[:12]:
        print(f"  {share:4.0%}{' +view' if view else '      '}  {r.name}")
    print(f"\nNo longer scenic ({len(lost)}), e.g.:")
    for r, share, view, _ in sorted(lost, key=lambda t: t[1])[:12]:
        print(f"  {share:4.0%}{' +view' if view else '      '}  {r.name} ({r.surface})")

    if DRY_RUN:
        print("\nDry run: nothing saved. Run without --dry-run to save.")
        return
    # save in batches, retrying if Supabase drops the connection (it does on long saves)
    import time
    rows = [{"id": r.id, "s": sc, "p": share} for r, share, view, sc in results]
    for k in range(0, len(rows), 200):
        for attempt in range(1, 5):
            try:
                with engine.begin() as conn:
                    conn.execute(text("UPDATE route SET scenic = :s, scenic_pct = :p WHERE id = :id"),
                                 rows[k:k + 200])
                break
            except Exception as ex:
                if attempt == 4:
                    raise
                print(f"  database connection dropped, retrying ({attempt}/3)...")
                engine.dispose()
                time.sleep(3)
    print(f"\nSaved scenic for {len(results)} routes.")


if __name__ == "__main__":
    main()
