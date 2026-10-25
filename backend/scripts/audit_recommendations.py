"""
Recommendation audit: run the real engine on the real routes for a grid of
made-up runners and check-ins, and write every top 3 into one report, with
automatic flags for picks that look wrong.

Run from backend/ (reads routes only, never writes to the database):
    DATABASE_URL=... python3 scripts/audit_recommendations.py
Writes:
    scripts/audit_output/audit_report.md   - read this one
    scripts/audit_output/audit_picks.csv   - every pick, one row each (for sorting/filtering)
"""

import csv
import os
import sys
from collections import Counter
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlmodel import Session, create_engine, select

from app.models import Route
from app.conditions import Conditions
from app.scoring.engine import (match_pct, UserProfile, DailyCheckin, RecentRuns, recommend, diversify,
                                heat_distance_factor, haversine_km, climb_per_km)
from app.scoring.converters import build_route_candidates, route_start
from app.scoring.route_combiner import generate_combined_routes
from app.scoring.fallbacks import needs_gentler, add_gentler, GENTLE_EXTRA_KM, wants_challenge, add_challenge, drop_weak, weak_match_note

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:devpassword@localhost:5432/run_recommender")

USE_CACHE = "--cache" in sys.argv     # reuse the routes saved by the last database run (no DB needed)
if "DATABASE_URL" not in os.environ and not USE_CACHE:
    sys.exit("DATABASE_URL isn't set, so this would use your local database. In this Terminal window, run:\n"
             '  export DATABASE_URL="<your Supabase link>"\nthen run this script again.')
OUT_DIR = os.path.join(os.path.dirname(__file__), "audit_output")
MAX_DISTANCE_KM = 15          # same as main.py
MI = 1.60934
PERFECT_POINTS = 85          # same as the app's match % (RecommendationsPage.tsx)

HOMES = {
    "Eagle Rock (Oxy)": (34.1270, -118.2110),
    "Pasadena (Old Town)": (34.1460, -118.1500),
    "Glendale (downtown)": (34.1460, -118.2550),
    "Altadena": (34.1900, -118.1310),
    "Highland Park": (34.1110, -118.1920),
    "Silver Lake": (34.0870, -118.2700),
    "Echo Park": (34.0780, -118.2600),
    "Los Feliz": (34.1070, -118.2870),
    "Atwater Village": (34.1180, -118.2620),
    "South Pasadena": (34.1160, -118.1500),
    "East Pasadena": (34.1500, -118.0800),
    "La Canada Flintridge": (34.2000, -118.2000),
    "Montrose / La Crescenta": (34.2070, -118.2350),
    "Burbank": (34.1810, -118.3090),
    "Toluca Lake": (34.1520, -118.3500),
    "Sunland-Tujunga": (34.2550, -118.3000),
}

# app check-in travel chips: close to home = 2 mi, 15/30/45 min at ~20 mph
DAYS = {
    "rough":   dict(energy_score=3, sleep_hours=5.0, sleep_quality=2,
                    sore_body_parts=["left_quad", "right_hamstring", "left_calf", "right_knee", "lower_back"],
                    willing_to_drive_km=2 * MI),
    "average": dict(energy_score=6, sleep_hours=7.0, sleep_quality=3,
                    sore_body_parts=["left_calf"], willing_to_drive_km=10 * MI),
    "great":   dict(energy_score=9, sleep_hours=8.5, sleep_quality=5,
                    sore_body_parts=[], willing_to_drive_km=15 * MI),
}
DISTANCES_MI = [3, 5, 8]

RUNNER = dict(fitness_level="intermediate", weekly_km_avg=40.0, usual_pace_min_km=5.6)

HOT = Conditions(target_time="2026-07-15T13:00", run_time="midday", temp_f=95, feels_like_f=98,
                 uv_index=9, wind_mph=5, us_aqi=60)

# extra situations, each run at every home with a 5 mi plan on an average day
EXTRAS = {
    "hot day (98F)":       dict(conditions=HOT),
    "beginner":            dict(runner=dict(fitness_level="beginner", weekly_km_avg=10.0, usual_pace_min_km=7.0)),
    "avoid hills":         dict(hills_pref="avoid"),
    "quiet side streets":  dict(quiet_streets=True),
    "wants hills":         dict(hills_pref="want"),
    "scenic + trail":      dict(wants_scenic=True, surface_preference="trail"),
    "easy recovery run":   dict(run_intent="easy"),
    "great day, close to home": dict(day="great", willing_to_drive_km=2 * MI),
    "average day, close to home": dict(day="average", willing_to_drive_km=2 * MI),
    "knee injury (severe)": dict(runner=dict(fitness_level="intermediate", weekly_km_avg=40.0, usual_pace_min_km=5.6,
                                             active_injury_body_parts=["left_knee"], injury_severity={"left_knee": "severe"})),
}


