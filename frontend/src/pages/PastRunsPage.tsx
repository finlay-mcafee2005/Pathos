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
};

function parseDate(iso: string): Date {
  // YYYY-MM-DD parsed as local time so it doesn't shift a day
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

// group runs under "October 2026"-style headings, keeping newest-first order
function groupByMonth(runs: PastRun[]): [string, PastRun[]][] {
  const groups = new Map<string, PastRun[]>();
  for (const run of runs) {
    const key = parseDate(run.run_date).toLocaleDateString(undefined, { month: "long", year: "numeric" });
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(run);
  }
  return [...groups.entries()];
}

// same blue ramp as the Log a run page: light (fresh) to deep navy (wrecked)
function soreShade(level: number): string {
  const t = level / 10;
  return `hsl(220 ${85 - t * 15}% ${78 - t * 50}%)`;
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

      {groupByMonth(runs).map(([month, monthRuns]) => (
        <section key={month} className="log-month">
          <h2 className="log-month-title">
            <span>{month}</span>
            <small>
              {monthRuns.length} run{monthRuns.length === 1 ? "" : "s"} ·{" "}
              {monthRuns.reduce((sum, r) => sum + kmToMiles(r.distance_km), 0).toFixed(1)} mi
            </small>
          </h2>
          <ol className="log-trail">
            {monthRuns.map((run) => {
              const date = parseDate(run.run_date);
              const surface = run.surface_type ? SURFACE_LABELS[run.surface_type] : null;
              return (
                <li key={run.id} className="log-entry">
                  <span className="log-date">
                    <span className="log-date-day">{String(date.getDate()).padStart(2, "0")}</span>
                    <span className="log-date-weekday">
                      {date.toLocaleDateString(undefined, { weekday: "short" })}
                    </span>
                  </span>

                  <article className="log-card">
                    <div className="log-main">
                      <h3>{run.route_name ?? "Your own route"}</h3>
                      <div className="run-tags">
                        {surface && <span className="run-tag">{surface}</span>}
                        {run.rating != null && (
                          <span className="log-stars" aria-label={`Rated ${run.rating} out of 5`}>
                            {"★".repeat(run.rating)}
                            <span className="run-stars-empty">{"★".repeat(5 - run.rating)}</span>
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="log-metrics">
                      <div>
                        <span className="rec-split-value">{kmToMiles(run.distance_km).toFixed(1)}<small>mi</small></span>
                        <span className="rec-split-label">Distance</span>
                      </div>
                      <div>
                        <span className="rec-split-value">
                          {formatPacePerMile(run.pace_min_km).replace(" /mi", "")}<small>/mi</small>
                        </span>
                        <span className="rec-split-label">Pace</span>
                      </div>
                      {run.post_run_soreness != null && (
                        <div>
                          <span className="rec-split-value">
                            {run.post_run_soreness}<small>/10</small>
                          </span>
                          <span className="rec-split-label">Soreness</span>
                          <span className="log-sore-meter">
                            {Array.from({ length: 10 }, (_, i) => (
                              <i
                                key={i}
                                style={i < run.post_run_soreness! ? { background: soreShade(i + 1) } : undefined}
                              />
                            ))}
                          </span>
                        </div>
                      )}
                    </div>
                  </article>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}

export default PastRunsPage;
