"""
LA places a runner can say they usually run (signup, Settings). Each spot is a rough circle
plus what it's like to run there, so Pathos can
  - learn their taste from day one (trail or road, scenic or not, flat or hilly), and
  - keep the picks from filling up with the places they already run all the time.

Centres are approximate; radii roughly cover each place. Tags describe the typical run there:
  surface: "trail" | "road" | "mixed"     scenic: True/False     hills: "flat" | "rolling" | "hilly"
"""
from typing import List, Optional

# key -> label, kind, lat, lon, radius km, surface, scenic, hills
SPOTS = {
    # parks, trails, paths
    "griffith-park":      ("Griffith Park", "park", 34.136, -118.294, 3.0, "trail", True, "hilly"),
    "rose-bowl":          ("Rose Bowl loop", "path", 34.161, -118.168, 1.2, "road", True, "flat"),
    "arroyo-seco":        ("Arroyo Seco", "trail", 34.140, -118.168, 2.0, "mixed", True, "rolling"),
    "silver-lake-res":    ("Silver Lake Reservoir", "path", 34.0935, -118.2635, 0.8, "road", True, "flat"),
    "echo-park-lake":     ("Echo Park Lake", "path", 34.0727, -118.2606, 0.6, "road", True, "flat"),
    "elysian-park":       ("Elysian Park", "park", 34.081, -118.240, 1.3, "mixed", True, "hilly"),
    "la-river":           ("LA River path", "path", 34.096, -118.248, 2.0, "road", True, "flat"),
    "runyon-canyon":      ("Runyon Canyon", "trail", 34.1105, -118.350, 0.9, "trail", True, "hilly"),
    "lake-hollywood":     ("Lake Hollywood", "path", 34.1265, -118.3285, 0.9, "road", True, "rolling"),
    "debs-park":          ("Debs Park", "park", 34.0915, -118.1985, 0.8, "trail", True, "hilly"),
    "eaton-canyon":       ("Eaton Canyon", "trail", 34.178, -118.097, 1.5, "trail", True, "hilly"),
    "hahamongna":         ("Hahamongna", "park", 34.200, -118.175, 1.2, "trail", True, "rolling"),
    "brand-park":         ("Brand Park", "park", 34.1825, -118.2745, 1.0, "trail", True, "hilly"),
    "verdugo-mountains":  ("Verdugo Mountains", "trail", 34.200, -118.270, 3.0, "trail", True, "hilly"),
    "lacy-park":          ("Lacy Park", "park", 34.1265, -118.1185, 0.5, "road", True, "flat"),
    "kenneth-hahn":       ("Kenneth Hahn Park", "park", 34.007, -118.367, 1.0, "trail", True, "hilly"),
    "santa-monica-beach": ("Santa Monica beach path", "beach", 34.010, -118.497, 3.0, "road", True, "flat"),
    "venice-beach":       ("Venice Beach", "beach", 33.985, -118.473, 1.5, "road", True, "flat"),
    "ballona-creek":      ("Ballona Creek path", "path", 33.995, -118.415, 3.0, "road", False, "flat"),
    # neighbourhood streets
    "eagle-rock":         ("Eagle Rock", "streets", 34.140, -118.212, 1.8, "road", False, "rolling"),
    "highland-park":      ("Highland Park", "streets", 34.115, -118.192, 1.8, "road", False, "rolling"),
    "glassell-park":      ("Glassell Park", "streets", 34.117, -118.233, 1.5, "road", False, "rolling"),
    "mount-washington":   ("Mount Washington", "streets", 34.103, -118.215, 1.3, "road", True, "hilly"),
    "atwater-village":    ("Atwater Village", "streets", 34.117, -118.257, 1.3, "road", False, "flat"),
    "silver-lake":        ("Silver Lake", "streets", 34.087, -118.270, 1.6, "road", False, "hilly"),
    "echo-park":          ("Echo Park", "streets", 34.078, -118.260, 1.4, "road", False, "hilly"),
    "los-feliz":          ("Los Feliz", "streets", 34.108, -118.287, 1.6, "road", False, "rolling"),
    "glendale":           ("Glendale", "streets", 34.155, -118.255, 4.0, "road", False, "rolling"),
    "pasadena":           ("Pasadena", "streets", 34.150, -118.140, 4.0, "road", False, "flat"),
    "south-pasadena":     ("South Pasadena", "streets", 34.116, -118.152, 1.6, "road", False, "flat"),
    "altadena":           ("Altadena", "streets", 34.190, -118.131, 2.5, "road", False, "hilly"),
    "la-canada":          ("La Cañada Flintridge", "streets", 34.199, -118.188, 2.8, "road", False, "hilly"),
    "burbank":            ("Burbank", "streets", 34.185, -118.315, 3.5, "road", False, "flat"),
    "lincoln-heights":    ("Lincoln Heights", "streets", 34.073, -118.207, 1.3, "road", False, "rolling"),
    "el-sereno":          ("El Sereno", "streets", 34.083, -118.180, 1.6, "road", False, "hilly"),
    "hollywood":          ("Hollywood", "streets", 34.098, -118.330, 2.5, "road", False, "flat"),
    "downtown":           ("Downtown LA", "streets", 34.045, -118.252, 2.0, "road", False, "flat"),
    "studio-city":        ("Studio City", "streets", 34.140, -118.387, 2.0, "road", False, "flat"),
}
POPULAR = ["griffith-park", "rose-bowl", "silver-lake-res", "arroyo-seco", "elysian-park", "eagle-rock"]
OFTEN, SOMETIMES = "often", "sometimes"