def nearby(routes, lat, lon, radius_km):
    """Mirror of main.py: routes starting within the radius, plus the 12 closest if fewer than 3."""
    starts = {r.id: route_start(r) for r in routes}
    dist = {r.id: haversine_km(lat, lon, *starts[r.id]) for r in routes if starts[r.id][0] is not None}
    inside = [r for r in routes if dist.get(r.id, 1e9) <= radius_km]
    if len(inside) < 3:
        have = {r.id for r in inside}
        inside = inside + sorted([r for r in routes if r.id in dist and r.id not in have], key=lambda r: dist[r.id])[:12]
    return inside, dist


def run_scenario(routes, home, day, dist_mi, extra):
    lat, lon = HOMES[home]
    runner = dict(RUNNER, **extra.get("runner", {}))
    user = UserProfile(home_lat=lat, home_lon=lon, **runner)
    ck = dict(DAYS[day])
    ck.update({k: v for k, v in extra.items() if k not in ("runner", "conditions")})
    checkin = DailyCheckin(planned_distance_km=dist_mi * MI, today=date.today(),
                           run_time="midday" if "conditions" in extra else "evening", **ck)
    checkin.conditions = extra.get("conditions")
    recent = RecentRuns(last_7_days_km=runner["weekly_km_avg"] * 0.8)

    radius = checkin.willing_to_drive_km or MAX_DISTANCE_KM
    pool, dist = nearby(routes, lat, lon, radius)
    if not pool:
        return [], 0, radius
    results = recommend(user, checkin, recent, build_route_candidates(pool))
    if (not results or not results[0].distance_matched or results[0].run_format == "repeat") \
            and checkin.planned_distance_km:
        cut, _ = heat_distance_factor(checkin.conditions)
        combos = generate_combined_routes(pool, checkin.planned_distance_km * cut)
        if combos:
            more = recommend(user, checkin, recent, build_route_candidates(combos))
            results = diversify(results + more, 3, surface_requested=bool(checkin.surface_preference))
    if needs_gentler(results, user, checkin, recent):
        shown = {r.id for r in pool}
        wider = [r for r in routes if dist.get(r.id, 1e9) <= radius + GENTLE_EXTRA_KM and r.id not in shown]
        if wider:
            results = add_gentler(results, user, checkin, recent, build_route_candidates(wider))
    if wants_challenge(results, user, checkin, recent):
        results = add_challenge(results, user, checkin, recent, build_route_candidates(pool))
    if len(results) < 3:      # same as the app: always 3, filled from the closest routes
        shown = {r.route.id for r in results} | {str(r.id) for r in pool}
        more = sorted((r for r in routes if str(r.id) not in shown and r.id in dist), key=lambda r: dist[r.id])[:40]
        extra = recommend(user, checkin, recent, build_route_candidates(more), top_n=3, gate=False)
        results = results + extra[:3 - len(results)]
    return results, len(pool), radius


def flags_for(s, day, dist_mi, extra, home):
    f = []
    r = s.route
    target_mi = (s.target_km or dist_mi * MI) / MI
    run_mi = s.effective_distance_km / MI
    climb = s.run_gain_m or 0.0
    per_km = climb / s.effective_distance_km if s.effective_distance_km else 0
    beginner = extra.get("runner", {}).get("fitness_level") == "beginner"
    if abs(run_mi - target_mi) > max(0.5, 0.2 * target_mi):
        f.append(f"DISTANCE {run_mi:.1f} mi vs {target_mi:.1f} target")
    if day == "rough" and s.difficulty == "hard" and per_km >= 20:
        f.append("HARD (steep) on a rough day")
    if day == "rough" and per_km >= 30:
        f.append(f"STEEP on a rough day ({per_km:.0f} m/km)")
    if beginner and s.difficulty == "hard":
        f.append("HARD for a beginner")
    if extra.get("hills_pref") == "avoid" and per_km >= 20:
        f.append(f"HILLY despite 'avoid hills' ({per_km:.0f} m/km)")
    if extra.get("hills_pref") == "want" and per_km < 10:
        f.append(f"FLAT despite 'wants hills' ({per_km:.0f} m/km)")
    if extra.get("run_intent") == "easy" and per_km >= 25:
        f.append(f"STEEP for an easy run ({per_km:.0f} m/km)")
    if extra.get("surface_preference") == "trail" and r.surface_type not in ("trail", "mixed"):
        f.append(f"NOT TRAIL ({r.surface_type})")
    if "knee" in str(extra.get("runner", {})) and r.surface_type == "pavement" and "injury" not in s.breakdown:
        f.append("PAVEMENT with knee injury (no injury penalty applied)")
    if extra.get("conditions") is HOT and (r.shade or 0) < 0.1 and run_mi >= 3:
        f.append(f"NO SHADE on a 98F day ({(r.shade or 0):.0%})")
    if r.surface_type == "unknown":
        f.append("surface unknown")
    if s.score < 100:
        f.append(f"NEGATIVE score ({s.score - 100:+.0f})")
    return f


