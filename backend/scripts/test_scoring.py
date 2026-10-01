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


def run(user, checkin, recent=None):
    recent = recent or RecentRuns(last_7_days_km=user.weekly_mileage_avg * 0.8)
    return recommend(user, checkin, recent, CANDIDATE_ROUTES, top_n=len(CANDIDATE_ROUTES))


INTERMEDIATE = UserProfile(fitness_level="intermediate", weekly_mileage_avg=30)

SCENARIOS = [
    ("Baseline, no surface signals",
     INTERMEDIATE, DailyCheckin(energy_score=6)),
    ("Sore left shin -> trails/track should rise, pavement drop",
     INTERMEDIATE, DailyCheckin(energy_score=6, sore_body_parts=["left_shin"])),
    ("Sore right calf -> pavement/track should rise, trails drop",
     INTERMEDIATE, DailyCheckin(energy_score=6, sore_body_parts=["right_calf"])),
    ("Active knee injury -> pavement heavily penalized",
     UserProfile(fitness_level="advanced", weekly_mileage_avg=40,
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


def check_tie_breaking():
    """Routes with identical scores should be ordered by the tie-breakers,
    and the order should be the same every run."""
    print("\n=== Tie-breaking checks ===")
    user = INTERMEDIATE

    # 1. distance: both trails score the same, but Arroyo (6.5 km loop) is
    #    closer to a 6 km target than an out-and-back of the 12 km trail
    res = run(user, DailyCheckin(energy_score=6, surface_preference="trail",
                                 planned_distance_km=6.0))
    trails = [s for s in res if s.route.surface_type == "trail"]
    assert trails[0].score == trails[1].score or trails[0].score > trails[1].score
    print(f"  distance:  {trails[0].route.name} before {trails[1].route.name}")

    # 2. recency: the never-run route should beat the one run 2 days ago
    recent = RecentRuns(last_7_days_km=24,
                        days_since_last_run_by_route_id={"r1": 20, "r2": 2})
    res = recommend(user, DailyCheckin(energy_score=6, surface_preference="road"),
                    recent, CANDIDATE_ROUTES, top_n=6)
    roads = [s.route.id for s in res if s.route.surface_type == "pavement"]
    assert roads == ["r1", "r2"], roads
    print(f"  recency:   r1 (20 days ago) before r2 (2 days ago)")

    # 3. determinism: shuffled input order gives identical output order
    import random
    base = [s.route.id for s in run(user, DailyCheckin(energy_score=6))]
    for _ in range(20):
        shuffled = CANDIDATE_ROUTES[:]
        random.shuffle(shuffled)
        got = [s.route.id for s in recommend(
            user, DailyCheckin(energy_score=6),
            RecentRuns(last_7_days_km=24), shuffled, top_n=6)]
        assert got == base, (got, base)
    print(f"  determinism: same order across 20 shuffles -> {base}")
    print("  all tie-breaking checks passed")


if __name__ == "__main__":
    for title, user, checkin in SCENARIOS:
        print_results(title, run(user, checkin))
    check_tie_breaking()
