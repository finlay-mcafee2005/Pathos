"""
Names for the generated long loops, in the house style: at most four words, no
distances, every name different. Instead of "Old Pasadena Long Loop (13.1 mi)" x14,
each loop is named for its area plus the street, park or river it runs along most:
"Eagle Rock Colorado Loop", "Atwater LA River Loop", "Pasadena Arroyo Loop".

Updates route.nickname for routes whose name has "Long Loop" in it.
    DATABASE_URL=... python3 scripts/name_long_loops.py --dry-run
    DATABASE_URL=... python3 scripts/name_long_loops.py
    python3 scripts/name_long_loops.py --json        # test on .shade_cache/long_loops.json
"""
import math
import os
import pickle
import re
import sys
from collections import Counter

from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from shorten_route_names import core, PLACE_SUBS, STREET_SUFFIX, MAX_WORDS, nwords  # noqa: E402

KX, KY = 111320 * math.cos(math.radians(34.15)), 110540
GENERIC = {"service road", "driveway", "alley", "path", "trail", "footpath", "sidewalk", "crosswalk"}
FEATURE_SUBS = [(r".*Los Angeles River.*", "LA River"), (r".*Arroyo Seco.*", "Arroyo"), (r".*Motorway$", None)]
# words that don't name anything on their own ("Avenue" from "Avenue 64")
NOT_A_NAME = {"avenue", "street", "trail", "path", "road", "drive", "way", "lane", "place", "boulevard",
              "mountain", "fire", "seco", "round", "north", "south", "east", "west", "old", "new", "upper",
              "lower", "service", "access", "connector", "bridge", "park"}


def m(lon, lat):
    return lon * KX, lat * KY


def load_network():
    d = pickle.load(open(os.path.join(HERE, ".shade_cache", "network.pkl"), "rb"))
    lines, names = [], []
    for u, v, length, hw, surface, name, coords in d["edges"]:
        if name and name.lower() not in GENERIC:
            lines.append(LineString([m(*c) for c in coords]))
            names.append(name)
    return lines, names, STRtree(lines), d["places"]


def feature_word(name):
    """'Colorado Boulevard' -> 'Colorado'; 'Los Angeles River Bike Path' -> 'LA River'."""
    for pat, rep in FEATURE_SUBS:
        if re.match(pat, name):
            if rep is None:
                return None
            return rep
    for pat, rep in PLACE_SUBS:
        name = re.sub(pat, rep, name)
    if any(ch.isdigit() for ch in name):
        return None                          # "Avenue 64", "Route 2"
    name = STREET_SUFFIX.sub("", name).strip()
    words = [w for w in name.split() if w.lower() not in ("n", "s", "e", "w")]
    if not words:
        return None
    w = " ".join(words[:2]) if words[0].lower() in ("la", "mount", "mt", "san", "santa", "el", "los", "eagle") \
        and len(words) > 1 else words[0]
    return None if w.lower() in NOT_A_NAME or len(w) < 3 else w


def features(coords, net):
    """Named streets / paths the route runs along, longest first."""
    lines, names, tree, _ = net
    line = LineString([m(*c) for c in coords])
    L = line.length
    count = Counter()
    for k in range(0, int(L), 25):
        p = line.interpolate(k)
        best = None
        for i in tree.query(p.buffer(15)):
            d = lines[int(i)].distance(p)
            if d <= 15 and (best is None or d < best[0]):
                best = (d, names[int(i)])
        if best:
            count[best[1]] += 25
    out = []
    for name, metres in count.most_common():
        w = feature_word(name)
        if w and w not in out:
            out.append(w)
    return out


def area(place):
    words = place.split()
    if words and words[0].lower() in ("old", "rancho") and len(words) > 1:
        words = words[1:]                    # "Old Pasadena" -> "Pasadena", "Rancho San Rafael" -> "San Rafael"
    if len(words) <= 2:
        return " ".join(words)               # "Adams Square", "Eagle Rock"
    return core(" ".join(words), 1)


def make_name(place, feats, taken):
    a = area(place)
    for f in feats[:6]:
        if f.lower() in a.lower():
            continue
        title = f"{a} {f} Loop"
        if nwords(title) <= MAX_WORDS and title not in taken:
            return title
    for d in ("North", "South", "East", "West", "Big", "Grand"):
        title = f"{a} {d} Loop"
        if nwords(title) <= MAX_WORDS and title not in taken:
            return title
    return f"{a} Loop"


def place_of(name):
    n = re.sub(r"\s*\(.*$", "", name)
    n = re.sub(r"\s*#\d+$", "", n)
    return re.sub(r"\s+Long Loop.*$", "", n).strip()


def main():
    net = load_network()
    if "--json" in sys.argv:
        import json
        rows = [(i, r["name"], r["coords"]) for i, r in
                enumerate(json.load(open(os.path.join(HERE, ".shade_cache", "long_loops.json")))["routes"])]
        taken = set()
    else:
        if "DATABASE_URL" not in os.environ:
            sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
        from sqlalchemy import create_engine, text
        engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
        with engine.connect() as conn:
            all_rows = conn.execute(text("SELECT id, COALESCE(nickname, name), ST_AsText(gps_path), "
                                         "COALESCE(hidden, FALSE) FROM route")).all()
        taken = {n for _, n, _, hidden in all_rows if not hidden and "long loop" not in n.lower()}
        rows = [(rid, n, [tuple(map(float, p.split())) for p in w[w.index("(") + 1:-1].split(",")])
                for rid, n, w, hidden in all_rows if not hidden and "long loop" in n.lower()]
    changes = []
    for rid, old, coords in rows:
        new = make_name(place_of(old), features(coords, net), taken)
        taken.add(new)
        changes.append((rid, old, new))
    for _, old, new in changes[:40]:
        print(f"  {old:<45} -> {new}")
    print(f"{len(changes)} long loops renamed; longest name {max((nwords(n) for *_, n in changes), default=0)} words; "
          f"{len(changes) - len({n for *_, n in changes})} duplicates.")
    if "--dry-run" in sys.argv or "--json" in sys.argv:
        print("Nothing saved.")
        return
    with engine.begin() as conn:
        for rid, _, new in changes:
            conn.execute(text("UPDATE route SET nickname = :n WHERE id = :id"), {"n": new, "id": rid})
    print("Saved.")


if __name__ == "__main__":
    main()
