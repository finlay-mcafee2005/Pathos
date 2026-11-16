"""
Fix route names that name a neighborhood the route doesn't go to (Aiden: Glassell Park
routes called "Highland Park", a "Lincoln Heights" route that never goes there).

Names came from one reverse-geocoded point per route. This checks the whole route
against OpenStreetMap's place points (neighbourhood / suburb / quarter / town / city)
from the local map file:

  - every ~200 m along the route, the nearest neighbourhood-level place is where that
    stretch is (a rough Voronoi map of LA's neighborhoods)
  - a place named in the route's title is fine if the route passes near it (within ~1 km of
    a neighbourhood point, ~1.6 km of a suburb, ~4 km of a town or city centre) or it's where
    at least 15% of the route is
  - otherwise the place in the title is swapped for the one most of the route is in

The original route.name is left alone (the generator scripts rely on it); the card title
(route.nickname) is what changes. --dry-run lists every change first.

Run from backend/:
    DATABASE_URL=... python3 scripts/check_route_names.py --dry-run
    DATABASE_URL=... python3 scripts/check_route_names.py
Or rename just the ones you've checked:
    python3 scripts/check_route_names.py --rename "Old Title=New Title" --rename "..."
"""
import glob
import json
import math
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(__file__)
PLACES = os.path.join(HERE, ".shade_cache", "places_local.json")
BBOX = (-118.60, 33.90, -117.95, 34.40)
# a place in the title is only "wrong" when the route stays this far from it ...
NEAR_KM = {"neighbourhood": 2.0, "quarter": 2.0, "suburb": 2.5, "town": 5.0, "city": 5.0}
MIN_NEW_SHARE = 0.4      # ... and the replacement is where at least this much of the route is
# place names that are part of a landmark, not a neighborhood: Lake Hollywood, Mount Hollywood,
# Burbank Peak, Big Tujunga Wash, Los Angeles County, San Gabriel Peak
LANDMARK_BEFORE = re.compile(r"\b(lake|mount|mt\.?|big|little|upper|lower|old)\s+$", re.I)
LANDMARK_AFTER = re.compile(r"^\s+(peak|wash|county|reservoir|dam|hills|canyon|ridge|summit)\b", re.I)
LOCAL_KINDS = {"neighbourhood", "quarter", "suburb"}     # what "where this stretch is" uses
STEP_KM = 0.2
MIN_SHARE = 0.15


def km(a, b):
    dy = (a[0] - b[0]) * 110.54
    dx = (a[1] - b[1]) * 111.32 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def extract_places():
    import osmium
    pbf = (glob.glob(os.path.join(HERE, "..", "..", "osrm-data", "*.osm.pbf")) or [None])[0]
    if not pbf:
        sys.exit("No .osm.pbf map file in osrm-data/.")
    out = []

    class H(osmium.SimpleHandler):
        def node(self, n):
            kind, name = n.tags.get("place"), n.tags.get("name")
            if kind in NEAR_KM and name and n.location.valid() \
                    and BBOX[0] <= n.location.lon <= BBOX[2] and BBOX[1] <= n.location.lat <= BBOX[3]:
                out.append([name, kind, n.location.lat, n.location.lon])

    print("Reading place names from the map file (a minute or two)...")
    H().apply_file(pbf)
    os.makedirs(os.path.dirname(PLACES), exist_ok=True)
    json.dump(out, open(PLACES, "w"))
    print(f"  {len(out)} places")
    return out


def load_places():
    return json.load(open(PLACES)) if os.path.exists(PLACES) else extract_places()


def along(coords):
    """[(lat, lon)] every STEP_KM along a [(lon, lat)] line."""
    pts = [(lat, lon) for lon, lat in coords]
    out, carry = [pts[0]], 0.0
    for a, b in zip(pts, pts[1:]):
        seg = km(a, b)
        t = STEP_KM - carry
        while t <= seg and seg > 0:
            f = t / seg
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            t += STEP_KM
        carry = (carry + seg) % STEP_KM
    return out


