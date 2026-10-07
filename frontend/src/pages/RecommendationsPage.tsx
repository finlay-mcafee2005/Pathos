import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { MapContainer, TileLayer, Polyline, CircleMarker, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useRouteActions } from "../components/RouteExportButtons";
import { type GroupMatch, formatMeetTime, sessionTitle } from "./GroupsPage";

function MapResizer({ path }: { path: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    setTimeout(() => {
      map.invalidateSize();
      if (path.length > 1) {
        const bounds = path.reduce(
          (b, [lat, lon]) => b.extend([lat, lon]),
          L.latLngBounds([path[0]])
        );
        map.fitBounds(bounds, { padding: [20, 20] });
      }
    }, 100);
  }, [map, path]);
  return null;
}

type Recommendation = {
  route_id: string | null;
  route_name: string;
  score: number;
  reasons: string[];
  distance_km: number;
  elevation_gain_m: number;
  difficulty: string;
  surface_type?: string;
  estimated_minutes?: number;
  score_breakdown?: Record<string, number>;
  effective_distance_km?: number;
  run_format?: string;
  repeat_count?: number;
  path: [number, number][];
};

// Plain-language explanation for each scoring factor.
// [when it raised the score, when it lowered the score]
const FACTOR_LABELS: Record<string, [string, string]> = {
  soreness: ["Easy on your sore muscles", "This surface is hard on a sore muscle"],
  injury: ["Easy on your injury", "This surface could aggravate your injury"],
  surface_relief: ["Softer surface for your sore muscles", "Surface is rough on sore muscles"],
  soreness_history: ["You usually recover well from runs like this", "You've been sorer after runs like this"],
  scenic: ["Scenic, like you asked", "Not very scenic"],
  surface_pref: ["The surface you asked for", "Not the surface you asked for"],
  adventure: ["Somewhere new, like you asked", "You've run it recently"],
  taste_surface: ["A surface you usually rate highly", "A surface you usually rate low"],
  taste_scenic: ["You tend to love scenic runs", "Scenic runs don't usually rate well for you"],
  taste_loop: ["You tend to enjoy loops", "You usually prefer point-to-point runs"],
  goal: ["Fits your training goal", "Doesn't fit your training goal"],
  distance: ["Right around the distance you want", "Longer or shorter than you want"],
  format: ["Simple to run at this distance", "Takes an out-and-back or extra laps to hit your distance"],
  terrain: ["Right amount of climbing for your energy", "Hillier or flatter than your energy calls for"],
  rhythm: ["Easy enough for a recovery day", "A bit much for a recovery day"],
  overload: ["Fits your weekly mileage", "Your weekly mileage is already high"],
  footing: ["Even footing after a short night", "Uneven trail after a short night's sleep"],
  proximity: ["Easy to get to from home", "A trek from home"],
  novelty: ["You haven't run it in a while", "You ran it recently"],
  rating: ["You've rated it well before", "You haven't rated it well before"],
  variety: ["Different from the routes above", "Similar to a route ranked above"],
  heat: ["Cool enough to run comfortably", "Hot out, and this one is long or hilly"],
  air: ["Clean air today", "Poor air quality for a run this long"],
  wind: ["Sheltered from the wind", "Strong wind on an exposed route"],
  mud: ["Dry trail conditions", "Trails may be muddy after recent rain"],
  daylight: ["Plenty of daylight", "You'd finish around or after sunset"],
  mood: ["Suits how you're feeling", "Not what you need in this mood"],
  intent: ["Fits the kind of run you wanted", "Not great for the kind of run you wanted"],
};

type Conditions = {
  run_time: string;
  temp_f: number | null;
  feels_like_f: number | null;
  uv_index: number | null;
  wind_mph: number | null;
  us_aqi: number | null;
  rain_last_48h_mm: number;
  sunset: string | null;
  minutes_until_sunset: number | null;
  is_tomorrow?: boolean;
  now_temp_f?: number | null;
  now_feels_like_f?: number | null;
};

function aqiLabel(aqi: number): string {
  if (aqi <= 50) return "Good";
  if (aqi <= 100) return "Moderate";
  if (aqi <= 150) return "Unhealthy for some";
  if (aqi <= 200) return "Unhealthy";
  return "Very unhealthy";
}

function formatClockTime(iso: string): string {
  const [, time] = iso.split("T");
  const [h, m] = time.split(":").map(Number);
  const hour12 = ((h + 11) % 12) + 1;
  return `${hour12}:${String(m).padStart(2, "0")} ${h < 12 ? "am" : "pm"}`;
}

