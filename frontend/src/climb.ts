// Total climb for a run, picked with a min–max slider (feet).
// Sent to the API as "LO_HI" (e.g. "200_900"), "LO_max" when there's no top, or "" for any.
// Old check-ins used fixed buckets ("under300", ...); those still read in.

export const CLIMB_MAX = 2000;   // the slider's top stop means "2,000+ ft"
export const CLIMB_STEP = 50;

const OLD: Record<string, [number, number]> = {
  under300: [0, 300], "300_700": [300, 700], "700_1200": [700, 1200], over1200: [1200, CLIMB_MAX],
};

export function parseClimb(v: string | null | undefined): [number, number] {
  if (!v) return [0, CLIMB_MAX];
  if (OLD[v]) return OLD[v];
  const m = /^(\d+)_(\d+|max)$/.exec(v);
  if (!m) return [0, CLIMB_MAX];
  const lo = Math.min(Number(m[1]), CLIMB_MAX);
  const hi = m[2] === "max" ? CLIMB_MAX : Math.min(Number(m[2]), CLIMB_MAX);
  return lo <= hi ? [lo, hi] : [hi, lo];
}

export function encodeClimb(lo: number, hi: number): string {
  if (lo <= 0 && hi >= CLIMB_MAX) return "";
  return `${lo}_${hi >= CLIMB_MAX ? "max" : hi}`;
}

/** old bucket names → the slider's form, so a copied check-in shows on the slider */
export function normalizeClimb(v: string | null | undefined): string {
  const [lo, hi] = parseClimb(v);
  return encodeClimb(lo, hi);
}

const ft = (n: number) => n.toLocaleString("en-US");

/** short label for chips: "Under 300 ft", "500+ ft", "300–900 ft", or "" for any */
export function climbShort(v: string | null | undefined): string {
  const [lo, hi] = parseClimb(v);
  if (lo <= 0 && hi >= CLIMB_MAX) return "";
  if (lo <= 0) return `Under ${ft(hi)} ft`;
  if (hi >= CLIMB_MAX) return `${ft(lo)}+ ft`;
  if (lo === hi) return `About ${ft(lo)} ft`;
  return `${ft(lo)}–${ft(hi)} ft`;
}

/** for sentences: "under 300 ft of climbing" */
export function climbWords(v: string | null | undefined): string {
  const s = climbShort(v);
  return s ? `${s.charAt(0).toLowerCase()}${s.slice(1)} of climbing` : "";
}
