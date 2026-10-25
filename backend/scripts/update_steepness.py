"""
Find the steepest stretch of every route, and take out the barely-runnable ones
(like the steep Mount Washington connector two study participants called brutal).

  steepest_grade   steepest climb sustained over 200 m, as a fraction (0.15 = 15%),
                   in either direction (routes can be run both ways)

Routes at or above HIDE_GRADE (20% on roads, 28% on trails) are hidden. Anything
steeper than ~12% that stays gets a scoring penalty in the app (lighter if you asked for hills).

Uses the same USGS elevation data as update_elevation_dem.py. Run from backend/:
    DATABASE_URL=... python3 scripts/update_steepness.py --dry-run
    DATABASE_URL=... python3 scripts/update_steepness.py
    DATABASE_URL=... python3 scripts/update_steepness.py --undo     # un-hide what it hid
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update_elevation_dem import resample, elevations, STEP_M  # noqa: E402  (also checks DATABASE_URL)
from sqlalchemy import create_engine, text  # noqa: E402

WINDOW_M = 200
HIDE_GRADE = {"trail": 0.28}       # trails: fire roads are steep on purpose
HIDE_GRADE_DEFAULT = 0.20          # roads / mixed / track
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "steep_hidden.json")


def steepest(coords):
    pts = resample(coords)
    el = elevations(pts)
    if not el or sum(e is None for e in el) > 0.1 * len(el):
        return None, None
    w = max(1, int(WINDOW_M // STEP_M))
    best, where = 0.0, None
    for i in range(len(el) - w):
        a, b = el[i], el[i + w]
        if a is None or b is None:
            continue
        g = abs(b - a) / (w * STEP_M)
        if g > best:
            best, where = g, pts[i + w // 2]
    return round(best, 3), where


def read_routes(engine, tries=3):
    """The connection to Supabase sometimes drops mid-read ("SSL SYSCALL error: EOF"):
    start a fresh one and try again."""
    import time
    from sqlalchemy.exc import OperationalError
    for attempt in range(1, tries + 1):
        try:
            with engine.connect() as conn:
                return conn.execute(text("SELECT id, COALESCE(nickname, name), surface_type, "
                                         "ST_AsText(gps_path) FROM route "
                                         "WHERE NOT COALESCE(hidden, FALSE)")).all()
        except OperationalError:
            if attempt == tries:
                raise
            print(f"  database connection dropped, retrying ({attempt}/{tries - 1})...")
            engine.dispose()
            time.sleep(3)


def main():
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    if "--undo" in sys.argv:
        ids = json.load(open(BACKUP))
        with engine.begin() as conn:
            for rid in ids:
                conn.execute(text("UPDATE route SET hidden = FALSE WHERE id = :id"), {"id": rid})
        print(f"Un-hid {len(ids)} routes.")
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS steepest_grade FLOAT"))
    rows = read_routes(engine)
    results = []
    for k, (rid, name, surf, wkt) in enumerate(rows, 1):
        if k % 100 == 0:
            print(f"  {k}/{len(rows)} measured", flush=True)
        if not wkt or not wkt.startswith("LINESTRING"):
            continue
        co = [tuple(map(float, p.split())) for p in wkt[wkt.index("(") + 1:-1].split(",")]
        try:
            g, where = steepest(co)
        except Exception as ex:
            print(f"  couldn't read elevation for {name}: {type(ex).__name__}")
            continue
        if g is not None:
            results.append((rid, name, surf, g, where))
    hide = [r for r in results if r[3] >= HIDE_GRADE.get(r[2], HIDE_GRADE_DEFAULT)]
    print(f"\n{len(results)} routes measured.")
    for cut in (0.10, 0.12, 0.15, 0.20, 0.25):
        print(f"  steepest 200 m at {cut:.0%}+: {sum(r[3] >= cut for r in results)} routes")
    print(f"\nTo hide ({len(hide)}): too steep to run")
    for rid, name, surf, g, where in sorted(hide, key=lambda r: -r[3]):
        print(f"  {g:.0%}  {surf:<8} {name}   (steepest at {where[1]:.5f},{where[0]:.5f})")
    mw = [r for r in results if "washington" in (r[1] or "").lower()]
    if mw:
        print("\nMount Washington routes, steepest stretch:")
        for rid, name, surf, g, where in sorted(mw, key=lambda r: -r[3]):
            print(f"  {g:.0%}  {name}{'   <- hidden' if r_in(hide, rid) else ''}")
    if "--dry-run" in sys.argv:
        print("\nDry run: nothing saved.")
        return
    engine.dispose()             # measuring takes minutes; don't reuse an idle connection
    with engine.begin() as conn:
        for rid, _, _, g, _ in results:
            conn.execute(text("UPDATE route SET steepest_grade = :g WHERE id = :id"), {"g": g, "id": rid})
        for rid, *_ in hide:
            conn.execute(text("UPDATE route SET hidden = TRUE WHERE id = :id"), {"id": rid})
    old = json.load(open(BACKUP)) if os.path.exists(BACKUP) else []
    json.dump(sorted(set(old) | {str(r[0]) for r in hide}), open(BACKUP, "w"))
    print(f"\nSaved steepness for {len(results)} routes and hid {len(hide)}.")


def r_in(rows, rid):
    return any(r[0] == rid for r in rows)


if __name__ == "__main__":
    main()
