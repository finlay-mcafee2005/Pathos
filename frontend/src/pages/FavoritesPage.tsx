import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { API_URL, kmToMiles, metersToFeet, SURFACE_LABELS } from "../utils/format";
import { MapContainer, TileLayer, Polyline, CircleMarker, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useRouteActions } from "../components/RouteExportButtons";

type Favorite = {
  route_id: string;
  route_name: string;
  distance_km: number;
  elevation_gain_m: number;
  difficulty: string;
  surface_type: string;
  scenic: boolean;
  times_run: number;
  path?: [number, number][];
};

// fit the whole route into the small map once it has its size
function FitRoute({ path }: { path: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    const t = setTimeout(() => {
      map.invalidateSize();
      map.fitBounds(L.latLngBounds(path), { padding: [28, 28] });
    }, 50);
    return () => clearTimeout(t);
  }, [map, path]);
  return null;
}

function FavActions({ fav, loadPath, onLog }: {
  fav: Favorite;
  loadPath: () => Promise<[number, number][]>;
  onLog: () => void;
}) {
  const { busy, handleFollow, handleGpx, handleMaps } = useRouteActions({
    routeId: fav.route_id,
    name: fav.route_name,
    loadPath,
    surface: fav.surface_type,
  });
  return (
    <div className="fav-actions-v2">
      <div className="fav-main">
        <button className="rec-btn primary" onClick={handleFollow} disabled={busy !== null}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M8 5.5v13a1 1 0 001.5.86l10.5-6.5a1 1 0 000-1.72L9.5 4.64A1 1 0 008 5.5z" />
          </svg>
          {busy === "follow" ? "Loading..." : "Start route"}
        </button>
        <button className="rec-btn secondary" onClick={onLog}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
          Log run
        </button>
      </div>
      <div className="fav-take">
        <button className="rec-tile" onClick={handleGpx} disabled={busy !== null}>
          <span className="rec-tile-icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />
            </svg>
          </span>
          <span className="rec-tile-text">
            <strong>{busy === "gpx" ? "Preparing..." : "GPX file"}</strong>
            <small>For your watch</small>
          </span>
        </button>
        <button className="rec-tile" onClick={handleMaps} disabled={busy !== null}>
          <span className="rec-tile-icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 11l18-8-8 18-2-8-8-2z" />
            </svg>
          </span>
          <span className="rec-tile-text">
            <strong>{busy === "maps" ? "Opening..." : "Directions"}</strong>
            <small>To the start</small>
          </span>
        </button>
      </div>
    </div>
  );
}

