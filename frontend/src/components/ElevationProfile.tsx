import { useId, useState } from "react";

// "Where are the climbs": the run's elevation along the way (feet over miles), as drawn on
// the card (laps and out-and-backs included). Hover or drag a finger to read a point.
// Folded away behind "Show elevation" so the picks stay uncluttered.
export type Profile = { mi: number[]; ft: number[] };

const W = 600, H = 120, PAD_L = 38, PAD_R = 8, PAD_T = 10, PAD_B = 20;

function ElevationProfile({ profile }: { profile: Profile }) {
  const [hover, setHover] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const fillId = `rpe-fill-${useId().replace(/:/g, "")}`;   // one per card
  const { mi, ft } = profile;
  if (mi.length < 2) return null;
  const total = mi[mi.length - 1] || 1;
  const lo = Math.min(...ft), hi = Math.max(...ft);
  // give flat routes some headroom so 20 ft of wobble doesn't look like a mountain
  const span = Math.max(hi - lo, 150);
  const base = lo - (span - (hi - lo)) / 2;
  const x = (m: number) => PAD_L + (m / total) * (W - PAD_L - PAD_R);
  const y = (f: number) => PAD_T + (1 - (f - base) / span) * (H - PAD_T - PAD_B);
  const line = mi.map((m, i) => `${i ? "L" : "M"}${x(m).toFixed(1)},${y(ft[i]).toFixed(1)}`).join(" ");
  const area = `${line} L${x(total).toFixed(1)},${H - PAD_B} L${x(0).toFixed(1)},${H - PAD_B} Z`;
  // steepest uphill quarter-mile, marked on the chart
  let steep: [number, number] | null = null, best = 0;
  for (let i = 0, j = 0; i < mi.length; i++) {
    while (j < mi.length - 1 && mi[j] - mi[i] < 0.25) j++;
    const grade = mi[j] > mi[i] ? (ft[j] - ft[i]) / ((mi[j] - mi[i]) * 5280) : 0;
    if (grade > best) { best = grade; steep = [i, j]; }
  }
  const ticks = [0, total / 2, total];

  function move(e: React.PointerEvent<SVGSVGElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    const m = ((e.clientX - r.left) / r.width * W - PAD_L) / (W - PAD_L - PAD_R) * total;
    let k = 0;
    while (k < mi.length - 1 && mi[k + 1] < m) k++;
    setHover(Math.max(0, Math.min(mi.length - 1, k)));
  }

  const summary = `${Math.round(lo).toLocaleString("en-US")}–${Math.round(hi).toLocaleString("en-US")} ft`
    + (steep && best >= 0.04 ? ` · steepest ${(best * 100).toFixed(0)}%` : "");
  if (!open) {
    return (
      <button type="button" className="rpe-toggle" aria-expanded="false" onClick={() => setOpen(true)}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
             strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 18l6-9 4 5 3-4 5 8" /></svg>
        <span>Show elevation chart</span>
        <span className="rpe-toggle-sum">{summary}</span>
      </button>
    );
  }

  return (
    <figure className="rpe">
      <figcaption className="rpe-head">
        <span className="rpe-title">Elevation</span>
        <button type="button" className="rpe-hide" aria-expanded="true" onClick={() => setOpen(false)}>Hide</button>
        <span className="rpe-read">
          {hover != null
            ? `${mi[hover].toFixed(1)} mi · ${ft[hover].toLocaleString("en-US")} ft`
            : `${Math.round(lo).toLocaleString("en-US")}–${Math.round(hi).toLocaleString("en-US")} ft`
              + (steep && best >= 0.04 ? ` · steepest ${(best * 100).toFixed(0)}% at mile ${mi[steep[0]].toFixed(1)}` : "")}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="rpe-svg" role="img"
           aria-label={`Elevation from ${Math.round(lo)} to ${Math.round(hi)} feet over ${total.toFixed(1)} miles`}
           onPointerMove={move} onPointerDown={move} onPointerLeave={() => setHover(null)}>
        <defs>
          <linearGradient id={fillId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.32" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.04" />
          </linearGradient>
        </defs>
        {[base, base + span].map((f, i) => (
          <g key={i}>
            <line x1={PAD_L} x2={W - PAD_R} y1={y(f)} y2={y(f)} className="rpe-grid" />
            <text x={PAD_L - 6} y={y(f) + 4} textAnchor="end" className="rpe-axis">{Math.round(f).toLocaleString("en-US")}</text>
          </g>
        ))}
        <path d={area} fill={`url(#${fillId})`} />
        <path d={line} className="rpe-line" />
        {steep && best >= 0.04 && (
          <path d={mi.slice(steep[0], steep[1] + 1).map((m, i) => `${i ? "L" : "M"}${x(m)},${y(ft[steep![0] + i])}`).join(" ")}
                className="rpe-steep" />
        )}
        {ticks.map((t, i) => (
          <text key={i} x={x(t)} y={H - 5} textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"} className="rpe-axis">
            {t.toFixed(1)} mi
          </text>
        ))}
        {hover != null && (
          <g>
            <line x1={x(mi[hover])} x2={x(mi[hover])} y1={PAD_T} y2={H - PAD_B} className="rpe-cursor" />
            <circle cx={x(mi[hover])} cy={y(ft[hover])} r={4} className="rpe-dot" />
          </g>
        )}
      </svg>
    </figure>
  );
}

export default ElevationProfile;
