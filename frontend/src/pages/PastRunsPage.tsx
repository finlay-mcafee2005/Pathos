import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_URL, kmToMiles, formatPacePerMile, SURFACE_LABELS } from "../utils/format";

type PastRun = {
  id: string;
  run_date: string;
  route_id: string | null;
  route_name: string | null;
  surface_type: string | null;
  distance_km: number;
  pace_min_km: number;
  rating: number | null;
  post_run_soreness: number | null;
  duration_s?: number | null;
  elevation_gain_m?: number | null;
  avg_heart_rate?: number | null;
  source?: string | null;
  pick_fit?: "yes" | "sort_of" | "no" | null;
  notes?: string | null;
};

function parseDate(iso: string): Date {
  // YYYY-MM-DD parsed as local time so it doesn't shift a day
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

type Day = { iso: string; runs: PastRun[] };
type Month = { label: string; days: Day[]; runs: PastRun[] };

// newest first: months -> days -> runs
function groupRuns(runs: PastRun[]): Month[] {
  const months: Month[] = [];
  for (const run of runs) {
    const label = parseDate(run.run_date).toLocaleDateString(undefined, { month: "long", year: "numeric" });
    let month = months[months.length - 1];
    if (!month || month.label !== label) {
      month = { label, days: [], runs: [] };
      months.push(month);
    }
    month.runs.push(run);
    let day = month.days[month.days.length - 1];
    if (!day || day.iso !== run.run_date) {
      day = { iso: run.run_date, runs: [] };
      month.days.push(day);
    }
    day.runs.push(run);
  }
  return months;
}

// same blue ramp as the Log a run page: light (fresh) to deep navy (wrecked)
function soreShade(level: number): string {
  const t = level / 10;
  return `hsl(220 ${85 - t * 15}% ${78 - t * 50}%)`;
}

function formatDuration(seconds: number): string {
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

const SOURCE_LABELS: Record<string, string> = {
  gpx: "From watch",
  tcx: "From watch",
  fit: "From watch",
  follow: "Tracked in Pathos",
  manual: "Logged by hand",
};

const FIT_LABELS: Record<string, string> = {
  yes: "Pick fit",
  sort_of: "Pick sort of fit",
  no: "Pick missed",
};

function avgPace(runs: PastRun[]): number {
  const km = runs.reduce((s, r) => s + r.distance_km, 0);
  const min = runs.reduce((s, r) => s + r.distance_km * r.pace_min_km, 0);
  return km ? min / km : 0;
}

function RunCard({ run, badge }: { run: PastRun; badge: string | null }) {
  const surfaceKey = run.surface_type ?? "own";
  const surface = run.surface_type ? SURFACE_LABELS[run.surface_type] : null;
  const details: string[] = [];
  const seconds = run.duration_s ?? run.distance_km * run.pace_min_km * 60;
  details.push(formatDuration(seconds));
  if (run.elevation_gain_m != null && run.elevation_gain_m > 0) {
    details.push(`${Math.round(run.elevation_gain_m * 3.281)} ft climb`);
  }
  if (run.avg_heart_rate) details.push(`${Math.round(run.avg_heart_rate)} bpm avg`);
  if (run.source && SOURCE_LABELS[run.source]) details.push(SOURCE_LABELS[run.source]);

  return (
    <article className={`lb-card surface-${surfaceKey}`}>
      <div className="lb-main">
        <div className="lb-title-row">
          <h3 className={run.route_name ? "" : "own"}>{run.route_name ?? "Your own route"}</h3>
          {badge && <span className="lb-badge">{badge}</span>}
        </div>
        <div className="lb-tags">
          {surface && <span className={`lb-surface surface-${surfaceKey}`}>{surface}</span>}
          {run.rating != null && (
            <span className="lb-stars" aria-label={`Rated ${run.rating} out of 5`}>
              {"★".repeat(run.rating)}
              <span className="off">{"★".repeat(5 - run.rating)}</span>
            </span>
          )}
          {run.pick_fit && <span className={`lb-fit fit-${run.pick_fit}`}>{FIT_LABELS[run.pick_fit]}</span>}
        </div>
        <p className="lb-details">{details.join("  ·  ")}</p>
        {run.notes && <p className="lb-notes">“{run.notes}”</p>}
      </div>

      <div className="lb-metrics">
        <div className="lb-metric">
          <span className="lb-value">{kmToMiles(run.distance_km).toFixed(1)}<small>mi</small></span>
          <span className="lb-label">Distance</span>
        </div>
        <div className="lb-metric">
          <span className="lb-value">
            {formatPacePerMile(run.pace_min_km).replace(" /mi", "")}<small>/mi</small>
          </span>
          <span className="lb-label">Pace</span>
        </div>
        <div className="lb-metric">
          {run.post_run_soreness != null ? (
            <>
              <span className="lb-value">{run.post_run_soreness}<small>/10</small></span>
              <span className="lb-sore" aria-hidden="true">
                {Array.from({ length: 10 }, (_, i) => (
                  <i key={i} style={i < run.post_run_soreness! ? { background: soreShade(i + 1) } : undefined} />
                ))}
              </span>
            </>
          ) : (
            <span className="lb-value muted">–</span>
          )}
          <span className="lb-label">Soreness</span>
        </div>
      </div>
    </article>
  );
}

function PastRunsPage() {
  const userId = localStorage.getItem("user_id");
  const [runs, setRuns] = useState<PastRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/runs/${userId}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Server responded with ${res.status}`);
        return res.json();
      })
      .then(setRuns)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [userId]);

  const totalMiles = runs.reduce((sum, r) => sum + kmToMiles(r.distance_km), 0);

  return (
    <div className="app runs-page">
      <header className="ci-intro runs-intro">
        <div>
          <span className="ci-eyebrow">Your logbook</span>
          <h1>
            {runs.length > 0 ? (
              <>
                <span className="bib">{runs.length}</span> run{runs.length === 1 ? "" : "s"},{" "}
                <span className="bib">{totalMiles.toFixed(1)}</span> miles.
              </>
            ) : (
              "Every run, logged."
            )}
          </h1>
          <p>Each run teaches Pathos a little more about what you like and how you recover.</p>
        </div>
        <Link to="/log-run" className="runs-log-button">+ Log a run</Link>
      </header>

      {loading && <p className="empty-state">Loading...</p>}
      {error && <p className="error">Error: {error}</p>}

      {!loading && !error && runs.length === 0 && (
        <div className="favs-empty">
          <h2>No runs yet</h2>
          <p>Log your first run and it'll show up here.</p>
          <Link to="/recommendations" className="favs-cta">Find today's route →</Link>
        </div>
      )}

      {groupRuns(runs).map((month) => {
        const miles = month.runs.reduce((s, r) => s + kmToMiles(r.distance_km), 0);
        const longest = month.runs.length > 1
          ? month.runs.reduce((a, b) => (b.distance_km > a.distance_km ? b : a)).id
          : null;
        const fastest = month.runs.length > 1
          ? month.runs.reduce((a, b) => (b.pace_min_km < a.pace_min_km ? b : a)).id
          : null;
        const [monthName, year] = month.label.split(" ");
        return (
          <section key={month.label} className="lb-month">
            <div className="lb-band">
              <div className="lb-band-title">
                <span className="lb-band-month">{monthName}</span>
                <span className="lb-band-year">{year}</span>
              </div>
              <div className="lb-band-stats">
                <div><b>{month.runs.length}</b><span>runs</span></div>
                <div><b>{miles.toFixed(1)}</b><span>miles</span></div>
                <div><b>{formatPacePerMile(avgPace(month.runs)).replace(" /mi", "")}</b><span>avg /mi</span></div>
              </div>
            </div>

            <ol className="lb-trail">
              {month.days.map((day) => {
                const date = parseDate(day.iso);
                return (
                  <li key={day.iso} className="lb-day">
                    <span className="lb-date">
                      <span className="lb-date-day">{String(date.getDate()).padStart(2, "0")}</span>
                      <span className="lb-date-weekday">{date.toLocaleDateString(undefined, { weekday: "short" })}</span>
                      {day.runs.length > 1 && <span className="lb-date-count">×{day.runs.length}</span>}
                    </span>
                    <div className="lb-day-runs">
                      {day.runs.map((run) => (
                        <RunCard
                          key={run.id}
                          run={run}
                          badge={run.id === longest ? "Longest" : run.id === fastest ? "Fastest" : null}
                        />
                      ))}
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>
        );
      })}
    </div>
  );
}

export default PastRunsPage;