def spot_list() -> List[dict]:
    """The catalog for the app's search box."""
    return [{"key": k, "label": v[0], "kind": v[1], "popular": k in POPULAR} for k, v in SPOTS.items()]


def clean_spots(items) -> Optional[str]:
    """What's stored on the user: 'rose-bowl:often,eagle-rock:sometimes' (known keys only)."""
    out = []
    for it in items or []:
        key = it.get("key") if isinstance(it, dict) else None
        if key in SPOTS and key not in [o[0] for o in out]:
            out.append((key, OFTEN if it.get("often", it.get("freq")) in (True, OFTEN) else SOMETIMES))
    return ",".join(f"{k}:{f}" for k, f in out) or None


def parse_spots(stored: Optional[str]) -> List[dict]:
    """Stored string -> [{key, label, lat, lon, radius_km, often, surface, scenic, hills}]."""
    out = []
    for part in (stored or "").split(","):
        key, _, freq = part.partition(":")
        if key in SPOTS:
            label, kind, lat, lon, r, surface, scenic, hills = SPOTS[key]
            out.append({"key": key, "label": label, "kind": kind, "lat": lat, "lon": lon, "radius_km": r,
                        "often": freq == OFTEN, "surface": surface, "scenic": scenic, "hills": hills})
    return out


def spots_out(stored: Optional[str]) -> List[dict]:
    """For the app: [{key, label, often}]."""
    return [{"key": s["key"], "label": s["label"], "often": s["often"]} for s in parse_spots(stored)]


def spot_taste(spots: List[dict]) -> Optional[dict]:
    """What their usual places say they like. Spots run 'often' count double.
    {'trail': 0..1 share of trail running, 'scenic': 0..1, 'hilly': 0 (flat) .. 1 (hilly)}"""
    if not spots:
        return None
    total = trail = scenic = hilly = 0.0
    for s in spots:
        w = 2.0 if s["often"] else 1.0
        total += w
        trail += w * {"trail": 1.0, "mixed": 0.5}.get(s["surface"], 0.0)
        scenic += w * (1.0 if s["scenic"] else 0.0)
        hilly += w * {"flat": 0.0, "rolling": 0.5, "hilly": 1.0}[s["hills"]]
    return {"trail": trail / total, "scenic": scenic / total, "hilly": hilly / total}
