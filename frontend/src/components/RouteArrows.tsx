import { useMemo } from "react";
import { Marker } from "react-leaflet";
import L from "leaflet";

// Small arrows along a route line showing which way to run it (Lucy: "which way do I go round?").
// path = [lat, lon] points; count = how many arrows (spread evenly, none right at the ends).

function metres(a: [number, number], b: [number, number]): number {
  const kx = 111320 * Math.cos((a[0] * Math.PI) / 180);
  return Math.hypot((b[1] - a[1]) * kx, (b[0] - a[0]) * 110540);
}

function bearing(a: [number, number], b: [number, number]): number {
  const kx = Math.cos((a[0] * Math.PI) / 180);
  return (Math.atan2((b[1] - a[1]) * kx, b[0] - a[0]) * 180) / Math.PI;   // 0 = north, clockwise
}

const iconCache = new Map<number, L.DivIcon>();
function arrowIcon(deg: number, color: string): L.DivIcon {
  const key = Math.round(deg / 5) * 5 + (color === "#1D4ED8" ? 1000 : 0);
  let icon = iconCache.get(key);
  if (!icon) {
    icon = L.divIcon({
      className: "route-arrow",
      iconSize: [18, 18],
      iconAnchor: [9, 9],
      // a plain chevron sitting on the line (white edge so it reads on the blue), no badge
      html: `<svg viewBox="0 0 18 18" width="18" height="18" style="transform:rotate(${Math.round(deg / 5) * 5}deg)">
        <path d="M4.5 11.5 L9 6.5 L13.5 11.5" fill="none" stroke="#fff" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>
        <path d="M4.5 11.5 L9 6.5 L13.5 11.5" fill="none" stroke="${color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    });
    iconCache.set(key, icon);
  }
  return icon;
}

export default function RouteArrows({ path, count = 5, color = "#2563EB" }: {
  path: [number, number][];
  count?: number;
  color?: string;
}) {
  const arrows = useMemo(() => {
    if (path.length < 2 || count < 1) return [];
    const cum = [0];
    for (let i = 1; i < path.length; i++) cum.push(cum[i - 1] + metres(path[i - 1], path[i]));
    const total = cum[cum.length - 1];
    if (total < 300) return [];
    const out: { pos: [number, number]; deg: number }[] = [];
    let j = 1;
    for (let k = 1; k <= count; k++) {
      const at = (total * k) / (count + 1);
      while (j < path.length - 1 && cum[j] < at) j++;
      const a = path[j - 1], b = path[j];
      const t = cum[j] > cum[j - 1] ? (at - cum[j - 1]) / (cum[j] - cum[j - 1]) : 0;
      // direction over ~40 m around the point, so a GPS wiggle doesn't flip the arrow
      let i0 = j - 1, i1 = j;
      while (i0 > 0 && at - cum[i0] < 20) i0--;
      while (i1 < path.length - 1 && cum[i1] - at < 20) i1++;
      out.push({ pos: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], deg: bearing(path[i0], path[i1]) });
    }
    return out;
  }, [path, count]);
  return (
    <>
      {arrows.map((a, i) => (
        <Marker key={i} position={a.pos} icon={arrowIcon(a.deg, color)} interactive={false} keyboard={false} />
      ))}
    </>
  );
}
