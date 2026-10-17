"""
Short, clean route titles: at most four words and no distances
("Ernest E. Debs Regional Park Loop (3.8 mi)" -> "Debs Park Loop",
 "Oxy Loop via Avenue 53" -> "Oxy Avenue 53 Loop",
 "Los Angeles River Bike Path: Atwater Village to Elysian Valley" -> "LA River Atwater Run").
Look-alikes get a direction word (North / South / East / West) or Short / Long,
never a distance - the card already shows the distance.

Updates route.nickname (what the app shows); route.name is left alone.
    DATABASE_URL=... python3 scripts/shorten_route_names.py --dry-run
    DATABASE_URL=... python3 scripts/shorten_route_names.py
"""
import math
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from geoalchemy2.shape import to_shape  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

MAX_WORDS = 4
KINDS = ("Loop", "Run", "Trail", "Out-and-Back", "Path", "Motorway", "Walk")
PLACE_SUBS = [  # long official names -> what runners call them
    (r"Ernest E\. Debs Regional Park", "Debs Park"),
    (r"Hahamongna Watershed Natural Park", "Hahamongna"),
    (r"Eaton Canyon Natural Area and Nature Center", "Eaton Canyon"),
    (r"Los Angeles River Bike ?(Path|way)", "LA River"),
    (r"Los Angeles River", "LA River"),
    (r"Arroyo Seco Bike Path", "Arroyo Seco"),
    (r"Hermon Park \(Arroyo Seco Park\)", "Hermon Park"),
    (r"Gloria Molina Grand Park", "Grand Park"),
    (r"Los Angeles State Historic Park", "State Historic Park"),
    (r"Verdugo Mountains Park Property", "Verdugo Mountains"),
    (r"Verdugo Mountains Open Space Preserve", "Verdugo Mountains"),
    (r"Deukmejian Wilderness Park", "Deukmejian Park"),
    (r"Montrose / La Crescenta", "La Crescenta"),
]
DROP_WORDS = {"regional", "natural", "nature", "area", "and", "center", "open", "space", "watershed",
              "wilderness", "historical", "memorial", "preserve", "property", "conservancy", "the",
              "of", "recreation", "rec", "bike", "path", "bikeway", "foot", "mitigation"}
STREET_SUFFIX = re.compile(r"\s+(St|Ave|Dr|Rd|Blvd|Way|Pl|Ln|Ct|Ter|Cir|Pkwy|Hwy|Street|Avenue|Drive|Road|"
                           r"Boulevard|Lane|Place|Terrace|Highway)\.?$", re.I)


def strip_distances(n):
    n = re.sub(r"\s*\(\s*\d+(\.\d+)?\s*(mi|km)\s*\)", "", n)
    n = re.sub(r"\s*:\s*\d+(\.\d+)?\s*mi out\b", "", n)
    n = re.sub(r"\s*·.*$", "", n)
    n = re.sub(r"\s*#\d+\s*$", "", n)
    n = re.sub(r"\s*\(\s*(Short|Long)\s*\)", "", n)
    n = re.sub(r"\b\d+(\.\d+)?\s*(mi|km|mile|miles)\b", "", n)
    return re.sub(r"\s{2,}", " ", n).strip(" -:")


# first words that don't stand alone ("Mount", "Los", "Lake"...): keep the next word with them
PREFIXES = {"mount", "mt", "los", "la", "las", "el", "san", "santa", "lake", "rose", "fern", "upper",
            "lower", "north", "south", "east", "west", "old", "big", "little", "sierra", "glen", "echo",
            "silver", "highland", "eagle", "lincoln", "elysian", "griffith", "chantry", "sam", "state", "grand",
            "north", "atwater", "montecito", "mid", "pico", "boyle", "cypress", "glassell", "garvey"}


def core(place, keep=2):
    """'Henderson Canyon Open Space' -> 'Henderson Canyon'; drops filler words.
    keep=1 keeps one *meaningful* name: 'Mount Washington', 'Debs', 'Wildwood'."""
    for pat, rep in PLACE_SUBS:
        place = re.sub(pat, rep, place)
    words = [w for w in place.replace("(", "").replace(")", "").split() if w.lower() not in DROP_WORDS]
    if not words:
        return place.split()[0]
    if keep == 1 and len(words) > 1 and words[0].lower() in PREFIXES:
        keep = 2
    return " ".join(words[:keep])


def distinctive(words):
    """One word that identifies a street or feature: 'Mount Lee' -> 'Lee'."""
    for w in words:
        if w.lower() not in PREFIXES and w.lower() not in DROP_WORDS and not w.isdigit():
            return [w]
    return words[:1]


def fit(words, kind):
    words = [x for w in words if w for x in w.split()]
    while len(words) + 1 > MAX_WORDS and len(words) > 1:
        words = words[:-1] if len(words) > 2 else words[1:]
    return " ".join(words + [kind])