def check(title, coords, places, local):
    """(new title, named place, majority place) or None if the title is fine."""
    pts = along(coords)
    if not pts:
        return None
    where = Counter(min(local, key=lambda p: km(pt, (p[2], p[3])))[0] for pt in pts)
    total = sum(where.values())
    low = title.lower()
    for name, kind, lat, lon in sorted(places, key=lambda p: -len(p[0])):   # longest names first
        m = re.search(r"\b" + re.escape(name.lower()) + r"\b", low)
        if not m:
            continue
        before, after = title[:m.start()], title[m.end():]
        if LANDMARK_BEFORE.search(before) or LANDMARK_AFTER.search(after):
            continue                          # "Lake Hollywood", "Burbank Peak": a landmark, keep it
        if before.rstrip().endswith("("):
            return None                       # "Old Zoo (Los Feliz)": a trail's area tag, keep it
        near = min(km(pt, (lat, lon)) for pt in pts) <= NEAR_KM[kind]
        share = where.get(name, 0) / total
        if near or share >= MIN_SHARE:
            return None                       # the place it's named after is really on the route
        best, n = where.most_common(1)[0]
        if n / total < MIN_NEW_SHARE or best.lower() in low or name.lower() in best.lower() \
                or best.lower() in name.lower():
            return None                       # no clear better name: leave it
        new = title[:m.start()] + best + title[m.end():]
        words = new.lower().split()
        if any(a == b for a, b in zip(words, words[1:])):
            return None                       # "Canyon Canyon": don't
        return new, name, best
    return None


def manual_renames():
    """--rename "Old Title=New Title" (repeatable): rename just these, checked by hand."""
    out = []
    for i, arg in enumerate(sys.argv):
        if arg == "--rename" and i + 1 < len(sys.argv) and "=" in sys.argv[i + 1]:
            old, new = (x.strip() for x in sys.argv[i + 1].split("=", 1))
            out.append((old, new))
    return out


def main():
    if "DATABASE_URL" not in os.environ:
        sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
    from sqlalchemy import create_engine, text
    picked = manual_renames()
    if picked:
        engine = create_engine(os.environ["DATABASE_URL"])
        with engine.begin() as conn:
            for old, new in picked:
                n = conn.execute(text("UPDATE route SET nickname = :new WHERE COALESCE(nickname, name) = :old"),
                                 {"new": new, "old": old}).rowcount
                print(f"  {old}  ->  {new}   ({n} route{'s' if n != 1 else ''})")
        return
    places = load_places()
    local = [p for p in places if p[1] in LOCAL_KINDS]
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, COALESCE(nickname, name), ST_AsText(gps_path) FROM route "
                                 "WHERE NOT COALESCE(hidden, FALSE)")).all()
    titles = Counter(t for _, t, _ in rows)
    changes = []
    for k, (rid, title, wkt) in enumerate(rows, 1):
        if k % 200 == 0:
            print(f"  {k}/{len(rows)} checked")
        if not wkt or not wkt.startswith("LINESTRING"):
            continue
        coords = [tuple(map(float, p.split())) for p in wkt[wkt.index("(") + 1:-1].split(",")]
        res = check(title, coords, places, local)
        if res:
            new, was, now = res
            if titles[new]:                   # don't create a duplicate title
                continue
            titles[new] += 1
            changes.append((rid, title, new, was, now))
    print(f"\n{len(changes)} of {len(rows)} titles name a place the route doesn't go to:")
    for _, old, new, was, now in changes:
        print(f"  {old}  ->  {new}")
    if "--dry-run" in sys.argv:
        print("\nDry run: nothing saved.")
        return
    with engine.begin() as conn:
        for rid, _, new, _, _ in changes:
            conn.execute(text("UPDATE route SET nickname = :n WHERE id = :id"), {"n": new, "id": rid})
    print(f"\nRenamed {len(changes)} routes.")


if __name__ == "__main__":
    main()
