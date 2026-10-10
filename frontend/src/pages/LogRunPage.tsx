import { useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { API_URL } from "../utils/format";

// 47.5 minutes -> "47:30"; 75 minutes -> "1:15:00"
function formatClock(totalMinutes: number): string {
  const totalSecs = Math.round(totalMinutes * 60);
  const h = Math.floor(totalSecs / 3600);
  const m = Math.floor((totalSecs % 3600) / 60);
  const sec = String(totalSecs % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

const RATING_WORDS = ["", "Rough one", "Meh", "Solid", "Really good", "One of the best"];
const SORENESS_WORDS = ["Totally fresh", "Barely there", "Barely there", "A little tight", "Mild", "Mild", "Noticeable", "Sore", "Sore", "Very sore", "Wrecked"];

// one blue ramp, light sky blue (fresh) to deep navy (wrecked)
function soreShade(level: number): string {
  const t = level / 10;
  const lightness = 78 - t * 50; // 78% -> 28%
  const saturation = 85 - t * 15;
  return `hsl(220 ${saturation}% ${lightness}%)`;
}

function LogRunPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const userId = localStorage.getItem("user_id");

  // the route this run is linked to: from the page you came from, or matched from an imported file
  const [linkedRoute, setLinkedRoute] = useState<{ id?: string; name?: string } | null>(
    location.state?.routeId || location.state?.routeName
      ? { id: location.state?.routeId, name: location.state?.routeName }
      : null
  );
  const routeId = linkedRoute?.id;
  const recommendationId = location.state?.recommendationId as string | undefined;
  const [pickFit, setPickFit] = useState<"yes" | "sort_of" | "no" | null>(null);
  const cameFromPick = Boolean(recommendationId || routeId);
  const routeName = linkedRoute?.name;

  // data pulled from a watch file (GPX / TCX / FIT)
  type Imported = {
    filename: string;
    source: string;
    run_date: string | null;
    start_time: string | null;
    distance_km: number;
    duration_s: number | null;
    elevation_gain_m: number | null;
    avg_heart_rate: number | null;
    max_heart_rate: number | null;
    matched_route: { route_id: string; route_name: string; confidence: number } | null;
  };
  const [imported, setImported] = useState<Imported | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function importFile(file: File) {
    setImportError(null);
    if (!/\.(fit|gpx|tcx)$/i.test(file.name)) {
      setImportError("Choose a .fit, .gpx or .tcx file exported from your watch or running app.");
      return;
    }
    setImporting(true);
    try {
      const base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "");
        reader.onerror = () => reject(new Error("Couldn't read that file."));
        reader.readAsDataURL(file);
      });
      const res = await fetch(API_URL + "/runs/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, filename: file.name, data_base64: base64 }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.detail ?? `Server responded with ${res.status}`);
      const data: Imported = { ...body, filename: file.name };
      setImported(data);
      setDistanceMiles((data.distance_km / 1.60934).toFixed(2));
      if (data.duration_s) {
        setTotalMinutes(String(Math.floor(data.duration_s / 60)));
        setTotalSeconds(String(Math.round(data.duration_s % 60)));
      }
      if (data.matched_route) {
        setLinkedRoute({ id: data.matched_route.route_id, name: data.matched_route.route_name });
      }
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "Couldn't import that file.");
    } finally {
      setImporting(false);
    }
  }

  function clearImport() {
    setImported(null);
    setImportError(null);
    if (fileInput.current) fileInput.current.value = "";
  }

  // filled in when you arrive from a finished run on the Follow screen
  const prefill = location.state?.prefill as { miles: string; minutes: string; seconds: string; source?: string } | undefined;
  const [distanceMiles, setDistanceMiles] = useState(prefill?.miles ?? "");
  const [totalMinutes, setTotalMinutes] = useState(prefill?.minutes ?? "");
  const [totalSeconds, setTotalSeconds] = useState(prefill?.seconds ?? "");
  const [rating, setRating] = useState(3);
  const [postRunSoreness, setPostRunSoreness] = useState(3);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // filled in after a successful save; drives the confirmation screen
  const [logged, setLogged] = useState<{
    miles: number;
    minutes: number;
    paceMinMile: number;
    rating: number;
    soreness: number;
  } | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!userId) {
      setError("No user found. Please log in again.");
      return;
    }
    const distanceMi = parseFloat(distanceMiles) || 0;
    const totalTimeMin = (parseFloat(totalMinutes) || 0) + (parseFloat(totalSeconds) || 0) / 60;
    if (distanceMi <= 0 || totalTimeMin <= 0) {
      setError("Please enter your distance and total time.");
      return;
    }
    const distanceKmValue = distanceMi * 1.60934;
    const paceMinKm = totalTimeMin / distanceKmValue;
    // 2:30-15:00 min/km covers sprinting to walking; anything else is a typo
    if (paceMinKm < 2.5 || paceMinKm > 15) {
      const perMile = paceMinKm * 1.60934;
      setError(
        `That works out to ${Math.floor(perMile)}:${String(Math.round((perMile % 1) * 60)).padStart(2, "0")} per mile - double-check the distance and time.`
      );
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await fetch(API_URL + "/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          route_id: routeId || null,
          distance_km: distanceKmValue,
          pace_min_km: paceMinKm,
          rating,
          post_run_soreness: postRunSoreness,
          run_date: imported?.run_date ?? null,
          duration_s: Math.round(totalTimeMin * 60),
          elevation_gain_m: imported?.elevation_gain_m ?? null,
          avg_heart_rate: imported?.avg_heart_rate ?? null,
          max_heart_rate: imported?.max_heart_rate ?? null,
          source: imported?.source ?? prefill?.source ?? "manual",
          recommendation_id: recommendationId ?? null,
          pick_fit: cameFromPick ? pickFit : null,
        }),
      });
      if (!response.ok) throw new Error(`Server responded with ${response.status}`);
      setLogged({
        miles: distanceMi,
        minutes: totalTimeMin,
        paceMinMile: totalTimeMin / distanceMi,
        rating,
        soreness: postRunSoreness,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  if (logged) {
    return (
      <div className="app logged-page">
        <div className="logged-card">
          <div className="logged-check" aria-hidden="true">
            <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
              <path className="logged-check-path" d="M5 12.5l4.5 4.5L19 7.5" />
            </svg>
          </div>

          <h1>Run logged!</h1>
          <p className="logged-route">{routeName ?? "Custom run"}</p>

          <div className="logged-stats">
            <div className="logged-stat">
              <span className="logged-stat-value">{logged.miles.toFixed(1)}</span>
              <span className="logged-stat-label">miles</span>
            </div>
            <div className="logged-stat">
              <span className="logged-stat-value">{formatClock(logged.minutes)}</span>
              <span className="logged-stat-label">time</span>
            </div>
            <div className="logged-stat">
              <span className="logged-stat-value">{formatClock(logged.paceMinMile)}</span>
              <span className="logged-stat-label">pace /mi</span>
            </div>
          </div>

          <div className="logged-feel">
            <span className="run-stars" aria-label={`Rated ${logged.rating} out of 5`}>
              {"★".repeat(logged.rating)}
              <span className="run-stars-empty">{"★".repeat(5 - logged.rating)}</span>
            </span>
            <span className="logged-dot">·</span>
            <span>Soreness {logged.soreness}/10</span>
          </div>

          <p className="logged-message">
            Nice work. Pathos will use how this run felt to shape tomorrow's recommendations.
          </p>

          <div className="logged-actions">
            <button className="logged-primary" onClick={() => navigate("/runs")}>
              View past runs
            </button>
            <button className="logged-secondary" onClick={() => navigate("/stats")}>
              See my stats
            </button>
          </div>
          <button className="logged-link" onClick={() => navigate("/checkin")}>
            Back to check-in
          </button>
        </div>
      </div>
    );
  }

  const livePace = (() => {
    const mi = parseFloat(distanceMiles) || 0;
    const totalMin = (parseFloat(totalMinutes) || 0) + (parseFloat(totalSeconds) || 0) / 60;
    if (mi <= 0 || totalMin <= 0) return null;
    return formatClock(totalMin / mi);
  })();
  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });

  return (
    <div className="app logrun-page">
      <header className="ci-intro">
        <span className="ci-eyebrow">Log a run · {today}</span>
        <h1>How'd it go?</h1>
        {routeName ? (
          <span className="lr-route">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 21s-7-6.5-7-11.5A7 7 0 0112 2a7 7 0 017 7.5C19 14.5 12 21 12 21z" />
              <circle cx="12" cy="9.5" r="2.5" />
            </svg>
            {routeName}
          </span>
        ) : (
          <p>Your own route today. Log the numbers and how it felt.</p>
        )}
        {prefill && !imported && <p className="lr-prefilled">Distance and time are filled in from your tracked run. Adjust if needed.</p>}
      </header>

      <form onSubmit={handleSubmit} className="lr-form">
        {!imported ? (
          <div
            className={`lr-drop ${dragOver ? "over" : ""} ${importing ? "busy" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const f = e.dataTransfer.files?.[0];
              if (f) importFile(f);
            }}
            onClick={() => fileInput.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileInput.current?.click()}
          >
            <span className="lr-drop-icon" aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="7" />
                <path d="M12 9v3l2 1.5M9 2h6M9 22h6" />
              </svg>
            </span>
            <span className="lr-drop-text">
              <strong>{importing ? "Reading your run..." : "Import from your watch"}</strong>
              <small>
                Drop a .fit, .gpx or .tcx file here, or click to choose one. Export it from Garmin Connect, COROS,
                Strava, Polar, Suunto or HealthFit (Apple Watch).
              </small>
            </span>
            <input
              ref={fileInput}
              type="file"
              accept=".fit,.gpx,.tcx"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) importFile(f);
              }}
            />
          </div>
        ) : (
          <div className="lr-imported">
            <div className="lr-imported-head">
              <span className="lr-imported-badge">{imported.source.toUpperCase()}</span>
              <span className="lr-imported-name">{imported.filename}</span>
              <button type="button" className="su-remove" onClick={clearImport}>Remove</button>
            </div>
            <div className="lr-imported-facts">
              {imported.start_time && (
                <span>
                  {new Date(imported.start_time).toLocaleString(undefined, {
                    weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
                  })}
                </span>
              )}
              {imported.elevation_gain_m != null && <span>{Math.round(imported.elevation_gain_m * 3.28084)} ft climb</span>}
              {imported.avg_heart_rate != null && (
                <span>
                  {imported.avg_heart_rate} avg bpm{imported.max_heart_rate ? ` · ${imported.max_heart_rate} max` : ""}
                </span>
              )}
            </div>
            {imported.matched_route ? (
              linkedRoute?.id === imported.matched_route.route_id ? (
                <p className="lr-imported-match">
                  ✓ Matched to <b>{imported.matched_route.route_name}</b>.{" "}
                  <button type="button" className="su-remove" onClick={() => setLinkedRoute(null)}>Not this route</button>
                </p>
              ) : (
                <p className="lr-imported-match muted">
                  Not linked to a route.{" "}
                  <button
                    type="button"
                    className="su-remove"
                    onClick={() =>
                      setLinkedRoute({ id: imported.matched_route!.route_id, name: imported.matched_route!.route_name })
                    }
                  >
                    Link to {imported.matched_route.route_name}
                  </button>
                </p>
              )
            ) : (
              <p className="lr-imported-match muted">Didn't match a Pathos route, so it'll be logged as your own route.</p>
            )}
          </div>
        )}
        {importError && <p className="su-error">{importError}</p>}

        {/* The numbers */}
        <section className="ci-card lr-numbers">
          <div className="ci-card-head">
            <h2>The numbers</h2>
            <span className="lr-numbers-tag">Today's effort</span>
          </div>

          <div className="lr-fields">
            <label className="lr-field">
              <span className="lr-field-label">Distance</span>
              <span className="lr-bib-input">
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  placeholder="0.0"
                  value={distanceMiles}
                  onChange={(e) => setDistanceMiles(e.target.value)}
                  required
                />
                <span className="lr-unit">mi</span>
              </span>
            </label>

            <div className="lr-field">
              <span className="lr-field-label">Time <span className="lr-field-hint">min : sec</span></span>
              <span className="lr-bib-input lr-time">
                <input
                  type="number"
                  min="0"
                  placeholder="00"
                  aria-label="Minutes"
                  value={totalMinutes}
                  onChange={(e) => setTotalMinutes(e.target.value)}
                  required
                />
                <span className="lr-colon">:</span>
                <input
                  type="number"
                  min="0"
                  max="59"
                  placeholder="00"
                  aria-label="Seconds"
                  value={totalSeconds}
                  onChange={(e) => setTotalSeconds(e.target.value)}
                />
              </span>
            </div>
          </div>

          <div className={`lr-pace ${livePace ? "on" : ""}`}>
            <span className="lr-pace-label">Average pace</span>
            <span className="lr-pace-value">
              {livePace ?? "–:––"}
              <small>/mi</small>
            </span>
          </div>
        </section>

        {/* How it felt */}
        <section className="ci-card">
          <div className="ci-card-head">
            <h2>How it felt</h2>
          </div>

          <div className="lr-feel-row">
            <span className="ci-field-label">The run overall</span>
            <span className="ci-word">{RATING_WORDS[rating]}</span>
          </div>
          <div className="lr-stars" role="radiogroup" aria-label="Rate the run from 1 to 5">
            {Array.from({ length: 5 }, (_, i) => (
              <button
                key={i}
                type="button"
                role="radio"
                aria-checked={rating === i + 1}
                aria-label={`${i + 1} star${i ? "s" : ""}`}
                className={`lr-star ${i < rating ? "on" : ""}`}
                onClick={() => setRating(i + 1)}
              >
                <svg width="34" height="34" viewBox="0 0 24 24">
                  <path
                    d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"
                    fill={i < rating ? "currentColor" : "none"}
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            ))}
          </div>

          <div className="lr-divider" />

          <div className="lr-feel-row">
            <span className="ci-field-label">Soreness afterward</span>
            <span className="ci-readout">
              <span className="ci-big lr-small-big" style={{ color: soreShade(Math.max(postRunSoreness, 3)) }}>{postRunSoreness}</span>
              <span className="ci-word">{SORENESS_WORDS[postRunSoreness]}</span>
            </span>
          </div>
          <div className="lr-soreness" role="radiogroup" aria-label="Soreness from 0 to 10">
            {Array.from({ length: 11 }, (_, i) => (
              <button
                key={i}
                type="button"
                role="radio"
                aria-checked={postRunSoreness === i}
                aria-label={`Soreness ${i}`}
                className={`lr-sore-seg ${i <= postRunSoreness ? "on" : ""}`}
                style={i <= postRunSoreness ? { background: soreShade(i) } : undefined}
                onClick={() => setPostRunSoreness(i)}
              />
            ))}
          </div>
          <div className="ci-ends">
            <span>Fresh</span>
            <span>Wrecked</span>
          </div>

          {cameFromPick && (
            <>
              <div className="lr-divider" />
              <div className="lr-feel-row">
                <span className="ci-field-label">Did this pick fit how you felt today?</span>
                <span className="lr-fit-optional">Optional</span>
              </div>
              <div className="lr-fit" role="radiogroup" aria-label="Did this pick fit how you felt today?">
                {([
                  ["yes", "Yes", "Right call"],
                  ["sort_of", "Sort of", "Close enough"],
                  ["no", "No", "Not today"],
                ] as const).map(([value, label, sub]) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={pickFit === value}
                    className={`lr-fit-opt fit-${value} ${pickFit === value ? "on" : ""}`}
                    onClick={() => setPickFit(pickFit === value ? null : value)}
                  >
                    <span className="lr-fit-label">{label}</span>
                    <span className="lr-fit-sub">{sub}</span>
                  </button>
                ))}
              </div>
            </>
          )}
        </section>

        {error && <p className="error">{error}</p>}

        <button type="submit" className="lr-submit" disabled={loading}>
          {loading ? "Saving..." : "Save this run"}
          <span aria-hidden="true">→</span>
        </button>
      </form>
    </div>
  );
}

export default LogRunPage;