def shorten(name):
    n = strip_distances(name).replace("Out & Back", "Out-and-Back").replace("Out and Back", "Out-and-Back")
    for pat, rep in PLACE_SUBS:
        n = re.sub(pat, rep, n)
    # "A to B Loop" (park-to-park)
    m = re.match(r"(.+?) to (.+?) (Loop|Out-and-Back|& Back)$", n)
    if m:
        a, b = core(m.group(1), 1), core(m.group(2), 1)
        kind = "Loop" if m.group(3) == "Loop" else "Out-and-Back"
        return f"{a}–{b} {kind}" if a != b else fit([a], kind)
    # "X Loop via Y St"
    m = re.match(r"(.+?) (Loop|Out-and-Back) via (.+)$", n)
    if m:
        x, kind, y = m.group(1), m.group(2), STREET_SUFFIX.sub("", m.group(3))
        xw, yw = core(x, 2).split(), y.split()
        if len(xw) + len(yw) + 1 > MAX_WORDS and xw[0].lower() == "old" and len(xw) > 1:
            xw = xw[1:]                       # "Old Pasadena" -> "Pasadena"
        if len(xw) + len(yw) + 1 > MAX_WORDS:
            yw = distinctive(yw)              # "Mount Lee Dr" -> "Lee"
        while len(xw) + len(yw) + 1 > MAX_WORDS and len(xw) > 1:
            xw = xw[1:]
        return " ".join(xw + yw + [kind])
    # "Path name: A to B" (greenway runs)
    m = re.match(r"(.+?):\s*(near\s+)?(.+?)(\s+to\s+.+)?$", n)
    if m:
        pw, place = core(m.group(1), 2).split(), core(m.group(3), 1).split()
        if len(pw) + len(place) <= MAX_WORDS:      # "LA River – Silver Lake"
            return f"{' '.join(pw)} – {' '.join(place)}"
        return f"{' '.join(pw[:MAX_WORDS - 1])} – {' '.join(distinctive(place))}"
    # "... Green Loop", "... Loop", "... Trail" etc.
    words = n.split()
    kind = words[-1] if words and words[-1] in KINDS else None
    if kind:
        return fit(core(" ".join(words[:-1]), 3).split(), kind)
    if len(n.split()) <= MAX_WORDS:
        return n
    return " ".join(core(n, MAX_WORDS).split()[:MAX_WORDS])


def direction(xy, center):
    dx, dy = xy[0] - center[0], xy[1] - center[1]
    if math.hypot(dx, dy) < 0.002:
        return "Central"
    return ("East" if dx > 0 else "West") if abs(dx) > abs(dy) else ("North" if dy > 0 else "South")


def nwords(title):
    return len([w for w in title.split() if w != "–"])


def with_word(title, word):
    """Add a qualifier only if there's room (under 4 words); 4-word look-alikes keep
    their name and the app tells them apart on screen (Short / Long)."""
    if nwords(title) >= MAX_WORDS:
        return title
    w = title.split()
    if w[-1] in KINDS:                          # "Debs Park Loop" -> "Debs Park North Loop"
        w = w[:-1] + [word, w[-1]]
        while nwords(" ".join(w)) > MAX_WORDS:
            del w[-3]                          # drop the word just before the qualifier
    else:                                      # "LA River – Atwater Village" -> "LA River – Atwater North"
        w = w + [word]
        while nwords(" ".join(w)) > MAX_WORDS:
            del w[-2]
    return " ".join(w)


def main():
    if "DATABASE_URL" not in os.environ:
        sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, COALESCE(nickname, name), distance_km, ST_AsEWKB(gps_path) "
                                 "FROM route WHERE NOT COALESCE(hidden, FALSE)")).all()
    items = []
    for rid, title, km, geom in rows:
        from geoalchemy2.elements import WKBElement
        g = to_shape(WKBElement(bytes(geom)))
        c = g.centroid
        new = shorten(title)
        (x1, y1), (x2, y2) = g.coords[0], g.coords[-1]
        closed = abs(y1 - y2) < 0.0015 and abs(x1 - x2) < 0.0018          # same rule as the app
        if not closed and new.endswith(" Loop"):
            new = new[: -len(" Loop")] + " Out-and-Back"   # the app runs open routes out and back
        items.append(dict(id=rid, old=title, new=new, km=km or 0, xy=(c.x, c.y)))

    # look-alikes: direction words first, then Short / Long
    groups = defaultdict(list)
    for it in items:
        groups[it["new"]].append(it)
    for name, same in groups.items():
        if len(same) < 2:
            continue
        center = (sum(i["xy"][0] for i in same) / len(same), sum(i["xy"][1] for i in same) / len(same))
        for i in same:
            i["new"] = with_word(name, direction(i["xy"], center))
    groups = defaultdict(list)
    for it in items:
        groups[it["new"]].append(it)
    leftover = 0
    for name, same in groups.items():
        if len(same) < 2:
            continue
        same.sort(key=lambda i: i["km"])
        labels = ["Short", "Long"] if len(same) == 2 else ["Short", "Medium", "Long"] if len(same) == 3 else None
        if labels:
            for i, lab in zip(same, labels):
                i["new"] = with_word(name, lab)
        else:
            leftover += len(same)              # many identical: keep the shared name

    changed = [i for i in items if i["new"] != i["old"]]
    long_ = sum(1 for i in items if nwords(i["new"]) > MAX_WORDS)
    print(f"{len(items)} routes; {len(changed)} titles change; {long_} still over {MAX_WORDS} words; "
          f"{leftover} share a name with 3+ others.")
    import random
    random.seed(4)
    for i in random.sample(changed, min(30, len(changed))):
        print(f"  {i['old'][:60]:<60} -> {i['new']}")
    if "--dry-run" in sys.argv:
        print("\nDry run: nothing saved.")
        return
    with engine.begin() as conn:
        conn.execute(text("UPDATE route SET nickname = :n WHERE id = :id"),
                     [{"id": i["id"], "n": i["new"]} for i in changed])
    print(f"\nSaved {len(changed)} new titles.")


if __name__ == "__main__":
    main()
