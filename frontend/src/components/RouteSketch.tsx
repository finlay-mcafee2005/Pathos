// Draws a route's shape as a single blue line on a contour-line tile.
// Takes [lat, lon] points; no map tiles needed.
function RouteSketch({ path, className = "" }: { path: [number, number][]; className?: string }) {
  const W = 320;
  const H = 200;
  const pad = 26;

  let line = "";
  let start: [number, number] | null = null;
  let end: [number, number] | null = null;

  if (path.length > 1) {
    const midLat = (path.reduce((s, p) => s + p[0], 0) / path.length) * (Math.PI / 180);
    // project: x = lon * cos(lat), y = -lat, so shapes aren't stretched
    const pts = path.map(([lat, lon]) => [lon * Math.cos(midLat), -lat]);
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const scale = Math.min((W - pad * 2) / (maxX - minX || 1), (H - pad * 2) / (maxY - minY || 1));
    const offX = (W - (maxX - minX) * scale) / 2;
    const offY = (H - (maxY - minY) * scale) / 2;
    const xy = pts.map(([x, y]) => [offX + (x - minX) * scale, offY + (y - minY) * scale] as [number, number]);
    line = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
    start = xy[0];
    end = xy[xy.length - 1];
  }

  const contours = Array.from({ length: 9 }, (_, i) => {
    const y = 10 + i * 24;
    return `M -10 ${y} C 60 ${y - 14}, 110 ${y + 14}, 170 ${y} S 280 ${y - 12}, 340 ${y + 6}`;
  });

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={`route-sketch ${className}`} role="img" aria-label="Route shape">
      {contours.map((d, i) => (
        <path key={i} d={d} className="route-sketch-contour" />
      ))}
      {line && (
        <>
          <path d={line} className="route-sketch-casing" />
          <path d={line} className="route-sketch-line" />
          {start && <circle cx={start[0]} cy={start[1]} r="6" className="route-sketch-start" />}
          {end && (Math.abs(end[0] - start![0]) > 4 || Math.abs(end[1] - start![1]) > 4) && (
            <circle cx={end[0]} cy={end[1]} r="4.5" className="route-sketch-end" />
          )}
        </>
      )}
    </svg>
  );
}

export default RouteSketch;