def _fam(name):
    from app.scoring.engine import route_family
    return route_family(name)


def _by_scn(rows):
    out = {}
    for r in rows:
        out.setdefault((r["home"], r["scenario"]), []).append(r)
    return out


def responsiveness(rows):
    by = {}
    for r in rows:
        by.setdefault((r["home"], r["scenario"]), []).append(r)
    out, shared_ag, shared_ra, n = [], 0, 0, 0
    for home in HOMES:
        for d in DISTANCES_MI:
            day = {k: by.get((home, f"{k} day, {d} mi"), []) for k in DAYS}
            names = {k: {x["route"] for x in v} for k, v in day.items()}
            climb = {k: (sum(x["climb_ft"] for x in v) / len(v) if v else 0) for k, v in day.items()}
            ag, ra = len(names["average"] & names["great"]), len(names["rough"] & names["average"])
            shared_ag += ag
            shared_ra += ra
            n += 1
            out.append(f"- {home}, {d} mi: average/great share {ag}/3, rough/average share {ra}/3; "
                       f"avg climb rough {climb['rough']:.0f} ft, average {climb['average']:.0f} ft, "
                       f"great {climb['great']:.0f} ft")
    for home in HOMES:
        names = {k: {x["route"] for x in by.get((home, k), [])} for k in
                 ("rough day, 5 mi", "average day, close to home, 5 mi", "great day, close to home, 5 mi")}
        out.append(f"- {home}, 5 mi, everyone staying close to home: rough/great share "
                   f"{len(names['rough day, 5 mi'] & names['great day, close to home, 5 mi'])}/3, "
                   f"average/great share {len(names['average day, close to home, 5 mi'] & names['great day, close to home, 5 mi'])}/3")
    out.insert(0, f"**Overall: average vs great share {shared_ag / max(1, n):.1f} of 3 routes; "
                  f"rough vs average {shared_ra / max(1, n):.1f} of 3.**")
    out.insert(1, "")
    return out


CACHE = os.path.join(OUT_DIR, "routes_cache.pkl")
ROUTE_FIELDS = ["id", "name", "nickname", "hidden", "distance_km", "elevation_gain_m", "elevation_loss_m",
                "shade_pct", "scenic_pct", "surface_type", "difficulty", "scenic",
                "busy_pct", "freeway_crossings", "downtown_pct", "turns_per_km", "stem_km"]


def load_routes():
    """Routes from the database (and saved to a local cache), or from that cache with --cache."""
    import pickle
    from types import SimpleNamespace
    if USE_CACHE:
        with open(CACHE, "rb") as f:
            routes = [SimpleNamespace(**d) for d in pickle.load(f)]
        print(f"{len(routes)} routes loaded (cache)")
        return routes
    from app.scoring.route_combiner import get_route_coords
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with Session(engine) as session:
        routes = session.exec(select(Route).where(Route.hidden.is_not(True))).all()
        for r in routes:                      # load geometry now, then drop the connection
            _ = r.gps_path
        session.expunge_all()
    print(f"{len(routes)} routes loaded (database: {DATABASE_URL.split('@')[-1].split('/')[0]})")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump([dict({k: getattr(r, k) for k in ROUTE_FIELDS}, coords=get_route_coords(r)) for r in routes], f)
    return routes


