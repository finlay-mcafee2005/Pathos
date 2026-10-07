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
};

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

// Weekly mileage drawn as a trail elevation profile
function ElevationChart({ weekly }: { weekly: Stats["weekly"] }) {
  const W = 800;
  const H = 230;
  const top = 34;
  const bottom = 200;
  const n = weekly.length;
  const miles = weekly.map((w) => kmToMiles(w.distance_km));
  const max = Math.max(...miles, 1);
  const pts = miles.map((m, i) => ({
    x: ((i + 0.5) / n) * W,
    y: bottom - (m / max) * (bottom - top),
    m,
  }));

  // smooth curve: horizontal tangents at each point, so hills never overshoot
  let line = `M 0 ${pts[0].y} L ${pts[0].x} ${pts[0].y}`;
  for (let i = 1; i < n; i++) {
    const p0 = pts[i - 1];
    const p1 = pts[i];
    const mx = (p0.x + p1.x) / 2;
    line += ` C ${mx} ${p0.y}, ${mx} ${p1.y}, ${p1.x} ${p1.y}`;
  }
  line += ` L ${W} ${pts[n - 1].y}`;
  const area = `${line} L ${W} ${bottom} L 0 ${bottom} Z`;
  const last = pts[n - 1];

  return (
    <div className="elev">
      <svg viewBox={`0 0 ${W} ${H}`} className="elev-svg" role="img" aria-label="Miles per week, last 8 weeks">
        <defs>
          <linearGradient id="elevFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.5, 1].map((f) => (
          <line key={f} x1="0" x2={W} y1={bottom - f * (bottom - top)} y2={bottom - f * (bottom - top)} className="elev-grid" />
        ))}
        <line x1="0" x2={W} y1={bottom} y2={bottom} className="elev-base" />
        <path d={area} fill="url(#elevFill)" />
        <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" className="elev-line" />
        {pts.slice(0, -1).map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r="4.5" className="elev-dot" />
        ))}
        <circle cx={last.x} cy={last.y} r="11" className="elev-now-halo" />
        <circle cx={last.x} cy={last.y} r="6.5" className="elev-now" />
      </svg>

      {/* hover columns + labels, aligned to the points */}
      <div className="elev-cols">
        {weekly.map((w, i) => {
          const [, mo, d] = w.week_start.split("-").map(Number);
          const isNow = i === n - 1;
          return (
            <div key={w.week_start} className="elev-col" tabIndex={0}>
              <span className="elev-tip" style={{ top: `${(pts[i].y / H) * 100}%` }}>
                <strong>{miles[i].toFixed(1)} mi</strong>
                {isNow ? "this week" : `wk of ${mo}/${d}`}
              </span>
              <span className={`elev-label ${isNow ? "now" : ""}`}>{isNow ? "NOW" : `${mo}/${d}`}</span>
            </div>
          );
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

                <div className="week-days">
                  {DAY_LETTERS.map((letter, i) => {
                    const ran = stats.this_week_days?.[i] ?? false;
                    return (
                      <div key={i} className="week-day">
                        <span className={`week-dot ${ran ? "ran" : ""} ${i === todayIdx ? "today" : ""}`} />
                        <span className="week-day-letter">{letter}</span>
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
                <h2>Mileage profile</h2>
                <span>Last 8 weeks</span>
              </div>
              <ElevationChart weekly={stats.weekly} />
            </section>
          </div>

          <section className="splits">
            <div className="split">
              <span className="split-label">Runs</span>
              <span className="split-value">{stats.total_runs}</span>
            </div>
            <div className="split">
              <span className="split-label">Avg pace</span>
              <span className="split-value">{pace}<small>/mi</small></span>
            </div>
            <div className="split">
              <span className="split-label">Longest</span>
              <span className="split-value">{kmToMiles(stats.longest_run_km).toFixed(1)}<small>mi</small></span>
            </div>
            <div className="split">
              <span className="split-label">Avg rating</span>
              <span className="split-value">
                {stats.avg_rating != null ? stats.avg_rating : "–"}
                {stats.avg_rating != null && <small>/5</small>}
              </span>
            </div>
            <div className="split">
              <span className="split-label">Saved routes</span>
              <span className="split-value">{stats.favorite_count}</span>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

export default StatsPage;
