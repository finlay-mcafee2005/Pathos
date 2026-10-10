import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_URL } from "../utils/format";

export type GroupMatch = {
  club_id: string;
  club_name: string;
  location: string;
  pace_range: string;
  experience_level: string;
  starts_at: string;
  day_of_week: string;
  meetup_time: string;
  distance_mi: number | null;
  run_type: string | null;
  surface: string | null;
  is_my_club: boolean;
  is_today: boolean;
  fit: number;
  reasons: string[];
  cautions: string[];
  distance_from_home_km: number | null;
  source_url?: string | null;
  verified_on?: string | null;
  notes?: string | null;
  place_label?: string | null;
};

type GroupsResponse = {
  today: GroupMatch | null;
  upcoming: GroupMatch[];
  checked_in_today: boolean;
};

const RUN_TYPE_LABELS: Record<string, string> = {
  easy: "Easy run",
  long: "Long run",
  workout: "Workout",
  social: "Social run",
};

export function formatMeetTime(iso: string): string {
  const [, time] = iso.split("T");
  const [h, m] = time.split(":").map(Number);
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "am" : "pm"}`;
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const tomorrow = new Date();
  tomorrow.setDate(today.getDate() + 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === tomorrow.toDateString()) return "Tomorrow";
  return d.toLocaleDateString(undefined, { weekday: "long" });
}

export function sessionTitle(m: GroupMatch): string {
  const type = m.run_type ? RUN_TYPE_LABELS[m.run_type] ?? m.run_type : "Group run";
  return m.distance_mi ? `${m.distance_mi} mi ${type.toLowerCase()}` : type;
}

function FitMeter({ fit }: { fit: number }) {
  const r = 22;
  const c = 2 * Math.PI * r;
  return (
    <div className="fit-meter" aria-label={`${Math.round(fit)}% fit`}>
      <svg width="58" height="58" viewBox="0 0 58 58" aria-hidden="true">
        <circle cx="29" cy="29" r={r} className="fit-track" />
        <circle
          cx="29"
          cy="29"
          r={r}
          className="fit-fill"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - fit / 100)}
          transform="rotate(-90 29 29)"
        />
      </svg>
      <span className="fit-num">{Math.round(fit)}</span>
      <span className="fit-label">fit</span>
    </div>
  );
}

function shortPlace(location: string): string {
  // "The Oinkster, 2005 Colorado Blvd, Los Angeles, CA" -> "The Oinkster"
  return location.split(",")[0].trim();
}

function fitWord(fit: number): string {
  if (fit >= 80) return "Great fit";
  if (fit >= 65) return "Good fit";
  if (fit >= 50) return "Okay fit";
  return "Long shot";
}

function longDayLabel(iso: string): string {
  const label = dayLabel(iso);
  const date = new Date(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  return label === "Today" || label === "Tomorrow" ? `${label} · ${date}` : date;
}

function groupByDay(matches: GroupMatch[]): [string, GroupMatch[]][] {
  const sorted = [...matches].sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  const groups = new Map<string, GroupMatch[]>();
  for (const m of sorted) {
    const key = longDayLabel(m.starts_at);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(m);
  }
  // within a day, best fit first
  return [...groups.entries()].map(([k, v]) => [k, v.sort((a, b) => b.fit - a.fit)]);
}

function SessionCard({ m }: { m: GroupMatch }) {
  const [open, setOpen] = useState(false);
  const allPaces = /all/i.test(m.pace_range);
  // drop reasons that just repeat a tag or the distance line
  const reasons = m.reasons.filter(
    (r) => !(allPaces && /all paces/i.test(r)) && !/close to home|near home/i.test(r),
  );
  const [time, ampm] = formatMeetTime(m.starts_at).split(" ");
  const longNotes = (m.notes?.length ?? 0) > 110;
  const tone = m.fit >= 80 ? "great" : m.fit >= 65 ? "good" : "fair";

  return (
    <article className={`gr-card ${m.is_my_club ? "mine" : ""}`}>
      <div className="gr-time">
        <span className="gr-time-num">{time}</span>
        <span className="gr-time-ampm">{ampm}</span>
      </div>

      <div className="gr-main">
        <div className="gr-title-row">
          <h3>{m.club_name}</h3>
          {m.is_my_club && <span className="gr-badge">Your club</span>}
        </div>
        <p className="gr-where">
          <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 22s7-6.2 7-12a7 7 0 1 0-14 0c0 5.8 7 12 7 12z" fill="none" stroke="currentColor" strokeWidth="2" />
            <circle cx="12" cy="10" r="2.5" fill="currentColor" />
          </svg>
          <span title={m.location}>{m.place_label || shortPlace(m.location)}</span>
          {m.distance_from_home_km != null && (
            <span className="gr-away">{Math.max(0.1, m.distance_from_home_km * 0.621371).toFixed(1)} mi from home</span>
          )}
        </p>
        <div className="gr-tags">
          <span className="gr-tag type">{sessionTitle(m)}</span>
          {m.surface && <span className="gr-tag">{m.surface.charAt(0).toUpperCase() + m.surface.slice(1)}</span>}
          <span className="gr-tag">{allPaces ? "All paces" : m.pace_range.replace(" min/mi", "/mi")}</span>
          {m.notes?.toLowerCase().includes("free") && <span className="gr-tag">Free</span>}
        </div>
        {(reasons.length > 0 || m.cautions.length > 0) && (
          <ul className="gr-reasons">
            {reasons.slice(0, 2).map((r) => <li key={r}>{r}</li>)}
            {m.cautions.slice(0, 1).map((c) => <li key={c} className="caution">{c}</li>)}
          </ul>
        )}
        {m.notes && (
          <p className={`gr-notes ${longNotes && !open ? "clamped" : ""}`}>
            {m.notes}
            {longNotes && (
              <button type="button" className="gr-more" onClick={() => setOpen(!open)}>
                {open ? "Less" : "More"}
              </button>
            )}
          </p>
        )}
        <div className="gr-links">
          <a
            className="gr-link"
            href={`https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(m.location)}`}
            target="_blank"
            rel="noreferrer"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
                 strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M3 11l18-8-8 18-2-8-8-2z" />
            </svg>
            Directions
          </a>
          {m.source_url && (
            <a className="gr-link" href={m.source_url} target="_blank" rel="noreferrer">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
                   strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" />
              </svg>
              Club schedule
            </a>
          )}
        </div>
      </div>

      <div className={`gr-fit ${tone}`}>
        <FitRing fit={m.fit} />
        <span className="gr-fit-word">{fitWord(m.fit)}</span>
      </div>
    </article>
  );
}

function FitRing({ fit }: { fit: number }) {
  const r = 26;
  const c = 2 * Math.PI * r;
  return (
    <div className="gr-ring" aria-label={`${Math.round(fit)} out of 100 fit`}>
      <svg width="64" height="64" viewBox="0 0 64 64" aria-hidden="true">
        <circle cx="32" cy="32" r={r} className="gr-ring-track" />
        <circle
          cx="32" cy="32" r={r}
          className="gr-ring-fill"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - fit / 100)}
          transform="rotate(-90 32 32)"
        />
      </svg>
      <span className="gr-ring-num">{Math.round(fit)}</span>
    </div>
  );
}

function GroupsPage() {
  const userId = localStorage.getItem("user_id");
  const [data, setData] = useState<GroupsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [joinMsg, setJoinMsg] = useState<string | null>(null);

  function load() {
    fetch(`${API_URL}/groups/${userId}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Server responded with ${res.status}`);
        return res.json();
      })
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(load, [userId]);

  async function join(e: React.FormEvent) {
    e.preventDefault();
    if (!code.trim()) return;
    const res = await fetch(`${API_URL}/clubs/join`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, join_code: code }),
    });
    const body = await res.json().catch(() => null);
    if (res.ok) {
      setJoinMsg(`You're in ${body.club_name}.`);
      setCode("");
      load();
    } else {
      setJoinMsg(body?.detail ?? "Couldn't join that club.");
    }
  }

  async function leave() {
    await fetch(`${API_URL}/clubs/leave/${userId}`, { method: "POST" });
    setJoinMsg(null);
    load();
  }

  const myClub = data?.upcoming.find((m) => m.is_my_club);
  const others = (data?.upcoming ?? []).filter((m) => m !== data?.today);

  return (
    <div className="app groups-page">
      <header className="ci-intro">
        <span className="ci-eyebrow">Group runs · next 7 days</span>
        <h1>Run with people at your pace.</h1>
        <p>
          Club sessions near you, ranked by how well the pace, distance and timing fit you
          {data?.checked_in_today ? " and how you're feeling today." : ". Check in to factor in how you feel today."}
        </p>
      </header>

      {loading && <p className="empty-state">Loading...</p>}
      {error && <p className="error">Error: {error}</p>}

      {data?.today && (
        <section className="group-hero">
          <span className="group-hero-label">Best group run today</span>
          <div className="group-hero-row">
            <div>
              <h2>{data.today.club_name}</h2>
              <p className="group-hero-when">
                <span className="bib">{formatMeetTime(data.today.starts_at)}</span> · {sessionTitle(data.today)} ·{" "}
                {data.today.location}
              </p>
            </div>
            <FitMeter fit={data.today.fit} />
          </div>
          <ul className="group-reasons light">
            {data.today.reasons.slice(0, 3).map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </section>
      )}

      {data && data.upcoming.length === 0 && (
        <div className="favs-empty">
          <h2>No group runs yet</h2>
          <p>No clubs have sessions in the app yet. Seed some with scripts/seed_clubs.py.</p>
        </div>
      )}

      {groupByDay(others).map(([day, sessions]) => (
        <section key={day} className="gr-day">
          <h2 className="gr-day-title">
            <span>{day}</span>
            <small>{sessions.length} session{sessions.length === 1 ? "" : "s"}</small>
          </h2>
          <div className="gr-list">
            {sessions.map((m) => (
              <SessionCard key={`${m.club_id}-${m.starts_at}`} m={m} />
            ))}
          </div>
        </section>
      ))}

      <section className="group-club">
        <div>
          <span className="ci-eyebrow">Your club</span>
          {myClub ? (
            <p>
              You're in <b>{myClub.club_name}</b>. Their sessions get a small boost in your matches.{" "}
              <button type="button" className="su-remove" onClick={leave}>Leave club</button>
            </p>
          ) : (
            <p>Have a join code from your club? Add it and their sessions get a small boost in your matches.</p>
          )}
        </div>
        <form className="group-join" onSubmit={join}>
          <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="JOIN CODE" aria-label="Club join code" />
          <button type="submit">{myClub ? "Switch" : "Join"}</button>
        </form>
        {joinMsg && <p className="group-join-msg">{joinMsg}</p>}
      </section>

      {!data?.checked_in_today && (
        <p className="empty-state">
          <Link to="/checkin">Check in</Link> to see which group run fits how you feel today.
        </p>
      )}
    </div>
  );
}

export default GroupsPage;
