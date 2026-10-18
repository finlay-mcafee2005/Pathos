"""
Remove pointless detours from route lines: a quick dash down a street and back
(a "spur"), or a tiny loop the line makes before carrying on. They come from how
the routes were generated (snapping to a junction, a dead end, a bridge ramp)
and make a clean loop look messy.

How: walking along each route, if the line goes down a street and comes straight
back the same way to (almost) where it left (within 8 m, the way back following the
way out), and that bit is short (under 600 m and under 15% of the route), it's cut
out. Switchbacks, hairpin bends and small loops are left alone. Real out-and-backs and lollipop loops are kept: the
turnaround (the point farthest from the start) is never cut, and long returns aren't detours.

Then the distance is recalculated. Afterwards re-measure climb, shade and scenery:
    python3 scripts/update_elevation_dem.py
    python3 scripts/update_shade_canopy.py
    python3 scripts/update_scenic.py

    DATABASE_URL=... python3 scripts/clean_route_spurs.py --dry-run
    DATABASE_URL=... python3 scripts/clean_route_spurs.py
"""
import math
import os
import sys

NEAR_M = 8                 # the line has to come back to (almost) the same spot
RETRACE_M = 8              # ...and the way back has to follow the way out this closely
MAX_DETOUR_M = 600
MAX_DETOUR_SHARE = 0.15
MIN_DETOUR_M = 40          # ignore GPS-scale wiggles


def dist_m(a, b):
    """a, b = (lon, lat)"""
    kx = 111320 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * 110540)


