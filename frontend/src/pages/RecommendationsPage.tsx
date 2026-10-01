import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { MapContainer, TileLayer, Polyline, CircleMarker, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import ThemeToggle from "../components/ThemeToggle";

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
  route_id: string;
  route_name: string;
  score: number;
  reasons: string[];
  distance_km: number;
  elevation_gain_m: number;
  difficulty: string;
  surface_type?: string;
  path: [number, number][];
};

const DIFFICULTY_COLOR: Record<string, string> = {
  easy: "#4A7C59",
  moderate: "#C1642F",
  hard: "#8B2E2E",
};

function kmToMiles(km: number): number {
  return km * 0.621371;
}

function metersToFeet(m: number): number {
  return m * 3.28084;
}

function RecommendationsPage() {
  const navigate = useNavigate();
  const userId = localStorage.getItem("user_id");
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [photos, setPhotos] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function fetchPhoto(routeName: string) {
    const term = getSearchTerm(routeName);
    if (!term) return;
    try {
      const searchRes = await fetch(
        `https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(term + " California")}&format=json&origin=*&srlimit=1`
      );
      if (!searchRes.ok) return;
      const searchData = await searchRes.json();
      const bestTitle = searchData?.query?.search?.[0]?.title;
      if (!bestTitle) return;

      const summaryRes = await fetch(
        `https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(bestTitle)}`
      );
      if (!summaryRes.ok) return;
      const summaryData = await summaryRes.json();
      if (summaryData.thumbnail?.source && summaryData.thumbnail.width > 200) {
        setPhotos((prev) => ({ ...prev, [routeName]: summaryData.thumbnail.source }));
      }
    } catch {
      // no photo available, fine to skip silently
    }
  }

  async function fetchRecommendations() {
    if (!userId) {
      setError("No user found. Please sign up again.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `http://127.0.0.1:8000/recommendations/${userId}`
      );
      if (!response.ok) throw new Error(`Server responded with ${response.status}`);
      const data = await response.json();
      setRecommendations(data);
      data.forEach((rec: Recommendation) => fetchPhoto(rec.route_name));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <ThemeToggle />
      <header className="header">
        <h1>Today's routes</h1>
        <button onClick={fetchRecommendations} disabled={loading}>
          {loading ? "Scoring routes..." : "Get today's recommendations"}
        </button>
        {error && <p className="error">Error: {error}</p>}
      </header>

      <div className="route-list">
        {recommendations.map((rec, i) => (
          <div
            key={i}
            className="route-card"
            style={{ borderLeftColor: DIFFICULTY_COLOR[rec.difficulty] ?? "#999" }}
          >
            <div className="route-card-header">
              <span className="route-card-icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                  <path d="M12 21s-7-6.5-7-11.5A7 7 0 0112 2a7 7 0 017 7.5C19 14.5 12 21 12 21z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
                  <circle cx="12" cy="9.5" r="2.5" stroke="currentColor" strokeWidth="2" />
                </svg>
              </span>
              <h2>{rec.route_name}</h2>
              <span className="score">{rec.score.toFixed(0)}</span>
            </div>

            {photos[rec.route_name] && (
              <img
                src={photos[rec.route_name]}
                alt={rec.route_name}
                className="route-photo"
              />
            )}

            <div className="route-stats">
              <span className="distance">{kmToMiles(rec.distance_km).toFixed(1)} mi</span>
              <span className="elevation">{metersToFeet(rec.elevation_gain_m).toFixed(0)} ft gain</span>
              <span className={`difficulty ${rec.difficulty}`}>{rec.difficulty}</span>
              {rec.surface_type && rec.surface_type !== "unknown" && (
                <span className="surface">
                  {({ pavement: "road", trail: "trail", track: "track", mixed: "mixed" } as Record<string, string>)[rec.surface_type] ?? rec.surface_type}
                </span>
              )}
            </div>

            {rec.path.length > 1 && (
              <MapContainer
                center={rec.path[Math.floor(rec.path.length / 2)]}
                zoom={15}
                scrollWheelZoom={false}
                attributionControl={false}
                className="route-map-large"
              >
                <MapResizer path={rec.path} />
                <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
                <Polyline
                  positions={rec.path}
                  pathOptions={{ color: "#FFFFFF", weight: 7, opacity: 0.6 }}
                />
                <Polyline
                  positions={rec.path}
                  pathOptions={{ color: "#C1642F", weight: 4, opacity: 1 }}
                />
                <CircleMarker
                  center={rec.path[0]}
                  radius={6}
                  pathOptions={{ color: "#4A7C59", fillColor: "#4A7C59", fillOpacity: 1 }}
                />
                <CircleMarker
                  center={rec.path[rec.path.length - 1]}
                  radius={6}
                  pathOptions={{ color: "#8B2E2E", fillColor: "#8B2E2E", fillOpacity: 1 }}
                />
              </MapContainer>
            )}

            {rec.reasons.length > 0 && (
              <ul className="reasons">
                {rec.reasons.map((reason, j) => (
                  <li key={j}>{reason}</li>
                ))}
              </ul>
            )}

            <button
              className="log-run-button"
              onClick={() =>
                navigate("/log-run", {
                  state: { routeId: rec.route_id, routeName: rec.route_name },
                })
              }
            >
              Log this run
            </button>
          </div>
        ))}
      </div>

      <footer className="map-attribution">
        Map data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors,
        rendered with <a href="https://leafletjs.com" target="_blank" rel="noreferrer">Leaflet</a>. Photos via{" "}
        <a href="https://www.wikipedia.org" target="_blank" rel="noreferrer">Wikipedia</a>.
      </footer>
    </div>
  );
}

export default RecommendationsPage;