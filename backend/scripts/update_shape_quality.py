"""
How clean a route's shape is, for the scoring engine (testers: "shape is everything"):

  jogs        short side trips in the middle of a route: a dead-end dash out and back
              along the same street ("go half a block down and turn around"), or, on
              streets, a little detour round a block or a plaza that comes straight back
              (the Hazelwood jog, the In-N-Out detour, the plaza on Colorado). The start,
              the end and a lollipop's stem don't count.
  near_self   loops only: share of the route within ~100 m of another part of itself that's
              well apart along the way: a long lollipop stem, a loop out on one street and back
              on the parallel street one block over, or a loop that runs back over itself.
              A big open loop is near 0; out and back on parallel streets is near 1.

Run from backend/ (after any route cleanup):
    DATABASE_URL=... python3 scripts/update_shape_quality.py --dry-run
    DATABASE_URL=... python3 scripts/update_shape_quality.py
    python3 scripts/update_shape_quality.py --cache        # test on the audit cache
"""
import math
import os
import pickle
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "audit_output", "routes_cache.pkl")
STEP_M = 10.0
SPUR_OUT_M = (30, 300)   # a dead-end dash goes this far out (then back the same way)
SAME_M = 8               # back along the same street: routes are drawn on centrelines
DETOUR_M = (150, 500)    # a detour round a block / plaza: this long along the route ...
DETOUR_BACK_M = 15       # ... and back within this of where it left ...
DETOUR_FAR_M = 40        # ... after getting at least this far away
NEAR_M = 110             # two parts of a route this close = running next to where you've been
NEAR_GAP_M = 400         # ...if they're at least this far apart along the route
CLOSED_M = 150           # start and end this close = a loop


def _project(coords):
    lat0 = sum(c[1] for c in coords) / len(coords)
    kx = 111320 * math.cos(math.radians(lat0))
    return [((x - coords[0][0]) * kx, (y - coords[0][1]) * 110540) for x, y in coords]


def _resample(pts, step):
    """Points every `step` m along the line."""
    out = [pts[0]]
    carry = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        if seg == 0:
            continue
        t = step - carry
        while t <= seg:
            out.append((a[0] + (b[0] - a[0]) * t / seg, a[1] + (b[1] - a[1]) * t / seg))
            t += step
        carry = (carry + seg) % step
    return out


def _retraced(p, i, j) -> bool:
    """Does the stretch i..j go out and come back the same way?"""
    half = (j - i) // 2
    if half < 2:
        return False
    same = sum(math.dist(p[i + k], p[j - k]) <= SAME_M for k in range(1, half))
    return same >= 0.7 * (half - 1)


def count_jogs(p, skip_start_m=0.0, skip_end_m=0.0, streets=True):
    """Dead-end dashes (any surface) and, on streets, little detour loops."""
    n = len(p)
    lo = int(skip_start_m / STEP_M) + 3
    hi = n - int(skip_end_m / STEP_M) - 3
    jogs, i = 0, lo
    while i < hi:
        hit = None
        for half in range(int(SPUR_OUT_M[0] / STEP_M), int(SPUR_OUT_M[1] / STEP_M) + 1):
            j = i + 2 * half
            if j >= hi:
                break
            if math.dist(p[i], p[j]) <= SAME_M + 4 and math.dist(p[i], p[i + half]) >= SPUR_OUT_M[0] * 0.8 \
                    and _retraced(p, i, j):
                hit = j
                break
        if hit is None and streets:
            far = 0.0
            for j in range(i + 1, min(hi, i + int(DETOUR_M[1] / STEP_M)) + 1):
                far = max(far, math.dist(p[i], p[j]))
                if j - i >= DETOUR_M[0] / STEP_M and far >= DETOUR_FAR_M \
                        and math.dist(p[i], p[j]) <= DETOUR_BACK_M:
                    hit = j
                    break
        if hit is not None:
            jogs += 1
            i = hit + 1
        else:
            i += 1
    return jogs


