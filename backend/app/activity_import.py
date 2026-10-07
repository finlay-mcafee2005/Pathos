"""
Read a run exported from a watch or running app (GPX, TCX or FIT) and
summarize it: distance, time, date, elevation gain, heart rate, and the
GPS track (used to match it to a Pathos route).

GPX and TCX are XML and parsed with the standard library. FIT is a binary
format; it needs the `fitdecode` package (pip install fitdecode).
"""

import io
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple


class ImportProblem(ValueError):
    """A problem with the file the user should see (bad format, no data...)."""


@dataclass
class TrackPoint:
    lat: float
    lon: float
    ele: Optional[float] = None
    time: Optional[datetime] = None
    hr: Optional[float] = None


@dataclass
class ActivitySummary:
    source_format: str
    start_time: Optional[datetime]
    distance_m: float
    duration_s: Optional[float]
    elevation_gain_m: Optional[float]
    avg_hr: Optional[float]
    max_hr: Optional[float]
    points: List[TrackPoint] = field(default_factory=list)


# --- helpers -----------------------------------------------------------------

def _meters(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _parse_time(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(el, name):
    return [c for c in el if _local(c.tag) == name]


def _first_text(el, name) -> Optional[str]:
    for c in el.iter():
        if _local(c.tag) == name and c.text:
            return c.text
    return None


def elevation_gain(points: List[TrackPoint]) -> Optional[float]:
    """Sum of climbs, ignoring wiggles under 3 m (GPS/barometer noise)."""
    eles = [p.ele for p in points if p.ele is not None]
    if len(eles) < 2:
        return None
    gain, base = 0.0, eles[0]
    for e in eles[1:]:
        if e - base >= 3:
            gain += e - base
            base = e
        elif e < base:
            base = e
    return round(gain, 1)


def summarize(points: List[TrackPoint], fmt: str, distance_m: Optional[float] = None,
              duration_s: Optional[float] = None, start: Optional[datetime] = None) -> ActivitySummary:
    if not points and not distance_m:
        raise ImportProblem("No GPS points or distance found in this file.")
    if distance_m is None:
        distance_m = sum(_meters((a.lat, a.lon), (b.lat, b.lon)) for a, b in zip(points, points[1:]))
    times = [p.time for p in points if p.time]
    if duration_s is None and len(times) >= 2:
        duration_s = (times[-1] - times[0]).total_seconds()
    hrs = [p.hr for p in points if p.hr]
    return ActivitySummary(
        source_format=fmt,
        start_time=start or (times[0] if times else None),
        distance_m=round(distance_m, 1),
        duration_s=round(duration_s) if duration_s else None,
        elevation_gain_m=elevation_gain(points),
        avg_hr=round(sum(hrs) / len(hrs)) if hrs else None,
        max_hr=round(max(hrs)) if hrs else None,
        points=points,
    )


# --- GPX ---------------------------------------------------------------------

def parse_gpx(data: bytes) -> ActivitySummary:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise ImportProblem("This GPX file couldn't be read.")
    points = []
    for el in root.iter():
        if _local(el.tag) != "trkpt":
            continue
        try:
            lat, lon = float(el.get("lat")), float(el.get("lon"))
        except (TypeError, ValueError):
            continue
        ele = _first_text(el, "ele")
        hr = None
        for c in el.iter():
            if _local(c.tag) in ("hr", "heartrate") and c.text:
                try:
                    hr = float(c.text)
                except ValueError:
                    pass
        points.append(TrackPoint(lat, lon, float(ele) if ele else None, _parse_time(_first_text(el, "time")), hr))
    if not points:
        raise ImportProblem("This GPX file has no track points. Is it a route instead of a recorded run?")
    return summarize(points, "gpx")


# --- TCX ---------------------------------------------------------------------

def parse_tcx(data: bytes) -> ActivitySummary:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise ImportProblem("This TCX file couldn't be read.")
    points, total_m, total_s, start = [], 0.0, 0.0, None
    has_laps = False
    for lap in root.iter():
        if _local(lap.tag) != "Lap":
            continue
        has_laps = True
        start = start or _parse_time(lap.get("StartTime"))
        for c in lap:
            if _local(c.tag) == "DistanceMeters" and c.text:
                total_m += float(c.text)
            elif _local(c.tag) == "TotalTimeSeconds" and c.text:
                total_s += float(c.text)
    for tp in root.iter():
        if _local(tp.tag) != "Trackpoint":
            continue
        lat = lon = None
        for c in tp.iter():
            name = _local(c.tag)
            if name == "LatitudeDegrees":
                lat = float(c.text)
            elif name == "LongitudeDegrees":
                lon = float(c.text)
        if lat is None or lon is None:
            continue
        ele = _first_text(tp, "AltitudeMeters")
        hr = None
        for c in tp.iter():
            if _local(c.tag) == "HeartRateBpm":
                v = _first_text(c, "Value")
                hr = float(v) if v else None
        points.append(TrackPoint(lat, lon, float(ele) if ele else None, _parse_time(_first_text(tp, "Time")), hr))
    return summarize(points, "tcx",
                     distance_m=total_m if has_laps and total_m > 0 else None,
                     duration_s=total_s if has_laps and total_s > 0 else None,
                     start=start)


# --- FIT ---------------------------------------------------------------------

SEMICIRCLE = 180 / 2 ** 31


def parse_fit(data: bytes) -> ActivitySummary:
    try:
        import fitdecode
    except ImportError:
        raise ImportProblem("FIT files need one extra package on the server: run `pip install fitdecode`. "
                            "GPX and TCX files work without it.")
    points, distance_m, duration_s, start = [], None, None, None
    try:
        with fitdecode.FitReader(io.BytesIO(data)) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                def get(name):
                    return frame.get_value(name, fallback=None)
                if frame.name == "record":
                    lat, lon = get("position_lat"), get("position_long")
                    if lat is None or lon is None:
                        continue
                    ele = get("enhanced_altitude") or get("altitude")
                    points.append(TrackPoint(lat * SEMICIRCLE, lon * SEMICIRCLE,
                                             float(ele) if ele is not None else None,
                                             get("timestamp"), get("heart_rate")))
                elif frame.name == "session":
                    distance_m = get("total_distance") or distance_m
                    duration_s = get("total_timer_time") or get("total_elapsed_time") or duration_s
                    start = get("start_time") or start
    except Exception:
        raise ImportProblem("This FIT file couldn't be read.")
    for p in points:
        if p.time and p.time.tzinfo is None:
            p.time = p.time.replace(tzinfo=timezone.utc)
    if start and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return summarize(points, "fit", distance_m=distance_m, duration_s=duration_s, start=start)


def parse_activity(filename: str, data: bytes) -> ActivitySummary:
    name = (filename or "").lower()
    if name.endswith(".fit") or data[8:12] == b".FIT":
        return parse_fit(data)
    if name.endswith(".tcx") or b"TrainingCenterDatabase" in data[:2000]:
        return parse_tcx(data)
    if name.endswith(".gpx") or b"<gpx" in data[:2000]:
        return parse_gpx(data)
    raise ImportProblem("Unsupported file. Export your run as a .fit, .gpx or .tcx file.")


# --- matching a track to a Pathos route --------------------------------------

def _xy(lat: float, lon: float, lat0: float) -> Tuple[float, float]:
    return lon * 111320 * math.cos(math.radians(lat0)), lat * 110540


def _resample(pts: List[Tuple[float, float]], n: int) -> List[Tuple[float, float]]:
    if len(pts) <= n:
        return pts
    step = (len(pts) - 1) / (n - 1)
    return [pts[round(i * step)] for i in range(n)]


def _near_fraction(a: List[Tuple[float, float]], b: List[Tuple[float, float]], tol_m: float) -> float:
    """Share of points in a that lie within tol_m of some point in b."""
    if not a or not b:
        return 0.0
    tol2 = tol_m * tol_m
    hits = 0
    for ax, ay in a:
        for bx, by in b:
            if (ax - bx) ** 2 + (ay - by) ** 2 <= tol2:
                hits += 1
                break
    return hits / len(a)


def match_route(track: List[Tuple[float, float]], routes: List[Tuple[str, str, List[Tuple[float, float]]]],
                tol_m: float = 40) -> Optional[dict]:
    """routes: [(route_id, name, [(lat, lon), ...])]. Returns the best match
    if the run covered most of the route and stayed on it most of the time."""
    if len(track) < 5:
        return None
    lat0 = track[0][0]
    t_xy = [_xy(la, lo, lat0) for la, lo in _resample(track, 300)]
    best = None
    for rid, name, path in routes:
        if len(path) < 2:
            continue
        r_xy = [_xy(la, lo, lat0) for la, lo in _resample(path, 200)]
        route_covered = _near_fraction(r_xy, t_xy, tol_m)     # did they run the whole route?
        on_route = _near_fraction(t_xy, r_xy, tol_m)          # did they stay on it?
        score = min(route_covered, on_route)
        if route_covered >= 0.8 and on_route >= 0.7 and (best is None or score > best["confidence"]):
            best = {"route_id": rid, "route_name": name, "confidence": round(score, 2),
                    "route_covered": round(route_covered, 2), "on_route": round(on_route, 2)}
    return best
