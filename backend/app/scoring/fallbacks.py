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
GENTLE_NOTE = "It's a bit farther than you wanted to go, but a lot flatter, which suits today"


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


# ---------------------------------------------------------------------------
# A challenge on a fresh day.
#
# Fired up and well slept, the picks lean hillier, but at short distances a
# "moderate" hilly loop can still win every spot. If none of the three is Hard,
# swap the third for the best Hard run that fits their distance, labelled as
# the stretch option - unless they asked for an easy run or no hills.
# ---------------------------------------------------------------------------
FRESH_READINESS = 0.85
CHALLENGE_GAP = 25           # the Hard pick can't score much worse than the pick it replaces
CHALLENGE_M_PER_KM = 45      # only routes this steep (or already Hard) are worth scoring
CHALLENGE_NOTE = "You're feeling good, so here's a harder one if you want it"


def wants_challenge(results: List[ScoredRoute], user: UserProfile,
                    checkin: DailyCheckin, recent: RecentRuns) -> bool:
    return bool(results) and len(results) >= 3 \
        and not any(r.difficulty == "hard" for r in results) \
        and checkin.run_intent != "easy" and checkin.hills_pref != "avoid" \
        and readiness(user, checkin, recent) >= FRESH_READINESS


def add_challenge(results: List[ScoredRoute], user: UserProfile, checkin: DailyCheckin,
                  recent: RecentRuns, candidates: List[RouteCandidate], top_n: int = 3) -> List[ScoredRoute]:
    from app.scoring.engine import climb_per_km
    shown = {r.route.id for r in results}
    steep = [c for c in candidates if c.id not in shown and (
        c.difficulty == "hard" or climb_per_km(c.distance_km, c.elevation_gain_m, c.elevation_loss_m) >= CHALLENGE_M_PER_KM)]
    if not steep:
        return results
    hard = [s for s in recommend(user, checkin, recent, steep, top_n=40)
            if s.difficulty == "hard" and s.distance_matched]
    if not hard or hard[0].score < results[top_n - 1].score - CHALLENGE_GAP:
        return results
    pick = hard[0]
    pick.reasons.insert(0, CHALLENGE_NOTE)
    return results[:top_n - 1] + [pick]


# ---------------------------------------------------------------------------
# Weak picks.
#
# The best option is always shown (even a so-so one beats an empty screen), but
# a 2nd or 3rd pick that's a poor fit AND far behind the best isn't worth
# showing. Picks added on purpose (gentler, challenge) keep their place.
# When the best pick is itself a weak match, say plainly why.
# ---------------------------------------------------------------------------
BASE_SCORE_POINTS = 100      # engine's starting score
PERFECT_POINTS = 85          # same as the app's match %
WEAK_MATCH_PCT = 30          # below this a 2nd/3rd pick can be dropped...
WEAK_GAP_POINTS = 25         # ...when it's also this far behind the best pick
LOW_MATCH_PCT = 50           # below this the card explains what's off


def match_pct(s: ScoredRoute) -> float:
    return max(0.0, min(100.0, (s.score - BASE_SCORE_POINTS) / PERFECT_POINTS * 100))


def drop_weak(results: List[ScoredRoute]) -> List[ScoredRoute]:
    if not results:
        return results
    best = results[0]
    keep = [best]
    for s in results[1:]:
        on_purpose = GENTLE_NOTE in s.reasons or CHALLENGE_NOTE in s.reasons
        if on_purpose or match_pct(s) >= WEAK_MATCH_PCT or s.score >= best.score - WEAK_GAP_POINTS:
            keep.append(s)
    return keep


WEAK_REASON = {
    "soreness": "This surface is a bit harder on your sore legs",
    "injury": "This surface puts some strain on your injury",
    "terrain": "The climbing isn't quite right for how you feel today",
    "surface_pref": "It's not the surface you picked, but nothing nearby was",
    "heat": "It'll be hot out, so run this one easy",
    "footing": "It's on uneven trail and you didn't sleep much, so watch your footing",
    "approach": "Few routes start near you, so most of this run is getting to the route",
    "energy": "This one is tough for a low-energy day",
}


def weak_match_note(s: ScoredRoute) -> str:
    """One plain sentence on why a pick is a weak match (under 50%)."""
    mi = s.effective_distance_km * 0.621371
    target_mi = (s.target_km or 0) * 0.621371
    if target_mi and not s.distance_matched:
        return f"There aren't many {target_mi:.0f} mi routes near you. This one is {mi:.1f} mi"
    known = [(k, v) for k, v in s.breakdown.items() if k in WEAK_REASON and v < 0]
    if known:
        return WEAK_REASON[min(known, key=lambda kv: kv[1])[0]]
    return "Not a perfect fit for today, but one of the closer matches near you"
