import { useEffect, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, useMap, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { API_URL } from "../utils/format";

// Check-in "Start from somewhere else" (Katie): search for a place or drop a pin, and
// today's routes are planned from there instead of where you are / home.

export type StartPoint = { lat: number; lon: number; label: string };

const DEFAULT_CENTER: [number, number] = [34.13, -118.2];   // northeast LA

function ClickToPin({ onPick }: { onPick: (lat: number, lon: number) => void }) {
  useMapEvents({ click: (e) => onPick(e.latlng.lat, e.latlng.lng) });
  return null;
}

function Recenter({ at }: { at: [number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (at) map.setView(at, Math.max(map.getZoom(), 14));
  }, [at, map]);
  return null;
}

export default function StartPicker({ value, onChange }: {
  value: StartPoint | null;
  onChange: (p: StartPoint | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [center, setCenter] = useState<[number, number] | null>(value ? [value.lat, value.lon] : null);

  async function search(e?: React.FormEvent | React.KeyboardEvent) {
    e?.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/check-area`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address: query.trim() }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(typeof body?.detail === "string" ? body.detail : "Couldn't find that place.");
      onChange({ lat: body.lat, lon: body.lon, label: body.label });
      setCenter([body.lat, body.lon]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't find that place.");
    } finally {
      setBusy(false);
    }
  }

  async function pin(lat: number, lon: number) {
    setError(null);
    const res = await fetch(`${API_URL}/check-point`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat, lon }),
    });
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      setError(typeof body?.detail === "string" ? body.detail : "No routes near that spot.");
      return;
    }
    onChange({ lat, lon, label: "Dropped pin" });
  }

  return (
    <div className="sp-box">
      <div className="sp-search">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") search(e); }}
          placeholder="A place, address or intersection (e.g. Rose Bowl)"
          aria-label="Where you'll start"
        />
        <button type="button" onClick={() => search()} disabled={busy || !query.trim()}>
          {busy ? "Finding…" : "Find"}
        </button>
      </div>
      <div className="sp-map">
        <MapContainer center={value ? [value.lat, value.lon] : DEFAULT_CENTER} zoom={value ? 14 : 12}
                      scrollWheelZoom={false} style={{ height: "100%", width: "100%" }}>
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                     attribution="&copy; OpenStreetMap" />
          <ClickToPin onPick={pin} />
          <Recenter at={center} />
          {value && (
            <CircleMarker center={[value.lat, value.lon]} radius={9}
                          pathOptions={{ color: "#fff", weight: 3, fillColor: "#1D4ED8", fillOpacity: 1 }} />
          )}
        </MapContainer>
      </div>
      {error ? <p className="sp-error">{error}</p>
        : value ? <p className="sp-ok">✓ Starting from <b>{value.label}</b>. Tap the map to move the pin.</p>
        : <p className="sp-hint">Search, or tap the map to drop a pin where you'll start.</p>}
    </div>
  );
}
