"""
Shared OSM surface rule: is a way pavement or trail?
Used by generate_routes_from_osm.py and generate_trail_routes.py so both
pipelines agree on what counts as a trail.
"""

TRAIL_HIGHWAY_TAGS = {"path", "footway", "track", "bridleway"}

PAVED_SURFACES = {
    "paved", "asphalt", "concrete", "concrete:plates", "concrete:lanes",
    "paving_stones", "sett", "cobblestone", "bricks", "metal", "wood",
}
UNPAVED_SURFACES = {
    "unpaved", "dirt", "earth", "ground", "gravel", "fine_gravel", "compacted",
    "pebblestone", "grass", "sand", "mud", "woodchips", "rock",
}


def classify_surface(highway_tag, surface_tag, footway_tag=None):
    """Pavement vs. trail. An explicit OSM surface tag wins; when it's missing,
    fall back on the way type: footways are almost always sidewalks/paved
    paths, while path/track/bridleway are usually dirt."""
    if surface_tag in PAVED_SURFACES:
        return "pavement"
    if surface_tag in UNPAVED_SURFACES:
        return "trail"
    # untagged or unrecognized surface
    if footway_tag in ("sidewalk", "crossing") or highway_tag == "footway":
        return "pavement"
    return "trail"
