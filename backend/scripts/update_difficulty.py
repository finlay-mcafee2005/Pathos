"""
Re-grades every route's Easy / Moderate / Hard label from its current distance and
climb, using the shared rule in app/scoring/difficulty.py (no API calls, instant).
Same rule as update_elevation_dem.py: a loop is graded as one lap; a point-to-point
route is graded as it's run, out and back (twice the distance, climb both ways).

update_elevation_dem.py already does this whenever it re-measures climb, so this is
only needed on its own if distances changed without re-running it.

Run from backend/:
    DATABASE_URL=... python3 scripts/update_difficulty.py --dry-run
    DATABASE_URL=... python3 scripts/update_difficulty.py
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine, text

from app.scoring.difficulty import classify_difficulty

if "DATABASE_URL" not in os.environ:
    sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
engine = create_engine(os.environ["DATABASE_URL"])


def is_loop(wkt):
    """Same test as update_elevation_dem.py (~150 m), so the two never disagree."""
    pts = wkt[wkt.index("(") + 1:-1].split(",")
    (x0, y0), (x1, y1) = (tuple(map(float, pts[0].split())), tuple(map(float, pts[-1].split())))
    return abs(y0 - y1) < 0.0015 and abs(x0 - x1) < 0.0018


with engine.connect() as conn:
    rows = conn.execute(text("SELECT id, distance_km, elevation_gain_m, elevation_loss_m, difficulty, "
                             "ST_AsText(gps_path) FROM route")).all()
before, after, updates = Counter(), Counter(), []
for rid, km, gain, loss, old, wkt in rows:
    if not wkt or not wkt.startswith("LINESTRING") or not km:
        continue
    gain = gain or 0.0
    loss = loss if loss is not None else gain
    new = classify_difficulty(km, gain) if is_loop(wkt) else classify_difficulty(km * 2, gain + loss)
    before[old] += 1
    after[new] += 1
    if new != old:
        updates.append((rid, new))

print(f"Checked {sum(after.values())} routes: {len(updates)} labels out of date.")
for level in ("easy", "moderate", "hard"):
    print(f"  {level:<9} {before[level]:>4} -> {after[level]:>4}")
if "--dry-run" in sys.argv:
    print("\nDry run: nothing saved.")
    sys.exit()
with engine.begin() as conn:
    for rid, new in updates:
        conn.execute(text("UPDATE route SET difficulty = :d WHERE id = :id"), {"d": new, "id": rid})
print(f"\nUpdated {len(updates)} routes.")
