// Backend address: set VITE_API_URL in Vercel (e.g. https://pathos-api.up.railway.app);
// falls back to the local backend when running on your Mac.
export const API_URL: string = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

export function kmToMiles(km: number): number {
  return km * 0.621371;
}

export function metersToFeet(m: number): number {
  return m * 3.28084;
}

// pace is stored as minutes per km; show it as m:ss per mile
export function formatPacePerMile(paceMinKm: number | null): string {
  if (paceMinKm == null) return "–";
  const minPerMile = paceMinKm / 0.621371;
  let mins = Math.floor(minPerMile);
  let secs = Math.round((minPerMile - mins) * 60);
  if (secs === 60) {
    mins += 1;
    secs = 0;
  }
  return `${mins}:${secs.toString().padStart(2, "0")} /mi`;
}

export function formatDate(iso: string): string {
  // dates come back as YYYY-MM-DD; parse as local time so they don't shift a day
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export const SURFACE_LABELS: Record<string, string> = {
  pavement: "Road",
  trail: "Trail",
  track: "Track",
  mixed: "Mixed",
};
