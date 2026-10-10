"""
Turns a street address into latitude/longitude using OpenStreetMap's
free Nominatim geocoding API. No API key required.
"""

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def geocode_address(address: str) -> tuple[float, float]:
    """Returns (latitude, longitude). Raises ValueError if not found."""
    response = httpx.get(
        NOMINATIM_URL,
        params={"q": address, "format": "json", "limit": 1},
        headers={"User-Agent": "run-recommender-app (student project)"},
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        raise ValueError(f"Could not geocode address: {address}")
    return float(results[0]["lat"]), float(results[0]["lon"])

# The area Pathos has routes for (same box as the routing map): roughly
# Santa Monica Mtns to the San Gabriel foothills, Long Beach to La Canada.
LA_VIEWBOX = "-118.49,34.382,-117.669,33.738"   # left,top,right,bottom


def geocode_la(address: str) -> tuple[float, float, str]:
    """Like geocode_address, but only accepts places inside Pathos's LA area.
    Returns (lat, lon, short label) or raises ValueError."""
    response = httpx.get(
        NOMINATIM_URL,
        params={"q": address, "format": "json", "limit": 1, "addressdetails": 1,
                "viewbox": LA_VIEWBOX, "bounded": 1, "countrycodes": "us"},
        headers={"User-Agent": "run-recommender-app (student project)"},
        timeout=15,
    )
    response.raise_for_status()
    results = response.json()
    if not results:
        raise ValueError(
            f"We couldn't find \"{address}\" in the Los Angeles area. Try a neighborhood "
            f"(like Eagle Rock or Highland Park) or a street address."
        )
    r = results[0]
    a = r.get("address", {})
    place = (a.get("neighbourhood") or a.get("suburb") or a.get("quarter")
             or a.get("city") or a.get("town") or r.get("name") or address)
    city = a.get("city") or a.get("town") or ""
    label = place if not city or city == place else f"{place}, {city}"
    return float(r["lat"]), float(r["lon"]), label
