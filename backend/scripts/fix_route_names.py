"""
Give generated routes with a placeholder name ("Neighborhood Long Loop") a real one:
the nearest named neighborhood or place to the route's middle, e.g.
"Cypress Park Long Loop (12.5 mi)". Names stay unique.

Run from backend/:
    DATABASE_URL=... python3 scripts/fix_route_names.py --dry-run
    DATABASE_URL=... python3 scripts/fix_route_names.py
"""
import math
import os
import pickle
import sys

from sqlalchemy import create_engine, text

HERE = os.path.dirname(os.path.abspath(__file__))
if "DATABASE_URL" not in os.environ:
    sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
places = pickle.load(open(os.path.join(HERE, ".shade_cache", "network.pkl"), "rb"))["places"]
engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


def nearest_place(lon, lat):
    kx = math.cos(math.radians(lat))
    return min(places, key=lambda p: ((p[1] - lon) * kx) ** 2 + (p[2] - lat) ** 2)[0]


with engine.connect() as conn:
    taken = {r[0] for r in conn.execute(text("SELECT nickname FROM route WHERE nickname IS NOT NULL")).all()}
    rows = conn.execute(text(
        "SELECT id, nickname, name, distance_km, ST_X(ST_Centroid(gps_path)), ST_Y(ST_Centroid(gps_path)) "
        "FROM route WHERE COALESCE(nickname, name) ILIKE 'Neighborhood %'")).all()
changes = []
for rid, nick, name, km, lon, lat in rows:
    kind = "Long Loop" if "long loop" in (nick or name).lower() else "Green Loop" if "green" in (nick or name).lower() else "Loop"
    base = f"{nearest_place(lon, lat)} {kind}"
    new = f"{base} ({km * 0.621371:.1f} mi)"
    n = 2
    while new in taken:
        new = f"{base} {n} ({km * 0.621371:.1f} mi)"
        n += 1
    taken.add(new)
    changes.append((rid, nick or name, new))
for _, old, new in changes:
    print(f"  {old}  ->  {new}")
print(f"{len(changes)} routes to rename.")
if "--dry-run" in sys.argv:
    sys.exit("Dry run: nothing saved.")
with engine.begin() as conn:
    for rid, _, new in changes:
        conn.execute(text("UPDATE route SET nickname = :n WHERE id = :id"), {"n": new, "id": rid})
print("Saved.")
