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