def main():
    routes = load_routes()

    scenarios = []
    for home in HOMES:
        for day in DAYS:
            for d in DISTANCES_MI:
                scenarios.append((f"{day} day, {d} mi", home, day, d, {}))
        for name, extra in EXTRAS.items():
            day = extra.get("day", "average")
            scenarios.append((f"{name}, 5 mi", home, day, 5, {k: v for k, v in extra.items() if k != "day"}))

    rows, sections, appear, flag_count = [], [], Counter(), Counter()
    for i, (label, home, day, d, extra) in enumerate(scenarios, 1):
        try:
            picks, n_pool, radius = run_scenario(routes, home, day, d, extra)
        except Exception as ex:
            sections.append(f"### {home} - {label}\n\n**ERROR:** {type(ex).__name__}: {ex}\n")
            flag_count["ERROR"] += 1
            continue
        lines = [f"### {home} - {label}",
                 f"_{n_pool} routes within {radius / MI:.0f} mi of home_", ""]
        if not picks:
            lines.append("**No recommendations.**")
            flag_count["NO PICKS"] += 1
        for rank, s in enumerate(picks, 1):
            r = s.route
            fl = flags_for(s, day, d, extra, home)
            for x in fl:
                flag_count[x.split(" (")[0].split(" ")[0] if x.startswith(("DISTANCE", "NEGATIVE")) else x.split(" (")[0]] += 1
            appear[r.name] += 1
            climb_ft = (s.run_gain_m or 0) * 3.281
            top = sorted(s.breakdown.items(), key=lambda kv: -abs(kv[1]))[:4]
            match = match_pct(s.score, s.perfect_points)
            lines.append(
                f"{rank}. **{r.name}** - {s.effective_distance_km / MI:.1f} mi ({s.run_format}"
                f"{' x' + str(s.repeat_count) if s.run_format == 'repeat' else ''}), "
                f"{climb_ft:.0f} ft climb, {s.difficulty}, {r.surface_type}, "
                f"shade {('%.0f%%' % (r.shade * 100)) if r.shade is not None else 'n/a'}, "
                f"~{s.estimated_minutes} min, match {match}%")
            lines.append("   - points: " + ", ".join(f"{k} {v:+.0f}" for k, v in top))
            if match < 50:
                lines.append(f"   - card note: {weak_match_note(s)}")
            if fl:
                lines.append("   - **FLAG: " + "; ".join(fl) + "**")
            rows.append({"home": home, "scenario": label, "rank": rank, "route": r.name,
                         "miles": round(s.effective_distance_km / MI, 2), "format": s.run_format,
                         "climb_ft": round(climb_ft), "difficulty": s.difficulty,
                         "surface": r.surface_type, "shade": r.shade, "minutes": s.estimated_minutes,
                         "match_pct": match, "flags": "; ".join(fl),
                         "breakdown": "; ".join(f"{k} {v:+.1f}" for k, v in s.breakdown.items())})
        sections.append("\n".join(lines) + "\n")
        if i % 10 == 0:
            print(f"  {i}/{len(scenarios)} scenarios")

    total_picks = len(rows)
    max_reach = max(d.get("willing_to_drive_km") or MAX_DISTANCE_KM for d in DAYS.values())
    reachable = 0
    for r in routes:
        lat, lon = route_start(r)
        if lat is not None and any(haversine_km(hl, hn, lat, lon) <= max_reach for hl, hn in HOMES.values()):
            reachable += 1
    flagged = sum(1 for r in rows if r["flags"])
    summary = [
        "# Recommendation audit", "",
        f"{len(scenarios)} scenarios x top 3 = {total_picks} picks, from {len(routes)} routes. "
        f"Runner: intermediate, 25 mi/week, ~9:00/mi unless stated.", "",
        f"**{flagged} picks flagged.** Flags are automatic hints, not verdicts: read the pick and decide.", "",
        "## Flag counts", "",
    ] + [f"- {k}: {v}" for k, v in flag_count.most_common()] + [
        "", "## Routes that show up most (same route everywhere = possible bias)", "",
    ] + [f"- {name}: {n} of {len(scenarios)} scenarios" for name, n in appear.most_common(12)] + [
        "", "## Does the day change the picks? (same home and distance)", "",
        "Shared routes in the top 3 (0/3 = completely different, 3/3 = identical), and average climb.", "",
    ] + responsiveness(rows) + [
        "", "## What kind of routes get picked", "",
        f"- Pavement: {sum(1 for r in rows if r['surface'] == 'pavement')} of {len(rows)} picks; "
        f"trail: {sum(1 for r in rows if r['surface'] == 'trail')}; mixed: {sum(1 for r in rows if r['surface'] == 'mixed')}",
        f"- Generated street loops ('... via ...'): {sum(1 for r in rows if ' via ' in r['route'])} of {len(rows)}",
        f"- Top 3 lists with two loops from the same family (e.g. two 'Oxy Loop via ...'): "
        f"{sum(1 for v in _by_scn(rows).values() if len({_fam(x['route']) for x in v}) < len(v))} of {len(_by_scn(rows))}",
        "", f"Catalog coverage: {len(appear)} different routes were picked; "
            f"{reachable} routes start within reach of at least one test home "
            f"({len(appear) / max(1, reachable):.0%} of those got picked).",
        "", f"{len(appear)} different routes were recommended at least once "
            f"({len(appear) / max(1, len(routes)):.0%} of the catalog).", "",
        "## Every scenario", "",
    ]
    os.makedirs(OUT_DIR, exist_ok=True)
    report = os.path.join(OUT_DIR, "audit_report.md")
    with open(report, "w") as f:
        f.write("\n".join(summary) + "\n" + "\n".join(sections))
    with open(os.path.join(OUT_DIR, "audit_picks.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["none"])
        w.writeheader()
        w.writerows(rows)
    print(f"\n{flagged} of {total_picks} picks flagged. Report: {report}")


if __name__ == "__main__":
    main()
