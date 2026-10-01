"""
Standalone sanity check for the scoring engine - no database required.
Run with:  python scripts/test_scoring.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.scoring.engine import (
    UserProfile, DailyCheckin, RecentRuns, RouteCandidate, recommend,
)


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


if __name__ == "__main__":
    for title, user, checkin in SCENARIOS:
        print_results(title, run(user, checkin))
    check_scoring()