def near_self_share(p):
    """Share of points within NEAR_M of a part of the route at least NEAR_GAP_M away along it
    (going either way round, so the loop closing on its own start doesn't count)."""
    grid = {}
    for k, (x, y) in enumerate(p):
        grid.setdefault((int(x // NEAR_M), int(y // NEAR_M)), []).append(k)
    gap, n = int(NEAR_GAP_M / STEP_M), len(p)
    flagged = 0
    for k, (x, y) in enumerate(p):
        cx, cy = int(x // NEAR_M), int(y // NEAR_M)
        flagged += any(gap < abs(j - k) < n - gap and math.dist(p[j], (x, y)) < NEAR_M
                       for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in grid.get((cx + dx, cy + dy), ()))
    return round(flagged / n, 3)


def measure(coords, stem_km=None, surface=None):
    if len(coords) < 3:
        return None
    pts = _resample(_project(coords), STEP_M)
    L = (len(pts) - 1) * STEP_M
    if L < 300:
        return None
    # the start / end (and a lollipop's stem) are where routes legitimately go out and back
    edge = (stem_km or 0) * 1000 + 60
    jogs = count_jogs(pts, edge, edge, streets=surface in ("pavement", "mixed", "track", None))
    closed = math.dist(pts[0], pts[-1]) <= CLOSED_M
    return dict(jogs=jogs, near_self=near_self_share(pts) if closed else None)


def summary(results):
    vals = [r for _, _, r in results if r]
    if not vals:
        return
    print(f"\n{len(vals)} routes measured.")
    js = sorted(v["jogs"] for v in vals)
    print(f"  side trips: none in {sum(j == 0 for j in js)} routes, 1 in {sum(j == 1 for j in js)}, "
          f"2+ in {sum(j >= 2 for j in js)} (max {js[-1]})")
    rs = sorted(v["near_self"] for v in vals if v["near_self"] is not None)
    if rs:
        q = lambda f: rs[int(f * (len(rs) - 1))]
        print(f"  loops running next to themselves: median {q(.5):.0%}, 75th pct {q(.75):.0%}, 90th pct {q(.9):.0%}; "
              f"over 60%: {sum(x > 0.6 for x in rs)} of {len(rs)} loops")
    print("  most side trips:")
    for _, name, r in sorted(results, key=lambda t: -((t[2] or {}).get("jogs") or 0))[:8]:
        print(f"    {r['jogs']}  {name}")
    print("  loops that most run next to themselves (lollipops, parallel streets):")
    loops = [t for t in results if t[2] and t[2]["near_self"] is not None]
    for _, name, r in sorted(loops, key=lambda t: -t[2]["near_self"])[:8]:
        print(f"    {r['near_self']:.0%}  {name}")


def main():
    if "--cache" in sys.argv:
        rows = pickle.load(open(CACHE, "rb"))
        results = []
        for r in rows:
            if r.get("hidden"):
                continue
            res = measure(r["coords"], r.get("stem_km"), r.get("surface_type"))
            if res:
                r.update(res)
            results.append((r["id"], r.get("nickname") or r["name"], res))
        if "--dry-run" not in sys.argv:
            pickle.dump(rows, open(CACHE, "wb"))
        summary(results)
        print("\nAudit cache only (no database).")
        return
    if "DATABASE_URL" not in os.environ:
        sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
    from sqlalchemy import create_engine, text
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS jogs INTEGER"))
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS near_self FLOAT"))
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, COALESCE(nickname, name), ST_AsText(gps_path), stem_km, surface_type FROM route "
                                 "WHERE NOT COALESCE(hidden, FALSE)")).all()
    results = []
    for k, (rid, name, wkt, stem, surface) in enumerate(rows, 1):
        if k % 200 == 0:
            print(f"  {k}/{len(rows)} measured")
        if not wkt or not wkt.startswith("LINESTRING"):
            continue
        co = [tuple(map(float, p.split())) for p in wkt[wkt.index("(") + 1:-1].split(",")]
        results.append((rid, name, measure(co, stem, surface)))
    summary(results)
    if "--dry-run" in sys.argv:
        print("\nDry run: nothing saved.")
        return
    with engine.begin() as conn:
        for rid, _, r in results:
            if r:
                conn.execute(text("UPDATE route SET jogs=:j, near_self=:n WHERE id=:id"),
                             {"j": r["jogs"], "n": r["near_self"], "id": rid})
    print(f"\nSaved shape measures for {sum(1 for *_, r in results if r)} routes.")


if __name__ == "__main__":
    main()
