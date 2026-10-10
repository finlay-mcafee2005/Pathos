"""
Give every route a unique, descriptive title (stored in route.nickname).

Generated routes are named after their starting anchor ("Occidental College
road loop - 8 km south"), so several loops from the same place look alike.
This script looks up the neighborhood, park or street each route heads to
(the point farthest from its start) and names it after that:

    Occidental College to Highland Park Loop
    Eagle Rock Trail Loop via Yosemite Recreation Center
    Debs Park Out-and-Back to Monterey Hills

Any names that still clash get the distance added ("... · 5.0 mi").
The original route.name is left alone, so the generator scripts keep working.

Run from backend/:
    python3 scripts/name_routes.py --dry-run   # print the new names only
    python3 scripts/name_routes.py             # save them
Uses OpenStreetMap's free Nominatim service (1 lookup per second), so
expect about a second per route.
"""

import json
import os
import re
import sys
import time
from math import radians, sin, cos, sqrt, atan2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from geoalchemy2.shape import to_shape
from sqlalchemy import text
from sqlmodel import Session, create_engine, select

from app.models import Route

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")
REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {"User-Agent": "run-recommender-app (student project)"}

GENERATED = re.compile(
    r"^(?P<anchor>.+?) (?P<kind>road loop|trail loop|trail out-and-back)"
    r"\s+-\s+(?P<km>\d+(?:\.\d+)?)\s*km\s+(?P<dir>north|south|east|west)$",
    re.IGNORECASE,
)
PLACE_KEYS_TRAIL = ["leisure", "natural", "tourism", "park", "neighbourhood", "suburb", "quarter", "road"]
STREET_ENDINGS = ("Street", "Avenue", "Boulevard", "Drive", "Road", "Way", "Lane", "Place", "Terrace",
                  "St", "Ave", "Blvd", "Dr", "Rd", "Ln")
PLACE_KEYS_ROAD = ["neighbourhood", "suburb", "quarter", "leisure", "road"]


def km_between(a, b):
    (lat1, lon1), (lat2, lon2) = a, b
    r = 6371.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * atan2(sqrt(h), sqrt(1 - h))


CACHE_FILE = os.path.join(os.path.dirname(__file__), ".place_cache.json")
try:
    with open(CACHE_FILE) as f:
        _cache = json.load(f)        # raw lookups, so re-runs (and rule tweaks) are instant
except (OSError, ValueError):
    _cache = {}

BAD_PLACE = re.compile(r"abandoned|future|closed|\"|\bB\b\"", re.IGNORECASE)
PATHLIKE = re.compile(r"\b(trail|path|motorway|fire road|connector|bikeway|lateral|spur)\b", re.IGNORECASE)
GENERIC_NAMES = {"equestrian", "fire road", "main trail", "loop trail", "north trail", "east trail",
                 "west trail", "edison road", "old road grade", "nature trail - upper", "firebreak",
                 "old zoo", "ladwp access", "radio street"}


def clean(name):
    """Tidy a place or trail name for display."""
    if not name:
        return None
    name = re.sub(r"\s+Neighborhood Council( District)?$", "", name)
    name = re.sub(r"^Greater\s+", "", name)
    name = re.sub(r"\s*-\s*abandoned segment\s*-\s*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s*\((infrequently|rarely|not)\s+[^)]*\)", "", name, flags=re.IGNORECASE)
    name = name.replace("Montain", "Mountain")
    return re.sub(r"\s{2,}", " ", name).strip() or None


def lookup(lat, lon):
    """Raw reverse-geocode result at a point (cached on disk)."""
    key = f"{lat:.3f},{lon:.3f}"
    if key not in _cache:
        try:
            res = httpx.get(REVERSE_URL, params={"lat": lat, "lon": lon, "format": "jsonv2",
                                                  "zoom": 17, "addressdetails": 1},
                            headers=HEADERS, timeout=15)
            res.raise_for_status()
            data = res.json()
            _cache[key] = {"category": data.get("category"), "name": data.get("name"),
                           "address": data.get("address", {})}
        except Exception as e:  # network hiccup: fall back to direction naming
            print(f"   lookup failed ({e})")
            return {"address": {}}
        time.sleep(1.1)  # Nominatim's usage policy: max 1 request per second
        if len(_cache) % 25 == 0:
            save_cache()
    return _cache[key]


def save_cache():
    with open(CACHE_FILE, "w") as f:
        json.dump(_cache, f)


def places_at(lat, lon, trail):
    """(area, street) near a point: area = neighborhood or park, street = road name."""
    data = lookup(lat, lon)
    addr = data.get("address", {})
    area = None
    if data.get("category") in ("leisure", "natural", "tourism") and data.get("name"):
        area = data["name"]
    keys = ["leisure", "natural", "park", "neighbourhood", "suburb", "quarter"] if trail \
        else ["neighbourhood", "suburb", "quarter"]
    for k in keys:
        if area:
            break
        area = addr.get(k)
    area, street = clean(area), clean(addr.get("road"))
    if area and (BAD_PLACE.search(area) or (not trail and PATHLIKE.search(area))):
        area = None          # road loops aren't named after trails or odd features
    if area and area.endswith(STREET_ENDINGS):
        area = None          # a street isn't a destination ("to Dayton Avenue")
    if street and (BAD_PLACE.search(street) or len(street.split()) > 5
                   or re.search(r"\bno street\b|\brecord\b", street, re.IGNORECASE)
                   or (not trail and PATHLIKE.search(street))):
        street = None        # junk labels, and trails as the "via" of a road loop
    return area, street


