"""
Export every visible route's line (plus name and surface) for the poster coverage map.
Run from backend/:
    DATABASE_URL=... python3 scripts/export_route_map.py
Writes scripts/audit_output/route_map_data.json
"""
import json
import os
import sys

if "DATABASE_URL" not in os.environ:
    sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as conn:
    rows = conn.execute(text("SELECT COALESCE(nickname, name), surface_type, distance_km, ST_AsText(gps_path) "
                             "FROM route WHERE NOT COALESCE(hidden, FALSE)")).all()
out = []
for name, surface, km, wkt in rows:
    if wkt and wkt.startswith("LINESTRING"):
        pts = [[round(float(a), 5), round(float(b), 5)] for a, b in
               (p.split() for p in wkt[wkt.index("(") + 1:-1].split(","))]
        out.append({"name": name, "surface": surface, "km": km, "coords": pts[::2] + [pts[-1]]})
path = os.path.join(os.path.dirname(__file__), "audit_output", "route_map_data.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
json.dump(out, open(path, "w"))
print(f"Saved {len(out)} routes to {path}")
