"""
Gentler options on a rough day.

The travel limit is a hard rule, but on a run-down day it can leave nothing
but steep fire roads (e.g. "close to home" in Altadena). When every pick is
too steep for how the runner feels, look a little farther out for gentler
routes and mix the best of them into the picks with a clear note.
"""
from typing import List

from app.scoring.engine import (UserProfile, DailyCheckin, RecentRuns, RouteCandidate,
                                ScoredRoute, recommend, diversify, readiness)

LOW_READINESS = 0.45
GENTLE_M_PER_KM = 20         # "gentle" = averages under ~20 m of climb per km (about 2%)


def climb_rate(s: ScoredRoute) -> float:
    return (s.run_gain_m or 0.0) / s.effective_distance_km if s.effective_distance_km else 0.0


def too_steep(s: ScoredRoute) -> bool:
    return s.difficulty == "hard" and climb_rate(s) >= GENTLE_M_PER_KM \
        or s.breakdown.get("terrain", 0) <= -5
GENTLE_EXTRA_KM = 8.0        # how much farther than their limit we'll look (~15 min drive)
GENTLE_NOTE = "A little farther than you wanted to go, but much gentler for today"


def needs_gentler(results: List[ScoredRoute], user: UserProfile,
                  checkin: DailyCheckin, recent: RecentRuns) -> bool:
    # any steep pick on a run-down day is worth replacing, not only when all three are
    return bool(results) and any(too_steep(r) for r in results) \
        and readiness(user, checkin, recent) < LOW_READINESS


def add_gentler(results: List[ScoredRoute], user: UserProfile, checkin: DailyCheckin,
                recent: RecentRuns, wider: List[RouteCandidate], top_n: int = 3) -> List[ScoredRoute]:
    """wider = candidates from the extended radius (not already in results)."""
    shown = {r.route.id for r in results}
    gentle = [s for s in recommend(user, checkin, recent,
                                   [c for c in wider if c.id not in shown], top_n=top_n)
              if climb_rate(s) < GENTLE_M_PER_KM]   # long but flat is fine; steep isn't
    if not gentle:
        return results
    keep = [r for r in results if not too_steep(r)]          # nearby picks that already suit today
    steep = [r for r in results if too_steep(r)]
    need = top_n - len(keep)
    if not keep:
        need = top_n - 1                                      # keep the best nearby option as a choice
    for s in gentle:
        s.reasons.insert(0, GENTLE_NOTE)
    extra = diversify(gentle, min(need, len(gentle)), surface_requested=bool(checkin.surface_preference))
    return (keep + extra + steep)[:top_n]
