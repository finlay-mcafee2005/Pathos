import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_URL, kmToMiles, formatPacePerMile } from "../utils/format";

type Stats = {
  total_runs: number;
  total_distance_km: number;
  this_week_distance_km: number;
  avg_pace_min_km: number | null;
  longest_run_km: number;
  avg_rating: number | null;
  current_streak_days: number;
  favorite_count: number;
  weekly: { week_start: string; distance_km: number }[];
  this_week_days?: boolean[];
  this_week_daily_km?: number[];
  runs_this_week?: number;
  fastest_pace_min_km?: number | null;
  longest_run_name?: string | null;
  surface_mix_km?: Record<string, number>;
};

const SURFACES: { key: string; label: string }[] = [
  { key: "pavement", label: "Road" },
  { key: "trail", label: "Trail" },
  { key: "track", label: "Track" },
  { key: "mixed", label: "Mixed" },
  { key: "own", label: "Your own routes" },
];

const DAY_LETTERS = ["M", "T", "W", "T", "F", "S", "S"];

// Topographic contour lines for the hero card background
function TopoLines() {
  const lines = Array.from({ length: 11 }, (_, i) => {
    const y = 18 + i * 26;
    const a = 14 + (i % 3) * 6;
    return `M -20 ${y} C 60 ${y - a}, 120 ${y + a}, 200 ${y} S 340 ${y - a * 1.4}, 420 ${y + 4} S 560 ${y + a}, 640 ${y - 6}`;
  });
  return (
    <svg className="topo-lines" viewBox="0 0 600 300" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      {lines.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="currentColor" strokeWidth={i % 4 === 0 ? 1.4 : 0.8} />
      ))}
    </svg>
  );
}

function weeklyAvg(weekly: Stats["weekly"]): number {
  return weekly.reduce((sum, w) => sum + kmToMiles(w.distance_km), 0) / Math.max(weekly.length, 1);
}

// Weekly mileage as labelled bars, with a dashed line at the 8-week average
function WeeklyBars({ weekly }: { weekly: Stats["weekly"] }) {
  const miles = weekly.map((w) => kmToMiles(w.distance_km));
  const rawMax = Math.max(...miles, 1);
  const step = rawMax > 40 ? 20 : rawMax > 20 ? 10 : 5;
  const max = Math.ceil(rawMax / step) * step;
  const ticks = Array.from({ length: max / step + 1 }, (_, i) => i * step);
  const avg = miles.reduce((s, m) => s + m, 0) / miles.length;
  const n = weekly.length;

  return (
    <div className="wb">
      <div className="wb-axis">
        {[...ticks].reverse().map((t) => <span key={t}>{t}</span>)}
      </div>
      <div className="wb-plot">
        <div className="wb-area">
        {ticks.map((t) => (
          <i key={t} className="wb-grid" style={{ bottom: `${(t / max) * 100}%` }} />
        ))}
        {avg > 0 && <div className="wb-avg" style={{ bottom: `${(avg / max) * 100}%` }} />}
        <div className="wb-bars">
          {weekly.map((w, i) => {
            const isNow = i === n - 1;
            const m = miles[i];
            return (
              <div key={w.week_start} className={`wb-col ${isNow ? "now" : ""}`}>
                <div className="wb-bar-wrap">
                  {m > 0 && <span className="wb-val">{m.toFixed(1)}</span>}
                  <div className={`wb-bar ${m === 0 ? "zero" : ""}`} style={{ height: m > 0 ? `${(m / max) * 100}%` : undefined }} />
                </div>
              </div>
            );
          })}
        </div>
        </div>
      </div>
      <div className="wb-labels">
        {weekly.map((w, i) => {
          const [, mo, d] = w.week_start.split("-").map(Number);
          const isNow = i === n - 1;
          return <span key={w.week_start} className={isNow ? "now" : ""}>{isNow ? "This wk" : `${mo}/${d}`}</span>;
        })}
      </div>
    </div>
  );
}

