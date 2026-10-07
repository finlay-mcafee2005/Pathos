import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { downloadGpx, googleMapsUrl, type RunFormat } from "../utils/routeExport";

type Props = {
  routeId?: string | null;
  name: string;
  // returns the full-resolution path; async so Favorites can fetch it on demand
  loadPath: () => Promise<[number, number][]> | [number, number][];
  format?: RunFormat;
  repeatCount?: number;
  surface?: string | null;
  compact?: boolean;
};

function RouteExportButtons({ routeId, name, loadPath, format, repeatCount, surface, compact = false }: Props) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState<"gpx" | "maps" | "follow" | null>(null);

  async function handleFollow() {
    setBusy("follow");
    try {
      const path = await loadPath();
      navigate("/follow", { state: { routeId, name, path, format, repeatCount, surface } });
    } finally {
      setBusy(null);
    }
  }

  async function handleGpx() {
    setBusy("gpx");
    try {
      downloadGpx(name, await loadPath(), format, repeatCount);
    } finally {
      setBusy(null);
    }
  }

  async function handleMaps() {
    // open the tab right away (inside the click) so popup blockers allow it
    const tab = window.open("", "_blank");
    setBusy("maps");
    try {
      const url = googleMapsUrl(await loadPath(), format, "start");
      if (url && tab) tab.location.href = url;
      else tab?.close();
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className={`route-export ${compact ? "compact" : ""}`}>
      <button type="button" className="route-export-btn follow" onClick={handleFollow} disabled={busy !== null}
        title="Full-screen map of the route with your live location">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
        </svg>
        {busy === "follow" ? "Loading..." : "Follow"}
      </button>
      <button type="button" className="route-export-btn" onClick={handleGpx} disabled={busy !== null}
        title="Download a GPX file for your watch or running app">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />
        </svg>
        {busy === "gpx" ? "Preparing..." : "GPX"}
      </button>
      <button type="button" className="route-export-btn" onClick={handleMaps} disabled={busy !== null}
        title="Directions to the start of the route in Google Maps">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M3 11l18-8-8 18-2-8-8-2z" />
        </svg>
        {busy === "maps" ? "Opening..." : "To start"}
      </button>
    </div>
  );
}

export default RouteExportButtons;