// one short sentence about how conditions are shaping today's picks
function conditionsVerdict(c: Conditions): string {
  const feels = c.feels_like_f ?? c.temp_f;
  const notes: string[] = [];
  if (feels != null && feels >= 95) notes.push("dangerously hot");
  else if (feels != null && feels >= 85) notes.push("hot");
  if (c.us_aqi != null && c.us_aqi > 100) notes.push("hazy");
  if (c.rain_last_48h_mm >= 5) notes.push("muddy on the trails");
  if (c.minutes_until_sunset != null && c.minutes_until_sunset < 75) notes.push("losing daylight");
  if (c.wind_mph != null && c.wind_mph >= 20) notes.push("windy");
  if (notes.length === 0) return "Good running conditions. Nothing to work around today.";
  const list = notes.length > 1 ? `${notes.slice(0, -1).join(", ")} and ${notes[notes.length - 1]}` : notes[0];
  return `${list.charAt(0).toUpperCase() + list.slice(1)}, so Pathos is favoring routes that work around it.`;
}

// Clause for each factor, used to build a one-line headline from a route's top strengths
const HEADLINE_CLAUSES: Record<string, string> = {
  novelty: "you haven't run it in a while",
  proximity: "it starts right near home",
  terrain: "the climbing suits your energy today",
  distance: "it lands right on the distance you want",
  scenic: "it has the views you asked for",
  surface_pref: "it's on the surface you wanted",
  surface_relief: "the softer surface spares your sore muscles",
  adventure: "it's somewhere new, like you wanted",
  rating: "you've loved it before",
  taste_surface: "it's on your favorite kind of surface",
  taste_scenic: "it's scenic, and you love scenic runs",
  taste_loop: "it's a loop, your favorite format",
  goal: "it fits your training goal",
  rhythm: "it's gentle enough for a recovery day",
  soreness_history: "you usually bounce back well from runs like this",
  overload: "it keeps your weekly mileage in check",
  mood: "it suits how you're feeling today",
  intent: "it fits the kind of run you wanted",
};

function buildHeadline(breakdown: Record<string, number> | undefined, fallback?: string): string | null {
  const top = Object.entries(breakdown ?? {})
    .filter(([key, pts]) => pts >= 2 && HEADLINE_CLAUSES[key])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2)
    .map(([key]) => HEADLINE_CLAUSES[key]);
  if (top.length === 0) return fallback ?? null;
  const sentence = top.length === 2 ? `${top[0]}, and ${top[1]}` : top[0];
  return sentence.charAt(0).toUpperCase() + sentence.slice(1) + ".";
}

function factorLabel(key: string, pts: number): string {
  const pair = FACTOR_LABELS[key];
  if (!pair) return key.replace(/_/g, " ");
  return pts >= 0 ? pair[0] : pair[1];
}

const SURFACE_LABELS: Record<string, string> = {
  pavement: "Road",
  trail: "Trail",
  track: "Track",
  mixed: "Mixed",
};

function kmToMiles(km: number): number {
  return km * 0.621371;
}

function metersToFeet(m: number): number {
  return m * 3.28084;
}

