// The streets from where they are to the start of a route, routed in the browser.
// The backend asks its own routing server first; when that isn't reachable (it isn't on
// Render) it sends back just the two end points, which drew a straight line through blocks
// and across freeways. The browser can reach the public OSRM foot server, so it fills in
// the real streets here (the same way it fetches elevations itself).
const FOOT_URL = "https://routing.openstreetmap.de/routed-foot/route/v1/foot";
const cache = new Map<string, Promise<[number, number][] | null>>();

export function footRoute(a: [number, number], b: [number, number]): Promise<[number, number][] | null> {
  const key = `${a[0].toFixed(5)},${a[1].toFixed(5)};${b[0].toFixed(5)},${b[1].toFixed(5)}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const job = (async () => {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 8000);
    try {
      const url = `${FOOT_URL}/${a[1].toFixed(6)},${a[0].toFixed(6)};${b[1].toFixed(6)},${b[0].toFixed(6)}`
        + "?overview=full&geometries=geojson";
      const res = await fetch(url, { signal: ctl.signal });
      if (!res.ok) return null;
      const data = await res.json();
      const coords: [number, number][] | undefined = data?.routes?.[0]?.geometry?.coordinates;
      if (!coords || coords.length < 2) return null;
      return coords.map(([lon, lat]) => [lat, lon] as [number, number]);
    } catch {
      return null;
    } finally {
      clearTimeout(timer);
    }
  })();
  cache.set(key, job);
  job.then((r) => { if (!r) cache.delete(key); });   // try again next time if it failed
  return job;
}

/** A street path that is really just its two ends (the backend's straight-line fallback). */
export function isStraight(path: [number, number][] | undefined): boolean {
  return !path || path.length <= 2;
}
