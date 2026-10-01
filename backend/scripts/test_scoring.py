"""
Standalone sanity check for the scoring engine - no database required.
Run with:  python scripts/test_scoring.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date, timedelta

from app.scoring.engine import (
    UserProfile, DailyCheckin, RecentRuns, RouteCandidate, recommend,
)
from app.scoring.personalization import RunRecord


CANDIDATE_ROUTES = [
    RouteCandidate(id="r1", name="Riverside flat loop", distance_km=5.0,
                    elevation_gain_m=20, difficulty="easy",
                    surface_type="pavement", scenic=True, is_loop=True),
    RouteCandidate(id="r2", name="Park hill repeats", distance_km=8.0,
                    elevation_gain_m=180, difficulty="hard",
                    surface_type="pavement", scenic=False),
    RouteCandidate(id="r3", name="Neighborhood tempo route", distance_km=10.0,
                    elevation_gain_m=60, difficulty="moderate",
                    surface_type="mixed", scenic=False),
    RouteCandidate(id="r4", name="Trail out-and-back", distance_km=12.0,
                    elevation_gain_m=220, difficulty="hard",
                    surface_type="trail", scenic=True),
    RouteCandidate(id="r5", name="Track intervals", distance_km=6.0,
                    elevation_gain_m=0, difficulty="moderate",
                    surface_type="track", scenic=False, is_loop=True),
    RouteCandidate(id="r6", name="Arroyo dirt loop", distance_km=6.5,
                    elevation_gain_m=90, difficulty="moderate",
                    surface_type="trail", scenic=True, is_loop=True),
]


def print_results(title, results):
    print(f"\n=== {title} ===")
    for s in results:
        reason_str = "; ".join(s.reasons) if s.reasons else "no strong signals"
        print(f"  {s.route.name:<26} [{s.route.surface_type:<8}] score={s.score:>6.1f}   {reason_str}")
        print(f"  {'':<26}            {s.breakdown}")


def run(user, checkin, recent=None):
    recent = recent or RecentRuns(last_7_days_km=user.weekly_km_avg * 0.8)
    return recommend(user, checkin, recent, CANDIDATE_ROUTES, top_n=len(CANDIDATE_ROUTES))


INTERMEDIATE = UserProfile(fitness_level="intermediate", weekly_km_avg=30)

SCENARIOS = [
    ("Baseline, no surface signals",
     INTERMEDIATE, DailyCheckin(energy_score=6)),
    ("Sore left shin -> trails/track should rise, pavement drop",
     INTERMEDIATE, DailyCheckin(energy_score=6, sore_body_parts=["left_shin"])),
    ("Sore right calf -> pavement/track should rise, trails drop",
     INTERMEDIATE, DailyCheckin(energy_score=6, sore_body_parts=["right_calf"])),
    ("Active knee injury -> pavement heavily penalized",
     UserProfile(fitness_level="advanced", weekly_km_avg=40,
                 active_injury_body_parts=["left_knee"]),
     DailyCheckin(energy_score=7)),
    ("Wants road",
     INTERMEDIATE, DailyCheckin(energy_score=6, surface_preference="road")),
    ("Wants trail",
     INTERMEDIATE, DailyCheckin(energy_score=6, surface_preference="trail")),
    ("4.5h sleep -> trails nudged down",
     INTERMEDIATE, DailyCheckin(energy_score=6, sleep_hours=4.5)),
    ("Wants trail but slept 4.5h -> explicit preference should still win",
     INTERMEDIATE, DailyCheckin(energy_score=6, sleep_hours=4.5, surface_preference="trail")),
    ("Wants trail but sore calf -> soreness outweighs preference",
     INTERMEDIATE, DailyCheckin(energy_score=6, surface_preference="trail",
                                sore_body_parts=["left_calf"])),
]


def check_scoring():
    print("\n=== Scoring checks ===")
    user = INTERMEDIATE

    # 1. no exact ties: in every scenario, distinct routes get distinct scores
    for title, u, checkin in SCENARIOS:
        scores = [r.score for r in run(u, checkin)]
        assert len(set(scores)) == len(scores), f"tie in '{title}': {scores}"
    print(f"  no ties across all {len(SCENARIOS)} scenarios")

    # 2. recency: two identical routes, one run 2 days ago, one 25 days ago
    twin_a = RouteCandidate(id="twinA", name="Twin A", distance_km=5.0, elevation_gain_m=50,
                            difficulty="easy", surface_type="pavement", is_loop=True)
    twin_b = RouteCandidate(id="twinB", name="Twin B", distance_km=5.0, elevation_gain_m=50,
                            difficulty="easy", surface_type="pavement", is_loop=True)
    recent = RecentRuns(last_7_days_km=24, days_since_last_run_by_route_id={"twinA": 2, "twinB": 25})
    res = recommend(user, DailyCheckin(energy_score=6), recent, [twin_a, twin_b])
    assert [r.route.id for r in res] == ["twinB", "twinA"] and res[0].score > res[1].score
    print(f"  recency: route run 25 days ago ({res[0].score}) beats one run 2 days ago ({res[1].score})")

    # 3. distance is graded: 0.2 km off beats 1.2 km off (both 'within tolerance')
    near = RouteCandidate(id="near", name="Near", distance_km=8.2, elevation_gain_m=60,
                          difficulty="moderate", surface_type="pavement", is_loop=True)
    far = RouteCandidate(id="far", name="Far", distance_km=9.2, elevation_gain_m=69,
                         difficulty="moderate", surface_type="pavement", is_loop=True)
    res = recommend(user, DailyCheckin(energy_score=6, planned_distance_km=8.0),
                    RecentRuns(last_7_days_km=24), [far, near])
    assert res[0].route.id == "near" and res[0].score > res[1].score
    print(f"  distance: 0.2 km off ({res[0].score}) beats 1.2 km off ({res[1].score})")

    # 4. readiness: fresh runner prefers the hilly route, tired runner the flat one
    flat = RouteCandidate(id="flat", name="Flat", distance_km=7.0, elevation_gain_m=20,
                          difficulty="moderate", surface_type="pavement", is_loop=True)
    hilly = RouteCandidate(id="hilly", name="Hilly", distance_km=7.0, elevation_gain_m=280,
                           difficulty="moderate", surface_type="pavement", is_loop=True)
    fresh = recommend(user, DailyCheckin(energy_score=9, sleep_hours=8.5, sleep_quality=5),
                      RecentRuns(last_7_days_km=20), [flat, hilly])
    tired = recommend(user, DailyCheckin(energy_score=2, sleep_hours=5, sleep_quality=2),
                      RecentRuns(last_7_days_km=20), [flat, hilly])
    assert fresh[0].route.id == "hilly" and tired[0].route.id == "flat"
    print("  readiness: fresh -> hilly first, tired -> flat first")

    # 5. units: 30 mi/week runner (48 km) logging 40 km is NOT overloaded
    runner = UserProfile(fitness_level="intermediate", weekly_km_avg=30 * 1.60934)
    res = recommend(runner, DailyCheckin(energy_score=6), RecentRuns(last_7_days_km=40), [flat])
    assert "overload" not in res[0].breakdown
    # and zero weekly mileage doesn't crash
    recommend(UserProfile(fitness_level="beginner", weekly_km_avg=0),
              DailyCheckin(energy_score=6), RecentRuns(last_7_days_km=10), [flat])
    print("  units: miles converted correctly; 0 weekly mileage handled")

    # 6. determinism under shuffled input
    import random
    base = [r.route.id for r in run(user, DailyCheckin(energy_score=6))]
    for _ in range(20):
        shuffled = CANDIDATE_ROUTES[:]
        random.shuffle(shuffled)
        got = [r.route.id for r in recommend(user, DailyCheckin(energy_score=6),
                                             RecentRuns(last_7_days_km=24), shuffled, top_n=6)]
        assert got == base
    print("  determinism: same order across 20 shuffles")
    print("  all scoring checks passed")


THURSDAY = date(2026, 10, 1)
SATURDAY = date(2026, 10, 3)


def rec(days_ago, km, route=None, rating=None, soreness=None, pace=6.0, today=THURSDAY, hill=None):
    """Build a RunRecord on one of the candidate routes."""
    r = next((c for c in CANDIDATE_ROUTES if c.id == route), None)
    return RunRecord(
        run_date=today - timedelta(days=days_ago), distance_km=km, pace_min_km=pace,
        rating=rating, post_run_soreness=soreness, route_id=route,
        surface_type=r.surface_type if r else None,
        hill_m_per_km=hill if hill is not None else ((r.elevation_gain_m / r.distance_km) if r else None),
        scenic=r.scenic if r else None, is_loop=r.is_loop if r else None,
    )


def recent_from(history, last_7_days_km=20, today=THURSDAY):
    """RecentRuns the way converters.py builds it from the database."""
    ratings, last = {}, {}
    for r in history:
        if r.route_id and r.rating is not None:
            ratings.setdefault(r.route_id, []).append(r.rating)
        if r.route_id:
            last[r.route_id] = max(last.get(r.route_id, r.run_date), r.run_date)
    return RecentRuns(
        last_7_days_km=last_7_days_km, history=history,
        last_14_days_route_ids=[rid for rid, d in last.items() if (today - d).days <= 14],
        avg_rating_by_route_id={k: sum(v) / len(v) for k, v in ratings.items()},
        days_since_last_run_by_route_id={k: (today - d).days for k, d in last.items()},
    )


def check_personalization():
    print("\n=== Personalization checks (same check-in, different runners) ===")
    checkin = DailyCheckin(energy_score=6, sleep_hours=7.5, today=THURSDAY)
    user = INTERMEDIATE

    # 1. taste: trail-lover vs road-lover get different top picks
    trail_lover = [rec(d, 6, "r6", 5) for d in (5, 12, 20)] + [rec(d, 5, "r1", 2) for d in (8, 15, 25)]
    road_lover = [rec(d, 6, "r6", 2) for d in (5, 12, 20)] + [rec(d, 5, "r1", 5) for d in (8, 15, 25)]
    a = recommend(user, checkin, recent_from(trail_lover), CANDIDATE_ROUTES, top_n=6)
    b = recommend(user, checkin, recent_from(road_lover), CANDIDATE_ROUTES, top_n=6)
    ra = [x.route.id for x in a]; rb = [x.route.id for x in b]
    assert ra.index("r6") < ra.index("r1") and rb.index("r1") < rb.index("r6"), (ra, rb)
    print(f"  taste: trail-lover top = {a[0].route.name}; road-lover top = {b[0].route.name}")

    # 2. recovery: sorer after hilly runs -> flatter routes favored
    flat = RouteCandidate(id="flat", name="Flat", distance_km=7.0, elevation_gain_m=35,
                          difficulty="moderate", surface_type="pavement", is_loop=True)
    hilly = RouteCandidate(id="hilly", name="Hilly", distance_km=7.0, elevation_gain_m=250,
                           difficulty="moderate", surface_type="pavement", is_loop=True)
    hill_hist = [rec(4, 8, "r2", soreness=8, hill=35), rec(11, 8, "r2", soreness=7, hill=35),
                 rec(18, 8, "r2", soreness=8, hill=35),
                 rec(7, 5, "r1", soreness=2), rec(14, 5, "r1", soreness=3), rec(21, 5, "r1", soreness=2)]
    fresh = DailyCheckin(energy_score=9, sleep_hours=8.5, sleep_quality=5, today=THURSDAY)
    plain = recommend(user, fresh, RecentRuns(last_7_days_km=20), [flat, hilly], top_n=2)
    sore = recommend(user, fresh, recent_from(hill_hist), [flat, hilly], top_n=2)
    assert plain[0].route.id == "hilly" and sore[0].route.id == "flat", (plain, sore)
    print(f"  recovery: no history -> Hilly first; sore-after-hills history -> Flat first ({sore[0].reasons})")

    # 3. rhythm: long hard run yesterday -> easier day
    yesterday_long = [rec(1, 16, pace=5.4), rec(3, 6), rec(6, 7), rec(9, 6)]
    r = recommend(user, fresh, recent_from(yesterday_long, 29), [flat, hilly], top_n=2)
    assert r[0].route.id == "flat" and any("yesterday" in x for x in r[0].reasons), r[0].reasons
    print(f"  rhythm: day after a 16 km run -> {r[0].route.name} first ({r[0].reasons[-1]})")

    # 4. goal: race training on a Saturday aims for a longer run than general fitness
    short = RouteCandidate(id="short", name="10 km loop", distance_km=10.0, elevation_gain_m=100,
                           difficulty="hard", surface_type="pavement", is_loop=True)
    long_ = RouteCandidate(id="long", name="14 km loop", distance_km=14.0, elevation_gain_m=140,
                           difficulty="hard", surface_type="pavement", is_loop=True)
    sat = DailyCheckin(energy_score=8, sleep_hours=8, today=SATURDAY)
    racer = UserProfile(fitness_level="intermediate", weekly_km_avg=36, goal="race_training")
    thu = recommend(racer, DailyCheckin(energy_score=8, sleep_hours=8, today=THURSDAY),
                    RecentRuns(last_7_days_km=25), [short, long_], top_n=2)
    weekend = recommend(racer, sat, RecentRuns(last_7_days_km=25), [short, long_], top_n=2)
    assert thu[0].route.id == "short" and weekend[0].route.id == "long", (thu, weekend)
    print(f"  goal: racer on Thursday -> {thu[0].route.name}; on Saturday -> {weekend[0].route.name}")

    # 5. proximity: identical routes, the one near home wins
    home = UserProfile(fitness_level="intermediate", weekly_km_avg=30, home_lat=34.1271, home_lon=-118.2109)
    near = RouteCandidate(id="nearhome", name="Near home", distance_km=6, elevation_gain_m=60,
                          difficulty="moderate", surface_type="pavement", is_loop=True,
                          start_lat=34.1280, start_lon=-118.2100)
    far = RouteCandidate(id="farhome", name="Across town", distance_km=6, elevation_gain_m=60,
                         difficulty="moderate", surface_type="pavement", is_loop=True,
                         start_lat=34.1950, start_lon=-118.1500)
    r = recommend(home, checkin, RecentRuns(last_7_days_km=20), [far, near], top_n=2)
    assert r[0].route.id == "nearhome"
    print(f"  proximity: {r[0].route.name} ({r[0].breakdown['proximity']}) beats {r[1].route.name} ({r[1].breakdown.get('proximity', 0)})")

    # 6. variety: two near-copies of one loop + a different route -> top 3 isn't two copies first
    north = RouteCandidate(id="loopN", name="Rose Bowl loop north", distance_km=8.0, elevation_gain_m=96,
                           difficulty="moderate", surface_type="pavement", is_loop=True,
                           start_lat=34.1613, start_lon=-118.1676)
    south = RouteCandidate(id="loopS", name="Rose Bowl loop south", distance_km=8.1, elevation_gain_m=95,
                           difficulty="moderate", surface_type="pavement", is_loop=True,
                           start_lat=34.1613, start_lon=-118.1676)
    other = RouteCandidate(id="arroyo", name="Arroyo trail", distance_km=5.5, elevation_gain_m=66,
                           difficulty="moderate", surface_type="trail", is_loop=True,
                           start_lat=34.1400, start_lon=-118.1660)
    r = recommend(user, checkin, RecentRuns(last_7_days_km=20), [north, south, other], top_n=3)
    by_base = sorted(r, key=lambda x: -x.base_score)
    # without variety, the two Rose Bowl copies would be #1 and #2 ...
    assert {by_base[0].route.id, by_base[1].route.id} == {"loopN", "loopS"}, [(x.route.id, x.base_score) for x in by_base]
    # ... with it, the Arroyo trail moves up to #2
    assert r[1].route.id == "arroyo", [x.route.id for x in r]
    print(f"  variety: {[x.route.name for x in r]} (copy penalized {r[2].breakdown.get('variety')})")

    # 7. injury severity: severe knee injury penalizes pavement more than a mild one
    def pavement_penalty(sev):
        u = UserProfile(fitness_level="intermediate", weekly_km_avg=30,
                        active_injury_body_parts=["left_knee"], injury_severity={"left_knee": sev})
        return recommend(u, checkin, RecentRuns(last_7_days_km=20), [flat], top_n=1)[0].breakdown["injury"]
    assert pavement_penalty("severe") < pavement_penalty("mild")
    print(f"  injury severity: mild {pavement_penalty('mild')} vs severe {pavement_penalty('severe')}")

    # 8. estimated time uses their own pace
    slow = recommend(user, checkin, RecentRuns(last_7_days_km=20, history=[rec(3, 5, pace=7.5)] * 3), [flat], top_n=1)[0]
    quick = recommend(user, checkin, RecentRuns(last_7_days_km=20, history=[rec(3, 5, pace=4.8)] * 3), [flat], top_n=1)[0]
    assert slow.estimated_minutes > quick.estimated_minutes
    print(f"  pace: same 7 km route ~{slow.estimated_minutes} min for a 7:30/km runner, ~{quick.estimated_minutes} min at 4:48/km")
    print("  all personalization checks passed")


def check_difficulty():
    from app.scoring.difficulty import classify_difficulty as cd
    print("\n=== Difficulty checks ===")
    cases = [
        ((4.0, 20), "easy"),        # short and flat
        ((3.0, 200), "hard"),       # short but steep (67 m/km) -> bumped up
        ((7.0, 150), "moderate"),   # effort 8.5
        ((8.0, 300), "hard"),       # effort 11
        ((12.0, 40), "hard"),       # long and flat, effort 12.4
        ((4.0, 120), "moderate"),   # effort 5.2
    ]
    for (km, gain), want in cases:
        got = cd(km, gain)
        assert got == want, (km, gain, got, want)
        print(f"  {km:>4} km, {gain:>3} m climb -> {got}")

    # the engine grades the run as actually run: 3 laps of a 3 km loop is not "easy"
    loop = RouteCandidate(id="lap", name="3 km loop", distance_km=3.0, elevation_gain_m=30,
                          difficulty="easy", surface_type="pavement", is_loop=True)
    r = recommend(INTERMEDIATE, DailyCheckin(energy_score=6, planned_distance_km=9.0, today=THURSDAY),
                  RecentRuns(last_7_days_km=20), [loop], top_n=1)[0]
    assert r.run_format == "repeat" and r.difficulty == "moderate", (r.run_format, r.difficulty)
    print(f"  3 km loop x{r.repeat_count} for a 9 km plan -> {r.difficulty}")

    # beginners are gated on that run difficulty
    beginner = UserProfile(fitness_level="beginner", weekly_km_avg=12)
    steep = RouteCandidate(id="steep", name="Steep 3 km", distance_km=3.0, elevation_gain_m=200,
                           difficulty="easy", surface_type="trail", is_loop=True)
    r = recommend(beginner, DailyCheckin(energy_score=6, today=THURSDAY),
                  RecentRuns(last_7_days_km=8), [steep, loop], top_n=2)
    assert [x.route.id for x in r] == ["lap"], [x.route.id for x in r]
    print("  beginner: steep 3 km (hard) filtered out, flat loop kept")
    print("  all difficulty checks passed")


if __name__ == "__main__":
    for title, user, checkin in SCENARIOS:
        print_results(title, run(user, checkin))
    check_scoring()
    check_personalization()
    check_difficulty()