function StatsPage() {
  const userId = localStorage.getItem("user_id");
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/stats/${userId}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Server responded with ${res.status}`);
        return res.json();
      })
      .then(setStats)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [userId]);

  const thisWeek = stats ? kmToMiles(stats.this_week_distance_km) : 0;
  const lastWeek = stats && stats.weekly.length > 1 ? kmToMiles(stats.weekly[stats.weekly.length - 2].distance_km) : 0;
  const delta = thisWeek - lastWeek;
  const totalMiles = stats ? kmToMiles(stats.total_distance_km) : 0;
  const pace = stats ? formatPacePerMile(stats.avg_pace_min_km).replace(" /mi", "") : "–";
  const todayIdx = (new Date().getDay() + 6) % 7; // Monday = 0
  const weekOf = stats?.weekly.length
    ? (() => {
        const [y, m, d] = stats.weekly[stats.weekly.length - 1].week_start.split("-").map(Number);
        return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric" });
      })()
    : "";

  return (
    <div className="app stats-page">
      {loading && <p className="empty-state">Loading...</p>}
      {error && <p className="error">Error: {error}</p>}

      {stats && stats.total_runs === 0 && (
        <div className="stats-intro">
          <span className="stats-eyebrow">Your logbook</span>
          <h1>Your miles start here.</h1>
          <p>
            Your stats will show up after you <Link to="/log-run">log a run</Link>.
          </p>
        </div>
      )}

      {stats && stats.total_runs > 0 && (
        <>
          <div className="stats-intro">
            <span className="stats-eyebrow">Your logbook · week of {weekOf}</span>
            <h1>
              <span className="bib">{totalMiles.toFixed(1)}</span> miles with Pathos.
            </h1>
          </div>

          <div className="stats-top">
            <section className="week-card">
              <TopoLines />
              <div className="week-card-body">
                <span className="week-label">This week</span>
                <div className="week-number">
                  {thisWeek.toFixed(1)}
                  <span>mi</span>
                </div>
                <span className={`week-delta ${delta >= 0 ? "up" : "down"}`}>
                  {delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(1)} mi vs last week
                </span>

                <div className="week-bars">
                  {DAY_LETTERS.map((letter, i) => {
                    const km = stats.this_week_daily_km?.[i] ?? (stats.this_week_days?.[i] ? 1 : 0);
                    const mi = kmToMiles(km);
                    const dayMax = Math.max(...(stats.this_week_daily_km ?? [1]).map(kmToMiles), 1);
                    return (
                      <div key={i} className={`week-bar-col ${i === todayIdx ? "today" : ""} ${i > todayIdx ? "future" : ""}`}>
                        <span className="week-bar-val">{mi > 0 ? mi.toFixed(1) : ""}</span>
                        <div className="week-bar-track">
                          <div className="week-bar-fill" style={{ height: mi > 0 ? `${Math.max((mi / dayMax) * 100, 8)}%` : 0 }} />
                        </div>
                        <span className="week-day-letter">{letter}</span>
                        <i className="week-today-dot" />
                      </div>
                    );
                  })}
                </div>
                <span className="week-streak">
                  {stats.current_streak_days > 0
                    ? `${stats.current_streak_days}-day streak, keep it rolling`
                    : "Start a streak today"}
                </span>
              </div>
            </section>

            <section className="elev-card">
              <div className="elev-head">
                <h2>Weekly mileage</h2>
                <span className="wb-legend">
                  <i className="wb-legend-avg" /> {weeklyAvg(stats.weekly).toFixed(1)} mi/wk avg
                  <span className="wb-legend-sep">·</span> Last 8 weeks
                </span>
              </div>
              <WeeklyBars weekly={stats.weekly} />
            </section>
          </div>

          <section className="tiles">
            <div className="tile">
              <span className="tile-head">
                <span className="tile-icon runs" aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="M4 18l5-6 4 3 7-9" /></svg>
              </span>
                <span className="tile-label">Runs</span>
              </span>
              <span className="tile-value">{stats.total_runs}</span>
              <span className="tile-sub">{stats.runs_this_week ?? 0} this week</span>
            </div>
            <div className="tile">
              <span className="tile-head">
                <span className="tile-icon pace" aria-hidden="true">
                <svg viewBox="0 0 24 24"><circle cx="12" cy="13" r="7" /><path d="M12 13l3-3M10 3h4" /></svg>
              </span>
                <span className="tile-label">Avg pace</span>
              </span>
              <span className="tile-value">{pace}<small>/mi</small></span>
              <span className="tile-sub">
                {stats.fastest_pace_min_km ? `Best ${formatPacePerMile(stats.fastest_pace_min_km)}` : "Distance-weighted"}
              </span>
            </div>
            <div className="tile">
              <span className="tile-head">
                <span className="tile-icon longest" aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="M3 20l6-10 4 6 3-4 5 8z" /></svg>
              </span>
                <span className="tile-label">Longest</span>
              </span>
              <span className="tile-value">{kmToMiles(stats.longest_run_km).toFixed(1)}<small>mi</small></span>
              <span className="tile-sub">{stats.longest_run_name ?? "Your own route"}</span>
            </div>
            <div className="tile">
              <span className="tile-head">
                <span className="tile-icon rating" aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z" /></svg>
              </span>
                <span className="tile-label">Avg rating</span>
              </span>
              <span className="tile-value">
                {stats.avg_rating != null ? stats.avg_rating : "–"}
                {stats.avg_rating != null && <small>/5</small>}
              </span>
              <span className="tile-sub tile-stars">
                {stats.avg_rating != null &&
                  Array.from({ length: 5 }, (_, i) => (
                    <i key={i} className={i < Math.round(stats.avg_rating!) ? "on" : ""}>★</i>
                  ))}
              </span>
            </div>
            <Link to="/favorites" className="tile tile-link">
              <span className="tile-head">
                <span className="tile-icon saved" aria-hidden="true">
                <svg viewBox="0 0 24 24"><path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.5-7 10-7 10z" /></svg>
              </span>
                <span className="tile-label">Saved routes</span>
              </span>
              <span className="tile-value">{stats.favorite_count}</span>
              <span className="tile-sub">View favorites →</span>
            </Link>
          </section>

          {stats.surface_mix_km && totalMiles > 0 && (
            <section className="mix-card">
              <div className="elev-head">
                <h2>Where your miles come from</h2>
                <span>All time</span>
              </div>
              <div className="mix-bar">
                {SURFACES.filter((sf) => (stats.surface_mix_km![sf.key] ?? 0) > 0).map((sf) => (
                  <div
                    key={sf.key}
                    className={`mix-seg mix-${sf.key}`}
                    style={{ flexGrow: stats.surface_mix_km![sf.key] }}
                    title={`${sf.label}: ${kmToMiles(stats.surface_mix_km![sf.key]).toFixed(1)} mi`}
                  />
                ))}
              </div>
              <ul className="mix-legend">
                {SURFACES.filter((sf) => (stats.surface_mix_km![sf.key] ?? 0) > 0).map((sf) => {
                  const mi = kmToMiles(stats.surface_mix_km![sf.key]);
                  return (
                    <li key={sf.key}>
                      <i className={`mix-${sf.key}`} />
                      <span>{sf.label}</span>
                      <b>{mi.toFixed(1)} mi</b>
                      <small>{Math.round((mi / totalMiles) * 100)}%</small>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}

export default StatsPage;
