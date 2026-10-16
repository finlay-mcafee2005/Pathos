"""
Step 3 of the park & path route generator: add the new routes to the database.

  - skips any that duplicate a route you already have (85%+ of the same path,
    similar length), and look-alikes among the new ones
  - keeps the best ones (most in-park, least retracing), up to --max (default 300)
  - gives each a clear, unique title (e.g. "Elysian Park Loop (3.1 mi)")
  - remembers what it added, so `--undo` can hide them all again

Run from backend/:
    DATABASE_URL=... python3 scripts/load_park_routes.py --dry-run
    DATABASE_URL=... python3 scripts/load_park_routes.py
    DATABASE_URL=... python3 scripts/load_park_routes.py --undo      # hide everything it added
    DATABASE_URL=... python3 scripts/load_park_routes.py --src more_routes.json --max 400   # round 2
Afterwards, fill in climb, shade and scenic for the new routes:
    python3 scripts/update_elevation_dem.py
    python3 scripts/update_shade_canopy.py
    python3 scripts/update_scenic.py
"""
import json
import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape
from shapely.geometry import LineString
from shapely.prepared import prep
from shapely.strtree import STRtree
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from app.models import Route
from app.scoring.difficulty import classify_difficulty

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")
if "DATABASE_URL" not in os.environ:
    sys.exit("DATABASE_URL isn't set, so this would use your local database. In this Terminal window, run:\n"
             '  export DATABASE_URL="<your Supabase link>"\nthen run this script again.')
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, ".shade_cache",
                   sys.argv[sys.argv.index("--src") + 1] if "--src" in sys.argv else "park_routes.json")
# names that make a poor route title (landfills, agency names, admin areas)
BAD_NAME_WORDS = ("landfill", "ladwp", "mrca", "authority", "mitigation", "maintenance", "closed",
                  "unmaintained", "easement", "parcel")
LOG = os.path.join(HERE, ".shade_cache", "park_routes_inserted.json")
DRY_RUN = "--dry-run" in sys.argv
MAX = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 300
PER_PARK = 10
KX, KY = 111320 * math.cos(math.radians(34.15)), 110540
NEAR_M, OVERLAP, LEN_TOL = 30, 0.85, 0.20


def mline(coords):
    return LineString([(x * KX, y * KY) for x, y in coords])


def share_inside(a, zone, n=40):
    pts = [a.interpolate(i / (n - 1), normalized=True) for i in range(n)]
    return sum(1 for p in pts if zone.contains(p)) / n


def is_dupe(line, km, others):
    zone = prep(line.buffer(NEAR_M))
    for o_line, o_km, o_zone in others:
        if o_km and abs(o_km - km) / max(o_km, km) <= LEN_TOL and \
                share_inside(line, o_zone) >= OVERLAP and share_inside(o_line, zone) >= OVERLAP:
            return True
    return False


def undo(engine):
    if not os.path.exists(LOG):
        sys.exit("Nothing to undo.")
    ids = json.load(open(LOG))
    with engine.begin() as conn:
        conn.execute(text("UPDATE route SET hidden = TRUE WHERE id = CAST(:id AS uuid)"), [{"id": i} for i in ids])
    print(f"Hid {len(ids)} park & path routes.")


def main():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    if "--undo" in sys.argv:
        return undo(engine)
    cands = json.load(open(SRC))["routes"]
    print(f"{len(cands)} candidates from the generator")
    with Session(engine) as session:
        existing = [(r.nickname or r.name, r.distance_km, list(to_shape(r.gps_path).coords))
                    for r in session.exec(select(Route).where(Route.hidden.is_not(True))).all()]
        taken_names = {n for n, _, _ in existing}
    ex = []
    for _, km, coords in existing:
        line = mline(coords)
        ex.append((line, km, prep(line.buffer(NEAR_M))))
    tree = STRtree([e[0].buffer(NEAR_M) for e in ex])
    print(f"{len(existing)} routes already in the app  (database: {DATABASE_URL.split('@')[-1].split('/')[0]})")

    cands.sort(key=lambda c: -c["quality"])
    kept, per_park, skipped_existing, skipped_new = [], Counter(), 0, 0
    kept_geo = []
    for c in cands:
        if len(kept) >= MAX:
            break
        if any(w in c["name"].lower() for w in BAD_NAME_WORDS):
            continue
        if per_park[c["park"]] >= PER_PARK:
            continue
        line = mline(c["coords"])
        km = c["length_m"] / 1000
        near = [ex[int(i)] for i in tree.query(line.buffer(NEAR_M))]
        if is_dupe(line, km, near):
            skipped_existing += 1
            continue
        if is_dupe(line, km, kept_geo):
            skipped_new += 1
            continue
        kept.append(c)
        kept_geo.append((line, km, prep(line.buffer(NEAR_M))))
        per_park[c["park"]] += 1

    # unique titles: add the distance where a name repeats or already exists
    counts = Counter(c["name"] for c in kept)
    for c in kept:
        mi = c["length_m"] / 1609.34
        title = c["name"]
        if counts[title] > 1 or title in taken_names:
            title = f"{title} ({mi:.1f} mi)"
        n = 2
        base = title
        while title in taken_names:
            title = f"{base} #{n}"
            n += 1
        taken_names.add(title)
        c["title"] = title

    kinds = Counter(c["kind"] for c in kept)
    surf = Counter(c["surface"] for c in kept)
    print(f"\nAdding {len(kept)} routes ({kinds.get('park_loop', 0)} park loops, "
          f"{kinds.get('greenway', 0)} river/greenway runs, {kinds.get('park_pair', 0)} park-to-park loops, "
          f"{kinds.get('trail_run', 0)} trail runs); surfaces {dict(surf)}")
    print(f"Skipped {skipped_existing} that duplicate routes you already have, "
          f"{skipped_new} look-alikes among the new ones.")
    for c in kept[:20]:
        print(f"  {c['title']}  [{c['surface']}]")
    if len(kept) > 20:
        print(f"  ... and {len(kept) - 20} more")
    if DRY_RUN:
        print("\nDry run: nothing saved. Run without --dry-run to add them.")
        return

    ids = []
    with Session(engine) as session:
        for c in kept:
            km = round(c["length_m"] / 1000, 2)
            run_km = km if c["loop"] else km * 2
            r = Route(name=c["title"][:100], nickname=c["title"][:100], distance_km=km,
                      elevation_gain_m=0.0, surface_type=c["surface"],
                      difficulty=classify_difficulty(run_km), scenic=True,
                      gps_path=WKTElement("LINESTRING(" + ", ".join(f"{x} {y}" for x, y in c["coords"]) + ")",
                                          srid=4326))
            session.add(r)
            session.flush()
            ids.append(str(r.id))
        session.commit()
    prev = json.load(open(LOG)) if os.path.exists(LOG) else []
    json.dump(prev + ids, open(LOG, "w"))
    print(f"\nAdded {len(ids)} routes. Now run update_elevation_dem.py, update_shade_canopy.py "
          f"and update_scenic.py to fill in their climb, shade and scenery.")


if __name__ == "__main__":
    main()
