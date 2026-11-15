"""
Places the runner wants to stay away from, read from the check-in's free-text note
("I hate Glendale", "not Pasadena today", "avoid downtown"). Simple keyword rules,
no AI: a known place name with a "stay away" word just before it (or "... sucks" after).

Each place is matched by name (in the route's name) and by a rough circle around it,
so a route in Glendale is avoided even if its name says "Verdugo".
"""
import re
from typing import List, Tuple

# name -> (lat, lon, radius km). Centres are approximate; radii roughly cover each place.
PLACES = {
    "glendale": (34.155, -118.255, 4.0),
    "pasadena": (34.150, -118.140, 4.0),
    "south pasadena": (34.116, -118.152, 1.6),
    "burbank": (34.185, -118.315, 3.5),
    "eagle rock": (34.140, -118.212, 1.8),
    "highland park": (34.115, -118.192, 1.8),
    "glassell park": (34.117, -118.233, 1.5),
    "mount washington": (34.103, -118.215, 1.3),
    "mt washington": (34.103, -118.215, 1.3),
    "atwater village": (34.117, -118.257, 1.3),
    "atwater": (34.117, -118.257, 1.3),
    "silver lake": (34.087, -118.270, 1.6),
    "silverlake": (34.087, -118.270, 1.6),
    "echo park": (34.078, -118.260, 1.4),
    "los feliz": (34.108, -118.287, 1.6),
    "griffith park": (34.136, -118.294, 3.0),
    "griffith": (34.136, -118.294, 3.0),
    "elysian park": (34.081, -118.240, 1.3),
    "lincoln heights": (34.073, -118.207, 1.3),
    "el sereno": (34.083, -118.180, 1.6),
    "alhambra": (34.095, -118.127, 2.5),
    "altadena": (34.190, -118.131, 2.5),
    "la canada": (34.199, -118.188, 2.8),
    "la cañada": (34.199, -118.188, 2.8),
    "hollywood": (34.098, -118.330, 2.5),
    "downtown": (34.045, -118.252, 2.0),
    "dtla": (34.045, -118.252, 2.0),
    "studio city": (34.140, -118.387, 2.0),
    "toluca lake": (34.152, -118.354, 1.3),
    "rose bowl": (34.161, -118.168, 1.2),
    "arroyo": (34.140, -118.168, 2.0),
    "sunland": (34.262, -118.317, 2.5),
    "tujunga": (34.252, -118.288, 2.5),
}
AWAY_BEFORE = re.compile(r"(hate|avoid|avoiding|not|no|don'?t|do not|sick of|tired of|bored of|stay out of|"
                         r"away from|anything but|anywhere but|skip|never|without|other than|except)\b[^.,;!?]{0,25}$")
AWAY_AFTER = re.compile(r"^[^.,;!?]{0,12}\b(sucks|is the worst|is boring|is gross|is ugly)")


def avoided_places(note: str) -> List[str]:
    """Place names the note asks to avoid, e.g. 'I hate Glendale' -> ['glendale']."""
    if not note:
        return []
    text = note.lower()
    found = []
    for name in sorted(PLACES, key=len, reverse=True):          # "south pasadena" before "pasadena"
        for m in re.finditer(r"\b" + re.escape(name) + r"\b", text):
            before, after = text[:m.start()], text[m.end():]
            if any(name in f and name != f for f in found):       # part of a longer name already found
                continue
            if AWAY_BEFORE.search(before) or AWAY_AFTER.search(after):
                found.append(name)
                break
    return found


def place_circle(name: str) -> Tuple[float, float, float]:
    return PLACES[name]
