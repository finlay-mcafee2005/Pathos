"""
Find routes that are basically the same run (same path, within ~15% of the
same length, maybe reversed or with a different name), so the catalog isn't
padded with look-alikes that crowd out variety.

Two routes are duplicates if at least 85% of each one runs within 30 m of
the other and their lengths are within 15%. In each group we keep one
(prefer: loop over out-and-back, then the most-recommended, then shortest name)
and hide the rest (route.hidden = true; nothing is deleted, and hidden routes
can be un-hidden in the database).

Run from backend/:
    DATABASE_URL=... python3 scripts/find_duplicate_routes.py          # report only
    DATABASE_URL=... python3 scripts/find_duplicate_routes.py --hide   # hide the extras
"""
import math
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from geoalchemy2.shape import to_shape
from shapely.geometry import LineString
from shapely.prepared import prep
from shapely.strtree import STRtree
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from app.models import Route

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")
HIDE = "--hide" in sys.argv
NEAR_M = 30
OVERLAP = 0.85
LENGTH_TOL = 0.15
SAMPLE_M = 40
KX, KY = 111320 * math.cos(math.radians(34.15)), 110540


def is_loop(coords):
    (a, b), (c, d) = coords[0], coords[-1]
    return abs(b - d) < 0.0015 and abs(a - c) < 0.0018


def main():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with Session(engine) as session:
        rows = session.exec(select(Route).where(Route.hidden.is_not(True))).all()
        routes = []
        for r in rows:
            coords = list(to_shape(r.gps_path).coords)
            line = LineString([(x * KX, y * KY) for x, y in coords])
            n = max(2, int(line.length // SAMPLE_M) + 1)
            pts = [line.interpolate(i * line.length / (n - 1)) for i in range(n)]
            routes.append(SimpleNamespace(id=r.id, name=r.nickname or r.name, km=r.distance_km,
                                          loop=is_loop(coords), line=line, pts=pts,
                                          zone=prep(line.buffer(NEAR_M))))
        times_shown = dict(session.exec(text(
            "SELECT route_id, COUNT(*) FROM recommendation WHERE route_id IS NOT NULL GROUP BY route_id")).all())
    print(f"{len(routes)} visible routes  (database: {DATABASE_URL.split('@')[-1].split('/')[0]})")

    tree = STRtree([r.line.envelope.buffer(NEAR_M) for r in routes])

    def covered(a, b):
        return sum(1 for p in a.pts if b.zone.contains(p)) / len(a.pts)

    parent = list(range(len(routes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    pairs = 0
    for i, a in enumerate(routes):
        for j in tree.query(a.line.envelope.buffer(NEAR_M)):
            j = int(j)
            if j <= i:
                continue
            b = routes[j]
            if not a.km or not b.km or abs(a.km - b.km) / max(a.km, b.km) > LENGTH_TOL:
                continue
            if covered(a, b) >= OVERLAP and covered(b, a) >= OVERLAP:
                parent[find(i)] = find(j)
                pairs += 1

    groups = {}
    for i in range(len(routes)):
        groups.setdefault(find(i), []).append(routes[i])
    dupes = [g for g in groups.values() if len(g) > 1]
    to_hide = []
    print(f"\n{len(dupes)} groups of look-alike routes ({sum(len(g) - 1 for g in dupes)} extras):\n")
    for g in sorted(dupes, key=lambda g: -len(g)):
        g.sort(key=lambda r: (not r.loop, -times_shown.get(r.id, 0), len(r.name)))
        keep, extra = g[0], g[1:]
        to_hide += extra
        print(f"  keep  {keep.name} ({keep.km * 0.621:.1f} mi)")
        for r in extra:
            print(f"   hide {r.name} ({r.km * 0.621:.1f} mi)")
    if not HIDE:
        print("\nReport only. Run with --hide to hide the extras (nothing is deleted).")
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE route SET hidden = TRUE WHERE id = :id"), [{"id": r.id} for r in to_hide])
    print(f"\nHid {len(to_hide)} look-alike routes.")


if __name__ == "__main__":
    main()