function FavoritesPage() {
  const navigate = useNavigate();
  const userId = localStorage.getItem("user_id");
  const [favorites, setFavorites] = useState<Favorite[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/favorites/${userId}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Server responded with ${res.status}`);
        return res.json();
      })
      .then(setFavorites)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [userId]);

  async function loadFullPath(fav: Favorite): Promise<[number, number][]> {
    try {
      const res = await fetch(`${API_URL}/routes/${fav.route_id}/path`);
      if (res.ok) return (await res.json()).path;
    } catch {
      // fall back to the simplified path below
    }
    return fav.path ?? [];
  }

  async function removeFavorite(routeId: string) {
    const res = await fetch(`${API_URL}/favorites/${userId}/${routeId}`, { method: "DELETE" });
    if (res.ok) setFavorites((prev) => prev.filter((f) => f.route_id !== routeId));
  }

  const count = favorites.length;

  return (
    <div className="app favs-page">
      <header className="ci-intro">
        <span className="ci-eyebrow">Saved routes</span>
        <h1>{count > 0 ? "Routes worth running again." : "Your go-to routes live here."}</h1>
        <p>
          {count > 0
            ? `${count} saved route${count === 1 ? "" : "s"}. Tap one to log it, or check in to see how it fits today.`
            : "Save the routes you love and they'll be one tap away."}
        </p>
      </header>

      {loading && <p className="empty-state">Loading...</p>}
      {error && <p className="error">Error: {error}</p>}

      {!loading && !error && count === 0 && (
        <div className="favs-empty">
          <div className="favs-empty-art" aria-hidden="true">
            <svg viewBox="0 0 220 120">
              <path d="M14 96 C 50 96, 52 40, 92 44 S 130 92, 160 70 S 190 24, 206 26" className="favs-empty-trail" />
              <circle cx="14" cy="96" r="6" className="favs-empty-start" />
              <g transform="translate(192 8)">
                <path d="M14 26s-12-7.5-12-17a6.8 6.8 0 0112-4.4A6.8 6.8 0 0126 9c0 9.5-12 17-12 17z" className="favs-empty-heart" />
              </g>
            </svg>
          </div>
          <h2>No favorites yet</h2>
          <p>Tap the heart on any route in your recommendations to save it here.</p>
          <Link to="/recommendations" className="favs-cta">See today's routes →</Link>
        </div>
      )}

      <div className="favs-grid">
        {favorites.map((fav) => {
          const surface = SURFACE_LABELS[fav.surface_type];
          return (
            <article key={fav.route_id} className="fav-card">
              <div className="fav-art">
                {fav.path && fav.path.length > 1 ? (
                  <MapContainer
 center={fav.path[0]}
                    zoom={14}
                    className="fav-map"
                    zoomControl={false}
                    
                    dragging={false}
                    scrollWheelZoom={false}
                    doubleClickZoom={false}
                    touchZoom={false}
                    keyboard={false}
                    boxZoom={false}
                  >
                    <FitRoute path={fav.path} />
                    <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' />
                    <Polyline positions={fav.path} pathOptions={{ color: "#FFFFFF", weight: 8, opacity: 0.95 }} />
                    <Polyline positions={fav.path} pathOptions={{ color: "#2563EB", weight: 4, opacity: 1 }} />
                    <CircleMarker center={fav.path[0]} radius={6}
                      pathOptions={{ color: "#FFFFFF", weight: 3, fillColor: "#1D4ED8", fillOpacity: 1 }} />
                  </MapContainer>
                ) : (
                  <div className="fav-map fav-map-empty" />
                )}
                <button
                  className="fav-heart"
                  aria-label="Remove from favorites"
                  title="Remove from favorites"
                  onClick={() => removeFavorite(fav.route_id)}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
                    <path d="M12 20s-7-4.4-7-10a4 4 0 017-2.6A4 4 0 0119 10c0 5.6-7 10-7 10z" />
                  </svg>
                </button>
                <span className="fav-runs">
                  {fav.times_run === 0 ? "Not run yet" : `Run ${fav.times_run}×`}
                </span>
              </div>

              <div className="fav-body">
                <h2>{fav.route_name}</h2>
                <div className="fav-tags">
                  {surface && <span className="run-tag">{surface}</span>}
                  {fav.scenic && <span className="run-tag">Scenic</span>}
                  <span className={`rec-difficulty ${fav.difficulty}`}>
                    <span className="rec-difficulty-bars" aria-hidden="true"><i /><i /><i /></span>
                    {fav.difficulty}
                  </span>
                </div>

                <div className="fav-stats">
                  <div>
                    <span className="rec-split-value">{kmToMiles(fav.distance_km).toFixed(1)}<small>mi</small></span>
                    <span className="rec-split-label">Distance</span>
                  </div>
                  <div>
                    <span className="rec-split-value">{metersToFeet(fav.elevation_gain_m).toFixed(0)}<small>ft</small></span>
                    <span className="rec-split-label">Climb</span>
                  </div>
                </div>

                <FavActions fav={fav} loadPath={() => loadFullPath(fav)} onLog={() =>
                  navigate("/log-run", { state: { routeId: fav.route_id, routeName: fav.route_name } })} />
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

export default FavoritesPage;
