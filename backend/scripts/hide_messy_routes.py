"""
Hide routes whose line is a jumble (crossing itself, running the same streets
several times, zig-zagging block by block) so only clean loops, lollipops and
out-and-backs are recommended. Nothing is deleted: they're set hidden, and
--undo un-hides exactly the ones this script hid.

Run from backend/:
    DATABASE_URL=... python3 scripts/hide_messy_routes.py --dry-run
    DATABASE_URL=... python3 scripts/hide_messy_routes.py --preview   # drawings of what would be hidden
    DATABASE_URL=... python3 scripts/hide_messy_routes.py
    DATABASE_URL=... python3 scripts/hide_messy_routes.py --undo
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from route_shape import mess_score, MESSY

if "DATABASE_URL" not in os.environ:
    sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
OUT = os.path.join(os.path.dirname(__file__), "audit_output")
RECORD = os.path.join(os.path.dirname(__file__), "messy_hidden.json")


def preview(items):
    from PIL import Image, ImageDraw
    W, cols = 260, 8
    rows_n = math.ceil(len(items) / cols)
    img = Image.new("RGB", (W * cols, W * rows_n), "white")
    d = ImageDraw.Draw(img)
    for i, (name, score, co) in enumerate(items):
        xs = [c[0] for c in co]; ys = [c[1] for c in co]
        kx = math.cos(math.radians(sum(ys) / len(ys)))
        s = (W - 40) / max((max(xs) - min(xs)) * kx or 1e-6, (max(ys) - min(ys)) or 1e-6)
        ox, oy = (i % cols) * W + 15, (i // cols) * W + 10
        pts = [(ox + (x - min(xs)) * kx * s, oy + (max(ys) - y) * s) for x, y in co]
        d.line(pts, fill=(37, 99, 235), width=2)
        d.text((ox, oy + W - 34), f"{name[:30]}  ({score})", fill="black")
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "messy_preview.png")
    img.save(path)
    print(f"\nDrawings of the {len(items)} messiest: {path}")


def main():
    from sqlalchemy import create_engine, text
    engine = create_engine(os.environ["DATABASE_URL"])
    if "--undo" in sys.argv:
        ids = json.load(open(RECORD)) if os.path.exists(RECORD) else []
        with engine.begin() as conn:
            for i in ids:
                conn.execute(text("UPDATE route SET hidden = FALSE WHERE id = CAST(:id AS uuid)"), {"id": i})
        print(f"Un-hid {len(ids)} routes.")
        return
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, COALESCE(nickname, name), surface_type, ST_AsText(gps_path) "
                                 "FROM route WHERE NOT COALESCE(hidden, FALSE)")).all()
    messy = []
    for n, (rid, name, surface, wkt) in enumerate(rows, 1):
        if n % 200 == 0:
            print(f"  {n}/{len(rows)} checked")
        if not wkt or not wkt.startswith("LINESTRING"):
            continue
        co = [tuple(map(float, p.split())) for p in wkt[wkt.index("(") + 1:-1].split(",")]
        score = mess_score(co, surface)
        if score >= MESSY:
            messy.append((str(rid), name, score, co))
    messy.sort(key=lambda m: -m[2])
    print(f"\n{len(rows)} routes checked; {len(messy)} are messy (score {MESSY}+) and would be hidden. "
          f"{len(rows) - len(messy)} stay.")
    for rid, name, score, _ in messy[:15]:
        print(f"  {score:5.1f}  {name}")
    if "--preview" in sys.argv:
        preview([(m[1], m[2], m[3]) for m in messy[:24]] +
                [(m[1], m[2], m[3]) for m in messy[-24:]])     # the worst, and the borderline ones
    if "--dry-run" in sys.argv or "--preview" in sys.argv:
        print("\nDry run: nothing changed.")
        return
    with engine.begin() as conn:
        for rid, *_ in messy:
            conn.execute(text("UPDATE route SET hidden = TRUE WHERE id = CAST(:id AS uuid)"), {"id": rid})
    old = json.load(open(RECORD)) if os.path.exists(RECORD) else []
    json.dump(sorted(set(old) | {m[0] for m in messy}), open(RECORD, "w"))
    print(f"\nHid {len(messy)} routes (undo: --undo).")


if __name__ == "__main__":
    main()