def length_m(pts):
    return sum(dist_m(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def densify(pts, step=10.0):
    """Extra points every ~10 m so a return along a long straight segment is noticed."""
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        d = dist_m(a, b)
        n = int(d // step)
        for k in range(1, n + 1):
            t = k / (n + 1)
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        out.append(b)
    return out


def is_retrace(pts, cum, j, k):
    """True if pts[j..k] goes out and comes straight back the same way (a dead-end spur):
    each point on the way out has a matching point the same distance back from the end.
    Switchbacks, hairpins and little loops fail this, so they're left alone."""
    span = cum[k] - cum[j]
    a, b = j, k
    while a < b:
        out_d = cum[a] - cum[j]
        while b > a and (cum[k] - cum[b]) < out_d:
            b -= 1
        if b <= a:
            break
        if dist_m(pts[a], pts[b]) > RETRACE_M:
            return False
        a += max(1, (b - a) // 20)      # sample ~20 pairs, enough to tell
    return span > 0


def remove_detours(pts):
    """Returns (cleaned points, metres removed)."""
    pts = densify(pts)
    total = length_m(pts)
    limit = min(MAX_DETOUR_M, MAX_DETOUR_SHARE * total)
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + dist_m(pts[i - 1], pts[i]))
    # the turnaround of an out-and-back (the point farthest from the start) is never a "detour"
    far = max(range(len(pts)), key=lambda i: dist_m(pts[0], pts[i]))
    keep = []
    removed = 0.0
    j = 0
    while j < len(pts):
        keep.append(j)
        # farthest point ahead that comes back within NEAR_M of pts[j], inside the limit
        best = None
        k = j + 1
        while k < len(pts) and cum[k] - cum[j] <= limit:
            if cum[k] - cum[j] >= MIN_DETOUR_M and dist_m(pts[j], pts[k]) <= NEAR_M \
                    and not (j < far < k) and is_retrace(pts, cum, j, k):
                best = k
            k += 1
        if best is not None and best < len(pts) - 1 or (best is not None and j > 0):
            removed += cum[best] - cum[j]
            j = best + 1          # skip the detour; pts[best] ~ pts[j]
        else:
            j += 1
    out = [pts[i] for i in keep]
    if out[-1] != pts[-1]:
        out.append(pts[-1])       # always keep the real end (loops close on their start)
    # thin back out: drop points closer than 3 m to the previous kept one
    thin = [out[0]]
    for p in out[1:]:
        if dist_m(thin[-1], p) >= 3:
            thin.append(p)
    if thin[-1] != out[-1]:
        thin.append(out[-1])
    return thin, removed


def write_previews(changes):
    """Before (grey, wide) and after (blue) drawings of each route, as SVG files plus
    an index.html, in scripts/audit_output/spurs_preview/ - open index.html to look."""
    out = os.path.join(os.path.dirname(__file__), "audit_output", "spurs_preview")
    os.makedirs(out, exist_ok=True)
    cards = []
    for n, (rid, name, km, new_km, removed, clean) in enumerate(changes):
        before = ORIGINALS[rid]
        xs = [p[0] for p in before]
        ys = [p[1] for p in before]
        kx = math.cos(math.radians(sum(ys) / len(ys)))
        w = (max(xs) - min(xs)) * kx or 1e-6
        h = (max(ys) - min(ys)) or 1e-6
        scale = 380 / max(w, h)

        def poly(ps):
            return " ".join(f"{20 + (x - min(xs)) * kx * scale:.1f},{20 + (max(ys) - y) * scale:.1f}" for x, y in ps)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="420" viewBox="0 0 420 420">'
               f'<rect width="420" height="420" fill="#fff"/>'
               f'<polyline points="{poly(before)}" fill="none" stroke="#f87171" stroke-width="7" stroke-linejoin="round"/>'
               f'<polyline points="{poly(clean)}" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linejoin="round"/>'
               f'<text x="10" y="410" font-family="sans-serif" font-size="12">{name[:40]}: {km * 0.621:.2f} -> {new_km * 0.621:.2f} mi</text>'
               f'</svg>')
        fn = f"route_{n:02d}.svg"
        with open(os.path.join(out, fn), "w") as f:
            f.write(svg)
        cards.append(f'<figure><img src="{fn}"><figcaption>{name}</figcaption></figure>')
    with open(os.path.join(out, "index.html"), "w") as f:
        f.write("<html><body style='font-family:sans-serif'><p>Red = removed back-and-forth, "
                "blue = the cleaned route.</p><div style='display:flex;flex-wrap:wrap;gap:8px'>"
                + "".join(cards) + "</div></body></html>")
    print(f"\nPreview drawings written to {out}/index.html")


ORIGINALS = {}


def main():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    if "DATABASE_URL" not in os.environ:
        sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
    from sqlalchemy import create_engine, text
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, COALESCE(nickname, name), distance_km, ST_AsText(gps_path) "
                                 "FROM route WHERE NOT COALESCE(hidden, FALSE)")).all()
    changes = []
    for rid, name, km, wkt in rows:
        if not wkt or not wkt.startswith("LINESTRING"):
            continue
        pts = [tuple(map(float, p.split())) for p in wkt[wkt.index("(") + 1:-1].split(",")]
        if len(pts) < 3:
            continue
        ORIGINALS[rid] = pts
        clean, removed = remove_detours(pts)
        if removed >= MIN_DETOUR_M and len(clean) >= 2:
            new_km = length_m(clean) / 1000
            changes.append((rid, name, km, new_km, removed, clean))
    changes.sort(key=lambda c: -c[4])
    print(f"{len(rows)} routes checked; {len(changes)} have detours to remove "
          f"({sum(c[4] for c in changes) / 1609.34:.0f} mi of back-and-forth in total).")
    for rid, name, km, new_km, removed, _ in changes[:20]:
        print(f"  {name[:45]:<45} {km * 0.621:5.2f} -> {new_km * 0.621:5.2f} mi  (removed {removed:.0f} m)")
    if "--preview" in sys.argv:
        write_previews(changes[:24] + changes[len(changes) // 2: len(changes) // 2 + 12])
    if "--dry-run" in sys.argv or "--preview" in sys.argv:
        print("\nDry run: nothing saved.")
        return
    with engine.begin() as conn:
        for rid, name, km, new_km, removed, clean in changes:
            wkt = "LINESTRING(" + ", ".join(f"{x:.7f} {y:.7f}" for x, y in clean) + ")"
            conn.execute(text("UPDATE route SET gps_path = ST_GeomFromText(:w, 4326), distance_km = :d, "
                              "shade_pct = NULL WHERE id = :id"),
                         {"w": wkt, "d": round(new_km, 3), "id": rid})
    print(f"\nCleaned {len(changes)} routes. Now re-run update_elevation_dem.py, "
          f"update_shade_canopy.py and update_scenic.py.")


if __name__ == "__main__":
    main()