// Card actions, grouped by purpose: run it / log it / save it, then take it with you
function RecActions({ rec, saved, onSave, onLog }: {
  rec: Recommendation;
  saved: boolean;
  onSave: () => void;
  onLog: () => void;
}) {
  const { busy, handleFollow, handleGpx, handleMaps } = useRouteActions({
    routeId: rec.route_id,
    name: rec.route_name,
    loadPath: () => rec.path,
    format: rec.run_format,
    repeatCount: rec.repeat_count,
    surface: rec.surface_type,
  });
  const hasPath = rec.path.length > 1;
  return (
    <div className="rec-actions-v2">
      <div className="rec-main-actions">
        {hasPath && (
          <button className="rec-btn primary" onClick={handleFollow} disabled={busy !== null}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M8 5.5v13a1 1 0 001.5.86l10.5-6.5a1 1 0 000-1.72L9.5 4.64A1 1 0 008 5.5z" />
            </svg>
            {busy === "follow" ? "Loading..." : "Start route"}
          </button>
        )}
        <button className="rec-btn secondary" onClick={onLog}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
          Log this run
        </button>
        {rec.route_id && (
          <button
            className={`rec-btn ghost ${saved ? "saved" : ""}`}
            aria-pressed={saved}
            onClick={onSave}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill={saved ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 20s-7-4.4-7-10a4 4 0 017-2.6A4 4 0 0119 10c0 5.6-7 10-7 10z" />
            </svg>
            {saved ? "Saved" : "Save"}
          </button>
        )}
      </div>

      {hasPath && (
        <div className="rec-take">
          <span className="rec-take-label">Take it with you</span>
          <div className="rec-take-tiles">
            <button className="rec-tile" onClick={handleGpx} disabled={busy !== null}>
              <span className="rec-tile-icon" aria-hidden="true">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />
                </svg>
              </span>
              <span className="rec-tile-text">
                <strong>{busy === "gpx" ? "Preparing..." : "GPX file"}</strong>
                <small>For your watch or running app</small>
              </span>
            </button>
            <button className="rec-tile" onClick={handleMaps} disabled={busy !== null}>
              <span className="rec-tile-icon" aria-hidden="true">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 11l18-8-8 18-2-8-8-2z" />
                </svg>
              </span>
              <span className="rec-tile-text">
                <strong>{busy === "maps" ? "Opening..." : "Directions"}</strong>
                <small>Get to the start in Google Maps</small>
              </span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function RecommendationsPage() {
  const navigate = useNavigate();
  const userId = localStorage.getItem("user_id");
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openReasoning, setOpenReasoning] = useState<Record<number, boolean>>({});
  const [favoriteIds, setFavoriteIds] = useState<Set<string>>(new Set());
  const [conditions, setConditions] = useState<Conditions | null>(null);
  const [groupToday, setGroupToday] = useState<GroupMatch | null>(null);

  // load saved routes so the Save buttons show the right state
  useEffect(() => {
    if (!userId) return;
    fetch(`http://127.0.0.1:8000/favorites/${userId}`)
      .then((res) => (res.ok ? res.json() : []))
      .then((favs: { route_id: string }[]) => setFavoriteIds(new Set(favs.map((f) => f.route_id))))
      .catch(() => {});
  }, [userId]);

  // fetch straight away, since you usually land here right after checking in
  useEffect(() => {
    fetchRecommendations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function toggleFavorite(routeId: string) {
    const isSaved = favoriteIds.has(routeId);
    const res = isSaved
      ? await fetch(`http://127.0.0.1:8000/favorites/${userId}/${routeId}`, { method: "DELETE" })
      : await fetch("http://127.0.0.1:8000/favorites", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_id: userId, route_id: routeId }),
        });
    if (!res.ok) return;
    setFavoriteIds((prev) => {
      const next = new Set(prev);
      if (isSaved) next.delete(routeId);
      else next.add(routeId);
      return next;
    });
  }

  function toggleReasoning(i: number) {
    setOpenReasoning((prev) => ({ ...prev, [i]: !prev[i] }));
  }

  async function fetchRecommendations() {
    if (!userId) {
      setError("No user found. Please log in again.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`http://127.0.0.1:8000/recommendations/${userId}`);
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        if (response.status === 404 && body?.detail === "No checkin for today") {
          throw new Error("checkin");
        }
        throw new Error(body?.detail ?? `Server responded with ${response.status}`);
      }
      const data = await response.json();
      setRecommendations(data);
      fetch(`http://127.0.0.1:8000/conditions/${userId}`)
        .then((res) => (res.ok ? res.json() : null))
        .then(setConditions)
        .catch(() => setConditions(null));
      fetch(`http://127.0.0.1:8000/groups/${userId}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((g) => setGroupToday(g?.today ?? null))
        .catch(() => setGroupToday(null));
      setOpenReasoning({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  const count = recommendations.length;

  return (
    <div className="app recs-page">
      <header className="recs-intro">
        <div>
          <span className="ci-eyebrow">Today's routes · {today}</span>
          <h1>
            {count > 0
              ? <>{count === 1 ? "One route" : `${["", "One", "Two", "Three", "Four", "Five"][count] ?? count} routes`} picked for how you feel.</>
              : "Your routes for today."}
          </h1>
          <p>Ranked by how well each one fits your check-in. Open "Why this route" to see the reasoning.</p>
        </div>
        <button className="recs-refresh" onClick={fetchRecommendations} disabled={loading}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className={loading ? "spin" : ""}>
            <path d="M20 11a8 8 0 10-2.3 5.7M20 4v7h-7" />
          </svg>
          {loading ? "Scoring..." : "Refresh"}
        </button>
      </header>

      {loading && count === 0 && (
        <div className="recs-loading">
          <span className="recs-loading-trail" />
          <p>Reading your check-in and scoring routes...</p>
        </div>
      )}

      {error === "checkin" && (
        <div className="recs-empty">
          <h2>Check in first</h2>
          <p>Pathos picks routes based on how you feel today, so start with a quick check-in.</p>
          <button className="logged-primary" onClick={() => navigate("/checkin")}>Start today's check-in</button>
        </div>
      )}
      {error && error !== "checkin" && <p className="error">Error: {error}</p>}

      {conditions && count > 0 && (() => {
        const feels = conditions.feels_like_f ?? conditions.temp_f;
        const rt = conditions.run_time.replace("tomorrow_", "");
        const base = { now: "Right now", morning: "morning", midday: "midday", evening: "evening" }[rt] ?? "today";
        const when = conditions.run_time === "now"
          ? "Right now"
          : conditions.is_tomorrow
            ? `Tomorrow ${base}`
            : `This ${base}`;
        const nowFeels = conditions.now_feels_like_f ?? conditions.now_temp_f;
        return (
          <section className="conditions">
            <div className="conditions-head">
              <span className="conditions-when">
                {when} near home
                {conditions.run_time !== "now" && nowFeels != null && (
                  <span className="conditions-now"> · {Math.round(nowFeels)}°F right now</span>
                )}
              </span>
              <p>{conditionsVerdict(conditions)}</p>
            </div>
            <div className="conditions-chips">
              {feels != null && (
                <span className={`cond-chip ${feels >= 85 ? "warn" : ""}`}>
                  <b>{Math.round(feels)}°F</b> feels like
                </span>
              )}
              {conditions.us_aqi != null && (
                <span className={`cond-chip ${conditions.us_aqi > 100 ? "warn" : ""}`}>
                  <b>AQI {Math.round(conditions.us_aqi)}</b> {aqiLabel(conditions.us_aqi)}
                </span>
              )}
              {conditions.uv_index != null && conditions.uv_index >= 6 && (
                <span className={`cond-chip ${conditions.uv_index >= 8 ? "warn" : ""}`}>
                  <b>UV {Math.round(conditions.uv_index)}</b> {conditions.uv_index >= 8 ? "very high" : "high"}
                </span>
              )}
              {conditions.wind_mph != null && conditions.wind_mph >= 12 && (
                <span className={`cond-chip ${conditions.wind_mph >= 20 ? "warn" : ""}`}>
                  <b>{Math.round(conditions.wind_mph)} mph</b> wind
                </span>
              )}
              {conditions.rain_last_48h_mm >= 1 && (
                <span className={`cond-chip ${conditions.rain_last_48h_mm >= 5 ? "warn" : ""}`}>
                  <b>{conditions.rain_last_48h_mm} mm</b> rain, last 48h
                </span>
              )}
              {conditions.sunset && (
                <span className={`cond-chip ${conditions.minutes_until_sunset != null && conditions.minutes_until_sunset < 75 ? "warn" : ""}`}>
                  <b>{formatClockTime(conditions.sunset)}</b> sunset
                </span>
              )}
            </div>
          </section>
        );
      })()}

      <div className="recs-list">
        {recommendations.map((rec, i) => {
          const miles = kmToMiles(rec.effective_distance_km ?? rec.distance_km);
          const surface = rec.surface_type && rec.surface_type !== "unknown" ? SURFACE_LABELS[rec.surface_type] ?? rec.surface_type : null;
          const saved = rec.route_id ? favoriteIds.has(rec.route_id) : false;
          const headline = buildHeadline(rec.score_breakdown, rec.reasons[0]);
          return (
            <article key={i} className={`rec-card ${i === 0 ? "top" : ""}`}>
              <div className="rec-map-wrap">
                {rec.path.length > 1 && (
                  <MapContainer
                    center={rec.path[Math.floor(rec.path.length / 2)]}
                    zoom={15}
                    scrollWheelZoom={false}
                    zoomControl={false}
                    attributionControl={false}
                    className="rec-map"
                  >
                    <MapResizer path={rec.path} />
                    <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
                    <Polyline positions={rec.path} pathOptions={{ color: "#FFFFFF", weight: 9, opacity: 0.9 }} />
                    <Polyline positions={rec.path} pathOptions={{ color: "#2563EB", weight: 4.5, opacity: 1 }} />
                    <CircleMarker
                      center={rec.path[0]}
                      radius={7}
                      pathOptions={{ color: "#FFFFFF", weight: 3, fillColor: "#1D4ED8", fillOpacity: 1 }}
                    />
                    <CircleMarker
                      center={rec.path[rec.path.length - 1]}
                      radius={5}
                      pathOptions={{ color: "#1D4ED8", weight: 3, fillColor: "#FFFFFF", fillOpacity: 1 }}
                    />
                  </MapContainer>
                )}
                <span className="rec-rank">{String(i + 1).padStart(2, "0")}</span>
                {i === 0 && <span className="rec-best">Best match today</span>}
              </div>

              <div className="rec-body">
                <div className="rec-title-row">
                  <h2>{rec.route_name}</h2>
                  <span className="rec-match" title="Fit score from your check-in">
                    <span className="rec-match-num">{rec.score.toFixed(0)}</span>
                    <span className="rec-match-label">fit</span>
                  </span>
                </div>

                {headline && <p className="rec-why">{headline}</p>}

                <div className="rec-splits">
                  <div>
                    <span className="rec-split-value">{miles.toFixed(1)}<small>mi</small></span>
                    <span className="rec-split-label">Distance</span>
                  </div>
                  {rec.estimated_minutes != null && (
                    <div>
                      <span className="rec-split-value">{rec.estimated_minutes}<small>min</small></span>
                      <span className="rec-split-label">Est. time</span>
                    </div>
                  )}
                  <div>
                    <span className="rec-split-value">{metersToFeet(rec.elevation_gain_m).toFixed(0)}<small>ft</small></span>
                    <span className="rec-split-label">Climb</span>
                  </div>
                  <div>
                    <span className={`rec-difficulty ${rec.difficulty}`}>
                      <span className="rec-difficulty-bars" aria-hidden="true">
                        <i /><i /><i />
                      </span>
                      {rec.difficulty}
                    </span>
                    <span className="rec-split-label">{surface ?? "Effort"}</span>
                  </div>
                </div>

                <RecActions
                  rec={rec}
                  saved={saved}
                  onSave={() => rec.route_id && toggleFavorite(rec.route_id)}
                  onLog={() => navigate("/log-run", { state: { routeId: rec.route_id, routeName: rec.route_name } })}
                />

                <button
                  className={`rec-why-row ${openReasoning[i] ? "open" : ""}`}
                  aria-expanded={!!openReasoning[i]}
                  onClick={() => toggleReasoning(i)}
                >
                  <span>Why this route</span>
                  <span className="rec-why-hint">{openReasoning[i] ? "Hide" : "See what went into the pick"}</span>
                  <span className={`chevron ${openReasoning[i] ? "open" : ""}`}>▾</span>
                </button>

                {openReasoning[i] && (() => {
                  const factors = Object.entries(rec.score_breakdown ?? {}).filter(([, pts]) => Math.abs(pts) >= 0.5);
                  const helped = factors.filter(([, p]) => p > 0).sort((x, y) => y[1] - x[1]);
                  const hurt = factors.filter(([, p]) => p < 0).sort((x, y) => x[1] - y[1]);
                  const biggest = Math.max(...factors.map(([, p]) => Math.abs(p)), 1);
                  const row = ([key, pts]: [string, number]) => (
                    <div className="rec-breakdown-row" key={key}>
                      <span>{factorLabel(key, pts)}</span>
                      <span className="rec-breakdown-bar">
                        <span className={pts >= 0 ? "plus" : "minus"} style={{ width: `${(Math.abs(pts) / biggest) * 100}%` }} />
                      </span>
                      <span className={`pts ${pts >= 0 ? "plus" : "minus"}`}>
                        {pts >= 0 ? "+" : "−"}
                        {Math.abs(pts).toFixed(0)}
                      </span>
                    </div>
                  );
                  return (
                    <div className="rec-reasoning">
                      {helped.length > 0 && (
                        <div className="rec-breakdown">
                          <span className="rec-breakdown-title">What helped</span>
                          {helped.map(row)}
                        </div>
                      )}
                      {hurt.length > 0 && (
                        <div className="rec-breakdown">
                          <span className="rec-breakdown-title">What held it back</span>
                          {hurt.map(row)}
                        </div>
                      )}
                      <p className="rec-breakdown-note">
                        Every route starts at 100. These add up to its fit score of <b>{rec.score.toFixed(0)}</b>.
                      </p>
                    </div>
                  );
                })()}
              </div>
            </article>
          );
        })}
      </div>

      {groupToday && count > 0 && (
        <Link to="/groups" className="group-suggest">
          <span className="group-suggest-icon" aria-hidden="true">👟</span>
          <span className="group-suggest-text">
            <span className="group-suggest-label">Rather run with a group?</span>
            <strong>
              {groupToday.club_name} · {formatMeetTime(groupToday.starts_at)} · {sessionTitle(groupToday)}
            </strong>
            <small>{groupToday.reasons[0]}</small>
          </span>
          <span className="group-suggest-fit">
            <b>{Math.round(groupToday.fit)}</b>fit
          </span>
        </Link>
      )}

      <footer className="map-attribution">
        Map data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors,
        rendered with <a href="https://leafletjs.com" target="_blank" rel="noreferrer">Leaflet</a>. Weather and air
        quality by <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo</a>.
      </footer>
    </div>
  );
}

export default RecommendationsPage;
