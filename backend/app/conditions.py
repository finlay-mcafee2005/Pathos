"""
Weather, air quality and daylight for a runner's location, from Open-Meteo
(free for non-commercial use, no API key).

    forecast:    https://api.open-meteo.com/v1/forecast
    air quality: https://air-quality-api.open-meteo.com/v1/air-quality

Everything here is best-effort: if a request fails or times out, the
functions return None and recommendations carry on without conditions.
"""

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
TIMEOUT_S = 4
CACHE_TTL_S = 30 * 60

# when the runner says they're heading out
RUN_TIME_HOURS = {"morning": 7, "midday": 12, "evening": 18}
RUN_TIME_ENDS = {"morning": 11, "midday": 15, "evening": 22}   # same cutoffs the check-in uses

_cache: dict = {}


@dataclass
class Conditions:
    target_time: str                         # local ISO time we looked up, e.g. "2026-10-07T18:00"
    run_time: str                            # "now" | "morning" | "midday" | "evening"
    temp_f: Optional[float] = None
    feels_like_f: Optional[float] = None
    uv_index: Optional[float] = None
    wind_mph: Optional[float] = None
    us_aqi: Optional[float] = None
    rain_last_48h_mm: float = 0.0
    sunset: Optional[str] = None             # local ISO time
    minutes_until_sunset: Optional[float] = None   # from the start of the run; negative = already dark
    is_tomorrow: bool = False                # the run time has passed today, so this is tomorrow's forecast
    now_temp_f: Optional[float] = None       # right now, for reference
    now_feels_like_f: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _get_json(url: str, params: dict) -> Optional[dict]:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    cached = _cache.get(full)
    if cached and time.time() - cached[0] < CACHE_TTL_S:
        return cached[1]
    try:
        with urllib.request.urlopen(full, timeout=TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        return None
    _cache[full] = (time.time(), data)
    return data


def _local_now(utc_offset_seconds: int) -> datetime:
    return (datetime.now(timezone.utc) + timedelta(seconds=utc_offset_seconds)).replace(tzinfo=None)


def target_hour(run_time: str, local_now: datetime) -> datetime:
    """The local hour the run will happen. 'now' = this hour; 'morning' etc.
    = later today (or tomorrow if that time has already passed);
    'tomorrow_morning' etc. = tomorrow."""
    run_time = run_time or "now"
    tomorrow = run_time.startswith("tomorrow_")
    base = run_time.removeprefix("tomorrow_")
    if base not in RUN_TIME_HOURS:
        return local_now.replace(minute=0, second=0, microsecond=0)
    this_hour = local_now.replace(minute=0, second=0, microsecond=0)
    t = this_hour.replace(hour=RUN_TIME_HOURS[base])
    if tomorrow or local_now.hour >= RUN_TIME_ENDS[base]:
        return t + timedelta(days=1)          # tomorrow, or today's window is over
    return max(t, this_hour)                  # still in (or before) today's window


def _value_at(hourly: dict, key: str, iso: str):
    try:
        return hourly[key][hourly["time"].index(iso)]
    except (KeyError, ValueError, IndexError, TypeError):
        return None


def parse_conditions(forecast: dict, air: Optional[dict], run_time: str,
                     local_now: Optional[datetime] = None) -> Optional[Conditions]:
    """Pure function (no network) so it can be tested with saved responses."""
    if not forecast or "hourly" not in forecast:
        return None
    now = local_now or _local_now(forecast.get("utc_offset_seconds", 0))
    t = target_hour(run_time, now)
    iso = t.strftime("%Y-%m-%dT%H:00")
    hourly = forecast["hourly"]

    cond = Conditions(target_time=iso, run_time=run_time or "now")
    cond.is_tomorrow = t.date() > now.date()
    now_iso = now.strftime("%Y-%m-%dT%H:00")
    cond.now_temp_f = _value_at(hourly, "temperature_2m", now_iso)
    cond.now_feels_like_f = _value_at(hourly, "apparent_temperature", now_iso)
    cond.temp_f = _value_at(hourly, "temperature_2m", iso)
    cond.feels_like_f = _value_at(hourly, "apparent_temperature", iso)
    cond.uv_index = _value_at(hourly, "uv_index", iso)
    cond.wind_mph = _value_at(hourly, "wind_speed_10m", iso)

    # rain that has actually fallen in the 48 hours before the run
    start = t - timedelta(hours=48)
    total = 0.0
    for ts, mm in zip(hourly.get("time", []), hourly.get("precipitation", [])):
        moment = datetime.fromisoformat(ts)
        if start <= moment <= min(t, now) and mm:
            total += mm
    cond.rain_last_48h_mm = round(total, 1)

    # sunset on the day of the run
    daily = forecast.get("daily", {})
    for day, sunset in zip(daily.get("time", []), daily.get("sunset", [])):
        if day == t.strftime("%Y-%m-%d"):
            cond.sunset = sunset
            run_start = now if run_time in (None, "", "now") else t
            cond.minutes_until_sunset = round((datetime.fromisoformat(sunset) - run_start).total_seconds() / 60)
            break

    if air and "hourly" in air:
        cond.us_aqi = _value_at(air["hourly"], "us_aqi", iso)
    return cond


def fetch_conditions(lat: Optional[float], lon: Optional[float], run_time: str = "now") -> Optional[Conditions]:
    if lat is None or lon is None:
        return None
    # round so nearby users share the cache
    lat, lon = round(lat, 2), round(lon, 2)
    forecast = _get_json(FORECAST_URL, {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,apparent_temperature,uv_index,wind_speed_10m,precipitation",
        "daily": "sunset",
        "past_days": 2,
        "forecast_days": 2,
        "timezone": "auto",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "mm",
    })
    if not forecast:
        return None
    air = _get_json(AIR_URL, {
        "latitude": lat,
        "longitude": lon,
        "hourly": "us_aqi",
        "past_days": 1,
        "forecast_days": 2,
        "timezone": "auto",
    })
    return parse_conditions(forecast, air, run_time)
