"""
Export one study participant's check-ins and the picks they were shown.

Run from backend/ (reads only, never writes to the database):
    DATABASE_URL=... python3 scripts/export_study_data.py --email someone@oxy.edu
    DATABASE_URL=... python3 scripts/export_study_data.py --email someone@oxy.edu --since 2026-10-19
    DATABASE_URL=... python3 scripts/export_study_data.py --name "Jane"                 (part of their name)
    DATABASE_URL=... python3 scripts/export_study_data.py --who-checked-in 2026-10-20  (everyone that day)

Writes to scripts/study_exports/<email>/ (kept out of git - it's personal data):
    summary.md     - read this: each check-in with what they entered and the top 3 shown
    checkins.csv   - one row per check-in (everything they entered)
    picks.csv      - one row per route shown: check-in, rank, route, match %, distance, climb, ...
    runs.csv       - runs they logged, and which pick (if any) each came from

Note: if a check-in's picks were refreshed, only the last set shown is saved.
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "DATABASE_URL" not in os.environ:
    sys.exit('DATABASE_URL isn\'t set. Run: export DATABASE_URL="<your Supabase link>"')
USAGE = ("Usage:\n"
         "  python3 scripts/export_study_data.py --email someone@oxy.edu [--since YYYY-MM-DD]\n"
         "  python3 scripts/export_study_data.py --name \"Jane Doe\" [--since YYYY-MM-DD]   (part of a name is fine)\n"
         "  python3 scripts/export_study_data.py --who-checked-in YYYY-MM-DD           (list everyone that day)")
if not any(a in sys.argv for a in ("--email", "--name", "--who-checked-in")):
    sys.exit(USAGE)


def arg(flag):
    return sys.argv[sys.argv.index(flag) + 1].strip() if flag in sys.argv else None


EMAIL = (arg("--email") or "").lower()
NAME = arg("--name")
SINCE = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else "1900-01-01"
LA = ZoneInfo("America/Los_Angeles")
MI = 0.621371
PERFECT_POINTS = 85        # same as the app's match %


def la_time(dt):
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LA).strftime("%Y-%m-%d %I:%M %p")


def match_pct(score, checkin=None):
    """Same as the app: points out of what a perfect route could earn for that check-in."""
    from types import SimpleNamespace
    from app.scoring.engine import perfect_points, match_pct as pct
    return pct(score, perfect_points(SimpleNamespace(**dict(checkin))) if checkin else PERFECT_POINTS)


def label(pct):
    return "Great match" if pct >= 70 else "Good match" if pct >= 50 else "Worth a look"


def main():
    from sqlalchemy import create_engine, text
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        day = arg("--who-checked-in")
        if day:
            # check-in dates are stored by the server's (UTC) day, so look at the LA day around it
            rows = conn.execute(text("""
                SELECT u.full_name, u.email, count(*) AS n, min(c.created_at) AS first, max(c.created_at) AS last
                FROM checkin c JOIN "user" u ON u.id = c.user_id
                WHERE c.checkin_date BETWEEN CAST(:d AS date) AND CAST(:d AS date) + 1
                GROUP BY u.full_name, u.email ORDER BY min(c.created_at)
            """), {"d": day}).mappings().all()
            print(f"Check-ins on or just after {day} (times in LA):")
            for r in rows:
                print(f"  {r['full_name']:<28} {r['email']:<34} {r['n']} check-ins  {la_time(r['first'])} - {la_time(r['last'])}")
            if not rows:
                print("  nobody")
            print("\nThen export one with: python3 scripts/export_study_data.py --email THEIR_EMAIL --since " + day)
            return
        cols = ('SELECT id, full_name, email, fitness_level, weekly_mileage_avg, usual_pace_min_km, '
                'address, goal FROM "user" ')
        if NAME:
            users = conn.execute(text(cols + "WHERE full_name ILIKE :n ORDER BY created_at"),
                                 {"n": f"%{NAME}%"}).mappings().all()
            if not users:
                sys.exit(f'No account with a name like "{NAME}". Try part of it, or --who-checked-in YYYY-MM-DD.')
            if len(users) > 1:
                print(f'{len(users)} accounts match "{NAME}" - use --email with one of these:')
                for u in users:
                    print(f"  {u['full_name']:<28} {u['email']}")
                sys.exit(1)
            user = users[0]
        else:
            user = conn.execute(text(cols + "WHERE lower(email) = :e"), {"e": EMAIL}).mappings().first()
        if not user:
            sys.exit(f"No account with the email {EMAIL}. Check the spelling (it's matched exactly, ignoring case).")
        checkins = conn.execute(text("""
            SELECT * FROM checkin WHERE user_id = :u AND checkin_date >= :s ORDER BY created_at
        """), {"u": user["id"], "s": SINCE}).mappings().all()
        picks = conn.execute(text("""
            SELECT r.checkin_id, r.rank, r.route_name, r.score, r.reasoning, r.shown_at, r.run_id,
                   r.route_id, rt.distance_km, rt.elevation_gain_m, rt.surface_type, rt.difficulty,
                   rt.shade_pct, rt.scenic_pct
            FROM recommendation r LEFT JOIN route rt ON rt.id = r.route_id
            WHERE r.user_id = :u AND r.rec_date >= :s
            ORDER BY r.shown_at, r.rank
        """), {"u": user["id"], "s": SINCE}).mappings().all()
        runs = conn.execute(text("""
            SELECT ru.run_date, ru.distance_km, ru.pace_min_km, ru.rating, ru.post_run_soreness, ru.source,
                   ru.recommendation_id, ru.pick_fit, COALESCE(rt.nickname, rt.name) AS route
            FROM run ru LEFT JOIN route rt ON rt.id = ru.route_id
            WHERE ru.user_id = :u AND ru.run_date >= :s ORDER BY ru.run_date
        """), {"u": user["id"], "s": SINCE}).mappings().all()
        injuries = conn.execute(text("SELECT body_part, severity, reported_at, resolved_at FROM injury WHERE user_id = :u"),
                                {"u": user["id"]}).mappings().all()

    out = os.path.join(os.path.dirname(__file__), "study_exports", user["email"].lower().replace("@", "_at_"))
    os.makedirs(out, exist_ok=True)

    by_checkin = {}
    for p in picks:
        by_checkin.setdefault(p["checkin_id"], []).append(p)
    num = {c["id"]: n for n, c in enumerate(checkins, 1)}
    ck_by_id = {c["id"]: c for c in checkins}

    ck_cols = ["checkin_no", "submitted", "energy_score", "sleep_hours", "sleep_quality", "sore_body_parts",
               "planned_distance_mi", "travel_limit_mi", "run_time", "available_minutes", "mood", "run_intent",
               "hills_pref", "surface_preference", "wants_scenic", "wants_adventure", "mood_note", "picks_shown"]
    with open(os.path.join(out, "checkins.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(ck_cols)
        for c in checkins:
            w.writerow([num[c["id"]], la_time(c["created_at"]), c["energy_score"], c["sleep_hours"], c["sleep_quality"],
                        ", ".join(json.loads(c["sore_body_parts"] or "[]")),
                        round(c["planned_distance_km"] * MI, 2) if c["planned_distance_km"] else "",
                        round(c["willing_to_drive_km"] * MI, 2) if c["willing_to_drive_km"] else "",
                        c["run_time"], c["available_minutes"], c["mood"], c["run_intent"], c["hills_pref"],
                        c["surface_preference"], c["wants_scenic"], c["wants_adventure"], c["mood_note"],
                        len(by_checkin.get(c["id"], []))])

    pk_cols = ["checkin_no", "shown_at", "rank", "route", "match_pct", "label", "route_distance_mi", "route_climb_ft",
               "surface", "difficulty", "shade_pct", "scenic_pct", "ran_it", "reasons"]
    with open(os.path.join(out, "picks.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(pk_cols)
        for p in picks:
            pct = match_pct(p["score"], ck_by_id.get(p["checkin_id"]))
            w.writerow([num.get(p["checkin_id"], ""), la_time(p["shown_at"]), p["rank"], p["route_name"], pct, label(pct),
                        round(p["distance_km"] * MI, 2) if p["distance_km"] else "",
                        round(p["elevation_gain_m"] * 3.28084) if p["elevation_gain_m"] is not None else "",
                        p["surface_type"] or "", p["difficulty"] or "",
                        round(p["shade_pct"] * 100) if p["shade_pct"] is not None else "",
                        round(p["scenic_pct"] * 100) if p["scenic_pct"] is not None else "",
                        "yes" if p["run_id"] else "", p["reasoning"]])

    with open(os.path.join(out, "runs.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "route", "distance_mi", "pace_min_per_mi", "rating", "soreness_after", "source",
                    "from_a_pick", "pick_fit"])
        for r in runs:
            w.writerow([r["run_date"], r["route"] or "", round(r["distance_km"] * MI, 2),
                        round(r["pace_min_km"] / MI, 2) if r["pace_min_km"] else "", r["rating"] or "",
                        r["post_run_soreness"] if r["post_run_soreness"] is not None else "", r["source"] or "",
                        "yes" if r["recommendation_id"] else "", r["pick_fit"] or ""])

    injury_text = ", ".join("%s (%s)" % (i["body_part"], i["severity"]) for i in injuries)
    lines = [f"# Study export: {user['full_name']} ({user['email']})", "",
             f"Exported {datetime.now(LA).strftime('%Y-%m-%d %I:%M %p')} (Los Angeles time).", "",
             f"Profile: {user['fitness_level']}, {user['weekly_mileage_avg']:.0f} km/week, goal {user['goal']}, "
             f"home {user['address'] or 'not set'}.",
             f"Injuries: {injury_text or 'none'}.", "",
             f"**{len(checkins)} check-ins, {len(picks)} picks shown, {len(runs)} runs logged.**", ""]
    for c in checkins:
        sore = ", ".join(json.loads(c["sore_body_parts"] or "[]")) or "none"
        dist = f"{c['planned_distance_km'] * MI:.1f} mi" if c["planned_distance_km"] else "no plan"
        travel = f"{c['willing_to_drive_km'] * MI:.1f} mi" if c["willing_to_drive_km"] else "any"
        extras = [x for x in [f"mood {c['mood']}" if c["mood"] else "", f"run: {c['run_intent']}" if c["run_intent"] else "",
                              f"hills: {c['hills_pref']}" if c["hills_pref"] else "",
                              f"surface: {c['surface_preference']}" if c["surface_preference"] else "",
                              "wants scenic" if c["wants_scenic"] else "", "wants somewhere new" if c["wants_adventure"] else ""] if x]
        lines += [f"## Check-in {num[c['id']]} - {la_time(c['created_at'])}", "",
                  f"Energy {c['energy_score']}/10, sleep {c['sleep_hours'] or '?'} h (quality {c['sleep_quality'] or '?'}/5), "
                  f"sore: {sore}. Distance {dist}, travel limit {travel}, run time {c['run_time'] or 'now'}."
                  + (f" Also: {', '.join(extras)}." if extras else ""), ""]
        shown = by_checkin.get(c["id"], [])
        if not shown:
            lines += ["_No picks saved for this check-in (they may not have opened the results)._", ""]
        for p in shown:
            pct = match_pct(p["score"], c)
            meta = []
            if p["distance_km"]:
                meta.append(f"route {p['distance_km'] * MI:.1f} mi")
            if p["elevation_gain_m"] is not None:
                meta.append(f"{p['elevation_gain_m'] * 3.28084:.0f} ft")
            if p["surface_type"]:
                meta.append(p["surface_type"])
            if p["difficulty"]:
                meta.append(p["difficulty"])
            lines.append(f"{p['rank']}. **{p['route_name']}** - {label(pct)} ({pct}%)"
                         + (f" - {', '.join(meta)}" if meta else "") + (" - **ran it**" if p["run_id"] else ""))
            if p["reasoning"]:
                lines.append(f"   - {p['reasoning']}")
        lines.append("")
    with open(os.path.join(out, "summary.md"), "w") as f:
        f.write("\n".join(lines))

    print(f"{user['full_name']}: {len(checkins)} check-ins, {len(picks)} picks shown, {len(runs)} runs logged.")
    print(f"Saved to {out}/  (summary.md, checkins.csv, picks.csv, runs.csv)")


if __name__ == "__main__":
    main()