def overlaps(a, b):
    """True if two names share a significant word ('Downtown Glendale' / 'Glendale City Center')."""
    stop = {"the", "of", "park", "city", "center", "downtown", "village", "lake", "heights", "loop"}
    wa = {w for w in re.findall(r"[a-z]+", a.lower()) if w not in stop and len(w) > 2}
    wb = {w for w in re.findall(r"[a-z]+", b.lower()) if w not in stop and len(w) > 2}
    return bool(wa & wb) or a.lower() in b.lower() or b.lower() in a.lower()


SHORT_ANCHOR = {
    "Occidental College": "Oxy",
    "Griffith Observatory": "Observatory",
    "Sam Merrill (Cobb Estate)": "Sam Merrill",
    "Deukmejian Wilderness": "Deukmejian",
    "Fern Dell (Griffith Park)": "Fern Dell",
    "Downtown Glendale": "Glendale",
    "Downtown Burbank": "Burbank",
    "Lower Arroyo Seco": "Arroyo Seco",
    "Baldwin Hills Overlook": "Baldwin Hills",
    "Kenneth Hahn Park": "Kenneth Hahn",
}
STREET_ABBR = [("Boulevard", "Blvd"), ("Avenue", "Ave"), ("Street", "St"), ("Drive", "Dr"),
               ("Road", "Rd"), ("Place", "Pl"), ("Terrace", "Ter"), ("Lane", "Ln"),
               ("Motorway", "Mtwy"), ("Mtrwy", "Mtwy")]
MAX_LEN = 32


def short_street(name):
    """'North Figueroa Street' -> 'Figueroa St'"""
    trimmed = re.sub(r"^(North|South|East|West)\s+", "", name)
    if len(trimmed.split()) >= 2:   # keep "East Avenue" / "North Trail" whole
        name = trimmed
    for long, short in STREET_ABBR:
        name = re.sub(rf"\b{long}$", short, name)
    return name


def is_loop(pts):
    return km_between(pts[0], pts[-1]) < 0.15


def describe(route):
    """Returns candidate titles for a route, best first. The first one that
    doesn't clash with another route's title is used."""
    coords = list(to_shape(route.gps_path).coords)  # (lon, lat)
    pts = [(lat, lon) for lon, lat in coords]
    start = pts[0]
    far = max(pts, key=lambda p: km_between(start, p))
    m = GENERATED.match(route.name)
    trail = route.surface_type in ("trail", "mixed")
    area, street = places_at(far[0], far[1], trail)

    if not m:
        # a real named trail: tidy it; vague names ("Fire Road") get their area added
        title = clean(route.name) or route.name
        out = [title]
        if title.lower() in GENERIC_NAMES or len(title.split()) == 1:
            start_area, _ = places_at(start[0], start[1], True)
            where = start_area or area
            if where and not overlaps(title, where):
                out.insert(0, f"{title} ({where})")
        return out

    anchor_full, kind, direction = m.group("anchor"), m.group("kind").lower(), m.group("dir").title()
    anchor = SHORT_ANCHOR.get(anchor_full, anchor_full)
    area = area if area and not overlaps(area, anchor_full) else None
    st = short_street(street) if street and not overlaps(street, anchor_full) else None

    if kind == "trail out-and-back":
        forms = [f"{anchor} to {area} & Back" if area else None,
                 f"{anchor} to {st} & Back" if st else None,
                 f"{anchor} {direction} Out & Back"]
    else:  # road or trail loop (surface is shown on the card)
        forms = [f"{anchor} to {area} Loop" if area else None,
                 f"{anchor} Loop via {st}" if st else None,
                 f"{anchor} {direction} Loop"]
    forms = [f for f in forms if f]
    # prefer forms that fit on one line; keep the rest as fallbacks
    return [f for f in forms if len(f) <= MAX_LEN] + [f for f in forms if len(f) > MAX_LEN]


def route_miles(route):
    """Distance as the card shows it: out-and-backs are stored one way."""
    pts = [(lat, lon) for lon, lat in to_shape(route.gps_path).coords]
    km = route.distance_km if is_loop(pts) else route.distance_km * 2
    return km * 0.621371


def main(dry_run):
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE route ADD COLUMN IF NOT EXISTS nickname VARCHAR"))

    with Session(engine) as session:
        routes = session.exec(select(Route)).all()
        print(f"Naming {len(routes)} routes ...\n")
        options = {r.id: describe(r) for r in routes}
        save_cache()

        # give each route its best name that nobody else has; when two routes
        # want the same one, both move on to their next option
        named = {}
        taken = set()
        pending = sorted(routes, key=lambda r: len(options[r.id]))
        for r in pending:
            for opt in options[r.id]:
                rivals = [o for o in routes if o.id != r.id and options[o.id][0].lower() == opt.lower()]
                if opt.lower() not in taken and not rivals:
                    named[r.id] = opt
                    break
            else:
                named[r.id] = None
            if named[r.id]:
                taken.add(named[r.id].lower())

        # anything still unresolved: its best short form + round-trip distance
        for r in routes:
            if not named[r.id]:
                base = options[r.id][-1] if len(options[r.id]) > 1 else options[r.id][0]
                title = f"{base} ({route_miles(r):.1f} mi)"
                n = 2
                while title.lower() in taken:
                    title = f"{base} ({route_miles(r):.1f} mi, {n})"
                    n += 1
                named[r.id] = title
                taken.add(title.lower())

        longest = sorted(named.values(), key=len, reverse=True)[:5]
        if dry_run:
            print("Dry run, nothing saved. Final names:")
            for title in sorted(named.values()):
                print(f"  {title}")
            print("\nLongest names:", *longest, sep="\n  ")
            return

        for r in routes:
            r.nickname = named[r.id]
            session.add(r)
        session.commit()
        print(f"Saved {len(named)} unique names.")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
