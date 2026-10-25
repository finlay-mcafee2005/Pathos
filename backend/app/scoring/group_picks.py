"""
One shared route for a few friends who each checked in on their own.

Each member's check-in scores every route exactly as it would for a solo
run, then the scores are combined so the pick is good for the group AND
not bad for anyone:

  - distance: everyone runs the same route, aimed at what the least-ready
    member should do today; loops offer extra laps to fresher runners
  - hard limits: a route too hard for anyone's level is out; if anyone
    asked to avoid hills, the group avoids hills
  - ranking: half the group average, half the lowest member's score
    ("least misery"), so one runner's sore calf isn't outvoted
"""

from dataclasses import dataclass, field, replace
from typing import List, Optional

from app.scoring.engine import (
    UserProfile, DailyCheckin, RecentRuns, RouteCandidate, ScoredRoute,
    prepare_context, target_km, score_route, passes_difficulty_gate, haversine_km,
)

GROUP_BAND = (0.75, 1.30)       # shared route must be within this of the group target
MIN_WEIGHT = 0.5                # share of the score given to the least-happy member
MAX_GROUP_LAPS = 2              # a group run is at most 2 laps of a loop...
MAX_TOTAL_LAPS = 3              # ...and add-ons never take anyone past 3


@dataclass
class Member:
    name: str
    user: UserProfile
    checkin: DailyCheckin
    recent: RecentRuns


@dataclass
class MemberFit:
    name: str
    score: float
    fit: str                    # "Great" | "Good" | "Okay"
    reason: Optional[str]
    extra_laps: int = 0         # loops: laps a fresher runner could add


@dataclass
class GroupPick:
    route: RouteCandidate
    group_score: float
    run_format: str
    repeat_count: int
    effective_distance_km: float
    estimated_minutes: List[int]
    difficulty: str
    members: List[MemberFit] = field(default_factory=list)


def group_recommend(members: List[Member], candidates: List[RouteCandidate],
                    top_n: int = 3) -> tuple[List[GroupPick], float]:
    prepared = []
    for m in members:
        ctx, ck = prepare_context(m.user, m.checkin, m.recent)
        prepared.append((m, ctx, ck, target_km(ctx, ck)))

    shared_km = min(t for *_, t in prepared)              # least-ready runner sets it
    avoid_hills = any(ck.hills_pref == "avoid" for _, _, ck, _ in prepared)
    quiet = any(getattr(ck, "quiet_streets", False) for _, _, ck, _ in prepared)

    # score every route for every member, judged against the shared distance
    per_member = []
    for m, ctx, ck, own_km in prepared:
        ck = replace(ck, planned_distance_km=shared_km, available_minutes=None,
                     hills_pref="avoid" if avoid_hills else ck.hills_pref, quiet_streets=quiet)
        per_member.append({r.id: score_route(r, m.user, ck, m.recent, ctx) for r in candidates})

    rows = []
    for r in candidates:
        scored = [pm[r.id] for pm in per_member]
        if not all(passes_difficulty_gate(s.difficulty, m.user) for s, (m, *_) in zip(scored, prepared)):
            continue
        if scored[0].run_format == "repeat" and scored[0].repeat_count > MAX_GROUP_LAPS:
            continue                    # 3 laps of a short loop isn't a good group run
        scores = [s.score for s in scored]
        combined = (1 - MIN_WEIGHT) * sum(scores) / len(scores) + MIN_WEIGHT * min(scores)
        rows.append((combined, r, scored))

    # keep the shared distance honest when there are enough routes near it
    lo, hi = GROUP_BAND
    banded = [x for x in rows if lo * shared_km <= x[2][0].effective_distance_km <= hi * shared_km]
    if len(banded) >= top_n:
        rows = banded
    rows.sort(key=lambda x: -x[0])

    best_for = [max((pm[r.id].score for r in candidates), default=1.0) for pm in per_member]

    picks: List[GroupPick] = []

    def near_copy(r, km):
        return any(r.start_lat is not None and p.route.start_lat is not None
                   and haversine_km(r.start_lat, r.start_lon, p.route.start_lat, p.route.start_lon) < 0.4
                   and abs(p.effective_distance_km - km) <= 0.05 * p.effective_distance_km
                   and p.route.surface_type == r.surface_type
                   for p in picks)

    # first pass skips near-copies of a pick already made; second pass fills
    # any empty spots so the group still sees top_n options
    queue = [(x, True) for x in rows] + [(x, False) for x in rows]
    used = set()
    for (combined, r, scored), strict in queue:
        if len(picks) == top_n:
            break
        if r.id in used or (strict and near_copy(r, scored[0].effective_distance_km)):
            continue
        used.add(r.id)
        fits = []
        for s, (m, ctx, ck, own_km), best in zip(scored, prepared, best_for):
            gap = best - s.score            # points behind this runner's own best option
            label = "Great" if gap <= 8 else "Good" if gap <= 20 else "Okay"
            laps = 0
            if r.is_loop and r.distance_km > 0:
                laps = min(MAX_TOTAL_LAPS - s.repeat_count,
                           int((own_km - s.effective_distance_km) / r.distance_km + 0.3))
            fits.append(MemberFit(m.name, round(s.score, 1), label,
                                  s.reasons[0] if s.reasons else None, max(0, laps)))
        first = scored[0]
        picks.append(GroupPick(
            route=r, group_score=round(combined, 1), run_format=first.run_format,
            repeat_count=first.repeat_count, effective_distance_km=first.effective_distance_km,
            estimated_minutes=[s.estimated_minutes for s in scored],
            difficulty=first.difficulty, members=fits,
        ))
    picks.sort(key=lambda p: -p.group_score)
    return picks, shared_km
