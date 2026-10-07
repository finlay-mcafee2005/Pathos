// Turn a route's [lat, lon] path into something a runner can follow:
// a GPX file for a watch / phone app, or a Google Maps walking route.

export type RunFormat = "single" | "out_and_back" | "repeat" | string | undefined;

function escapeXml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// The path as it will actually be run: an out-and-back goes to the end and
// comes back the same way; repeated loops are left as one loop (watches
// handle laps on their own) and noted in the description.
export function runPath(path: [number, number][], format: RunFormat): [number, number][] {
  if (format === "out_and_back" && path.length > 1) {
    return [...path, ...path.slice(0, -1).reverse()];
  }
  return path;
}

export function formatNote(format: RunFormat, repeatCount?: number): string {
  if (format === "out_and_back") return "Out-and-back: turn around at the far end and return the same way.";
  if (format === "repeat" && repeatCount && repeatCount > 1) return `Loop: run it ${repeatCount} times.`;
  return "";
}

export function buildGpx(name: string, path: [number, number][], description = ""): string {
  const points = path
    .map(([lat, lon]) => `      <trkpt lat="${lat.toFixed(6)}" lon="${lon.toFixed(6)}"></trkpt>`)
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Pathos" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata>
    <name>${escapeXml(name)}</name>${description ? `\n    <desc>${escapeXml(description)}</desc>` : ""}
  </metadata>
  <trk>
    <name>${escapeXml(name)}</name>${description ? `\n    <desc>${escapeXml(description)}</desc>` : ""}
    <type>running</type>
    <trkseg>
${points}
    </trkseg>
  </trk>
</gpx>
`;
}

export function downloadGpx(name: string, path: [number, number][], format?: RunFormat, repeatCount?: number) {
  if (path.length < 2) return;
  const gpx = buildGpx(`Pathos · ${name}`, runPath(path, format), formatNote(format, repeatCount));
  const blob = new Blob([gpx], { type: "application/gpx+xml" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `pathos-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")}.gpx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// --- Google Maps ---------------------------------------------------------
// Google only knows streets and some paths, so:
//  - trails: send directions to the trailhead only (waypoints on trails it
//    doesn't know make it detour to the nearest street address and back)
//  - roads: send only the route's real turning points, found by simplifying
//    the line, so Google follows the same streets instead of zig-zagging

function metersBetween(a: [number, number], b: [number, number]): number {
  const R = 6371000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b[0] - a[0]);
  const dLon = toRad(b[1] - a[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a[0])) * Math.cos(toRad(b[0])) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

// distance (m) from p to the segment a-b, on a flat local projection
function offsetFromSegment(p: [number, number], a: [number, number], b: [number, number]): number {
  const k = Math.cos((a[0] * Math.PI) / 180) * 111320;
  const ax = a[1] * k, ay = a[0] * 110540;
  const bx = b[1] * k, by = b[0] * 110540;
  const px = p[1] * k, py = p[0] * 110540;
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const t = len2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2)) : 0;
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

// Douglas-Peucker: keep the points where the route actually changes direction
function simplify(path: [number, number][], tolerance: number): [number, number][] {
  if (path.length < 3) return path;
  let maxD = 0;
  let idx = 0;
  for (let i = 1; i < path.length - 1; i++) {
    const d = offsetFromSegment(path[i], path[0], path[path.length - 1]);
    if (d > maxD) {
      maxD = d;
      idx = i;
    }
  }
  if (maxD <= tolerance) return [path[0], path[path.length - 1]];
  const left = simplify(path.slice(0, idx + 1), tolerance);
  const right = simplify(path.slice(idx), tolerance);
  return [...left.slice(0, -1), ...right];
}

// the fewest turning points (<= max) that still trace the route
export function turningPoints(path: [number, number][], max = 8): [number, number][] {
  let tol = 25;
  let pts = simplify(path, tol);
  while (pts.length - 2 > max && tol < 5000) {
    tol *= 1.5;
    pts = simplify(path, tol);
  }
  return pts.slice(1, -1);
}

export function isTrailSurface(surface?: string | null): boolean {
  return surface === "trail" || surface === "mixed";
}

export function googleMapsUrl(path: [number, number][], format?: RunFormat, surface?: string | null): string | null {
  if (path.length < 2) return null;
  const fmt = (p: [number, number]) => `${p[0].toFixed(6)},${p[1].toFixed(6)}`;
  const start = path[0];

  // directions to the start only. Used for every route: Google can't follow
  // a custom line, and waypoints on paths it doesn't know cause detours.
  if (surface === "start" || isTrailSurface(surface)) {
    const params = new URLSearchParams({ api: "1", destination: fmt(start) });
    return `https://www.google.com/maps/dir/?${params.toString()}`;
  }

  const isOutAndBack = format === "out_and_back";
  const end = path[path.length - 1];
  const isLoop = !isOutAndBack && metersBetween(start, end) < 150;
  const destination = isOutAndBack || !isLoop ? end : start;
  const waypoints = turningPoints(path, 8);
  const params = new URLSearchParams({
    api: "1",
    origin: fmt(start),
    destination: fmt(destination),
    travelmode: "walking",
  });
  if (waypoints.length) params.set("waypoints", waypoints.map(fmt).join("|"));
  return `https://www.google.com/maps/dir/?${params.toString()}`;
}

// how far along the route a point is (for the Follow view)
export function cumulativeMeters(path: [number, number][]): number[] {
  const out = [0];
  for (let i = 1; i < path.length; i++) out.push(out[i - 1] + metersBetween(path[i - 1], path[i]));
  return out;
}

export function nearestIndex(path: [number, number][], p: [number, number]): { index: number; meters: number } {
  let best = 0;
  let bestD = Infinity;
  for (let i = 0; i < path.length; i++) {
    const d = metersBetween(path[i], p);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return { index: best, meters: bestD };
}

export { metersBetween };
