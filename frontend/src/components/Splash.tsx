import { useEffect, useState } from "react";
import "./Splash.css";

// Intro shown once per browser session, before the login page:
// the Pathos logo builds itself, then the runner takes off along the trail.
// Click / tap / any key skips it. Skipped entirely for reduced-motion users.

const SHOW_MS = 4200;   // how long the intro plays before fading out
const FADE_MS = 600;
const SEEN_KEY = "pathos_splash_seen";

function Limb({ cls, x, y, upper, lower, width }: {
  cls: string; x: number; y: number; upper: number; lower: number; width: number;
}) {
  // A two-segment limb hinged at (x, y): the upper segment rotates at the
  // hip/shoulder, the lower one at the knee/elbow. Both start pointing down.
  return (
    <g transform={`translate(${x} ${y})`}>
      <g className={`sp-upper ${cls}`}>
        <line x1="0" y1="0" x2="0" y2={upper} strokeWidth={width} />
        <g transform={`translate(0 ${upper})`}>
          <g className={`sp-lower ${cls}`}>
            <line x1="0" y1="0" x2="0" y2={lower} strokeWidth={width} />
          </g>
        </g>
      </g>
    </g>
  );
}

function Runner({ stroke, extra }: { stroke: string; extra: number }) {
  const leg = 5 + extra, arm = 4.4 + extra;
  return (
    <g className="sp-runner" stroke={stroke} strokeLinecap="round" fill="none">
      <g className="sp-bob">
        <Limb cls="b leg" x={60} y={48} upper={14.5} lower={15} width={leg} />
        <Limb cls="b arm" x={65.5} y={32} upper={10} lower={9.5} width={arm} />
        <line x1="60" y1="48" x2="65.5" y2="31.5" strokeWidth={8 + extra} />
        <circle cx="70.5" cy="22.5" r={5.6 + extra / 2} fill={stroke} stroke="none" />
        <Limb cls="a leg" x={60} y={48} upper={14.5} lower={15} width={leg} />
        <Limb cls="a arm" x={65.5} y={32} upper={10} lower={9.5} width={arm} />
      </g>
    </g>
  );
}

export function PathosRunner() {
  return (
    <svg className="sp-logo" viewBox="0 0 100 100" role="img" aria-label="Pathos logo">
      <defs>
        <linearGradient id="sp-shine-grad" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#fff" stopOpacity="0" />
          <stop offset="0.5" stopColor="#fff" stopOpacity="0.45" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <clipPath id="sp-tile">
          <rect x="0" y="0" width="100" height="100" rx="24" />
        </clipPath>
      </defs>
      <g clipPath="url(#sp-tile)">
        <rect className="sp-bg" x="0" y="0" width="100" height="100" />
        {/* scene builds in order: sun, hills, trail, then the runner */}
        <circle className="sp-sun" cx="30" cy="25" r="6.5" />
        <path className="sp-hills"
          d="M4 48 Q12 41 21 35 Q25 32.5 29 35 L36 40 Q40 37 43 38 Q52 43.5 64 48 Z" />
        <path className="sp-trail"
          d="M50 104 C20 98 2 90 14 84 C26 77 62 79 82 71.5 C98 65 95 56 79 52.5 C72 50.8 66 50 61 49.6" />
        {/* the runner: drawn twice, a blue outline pass then the white figure,
            so the limbs stay readable where they cross the white trail */}
        <Runner stroke="#0B6CEB" extra={3.2} />
        <Runner stroke="#fff" extra={0} />
        {/* a quick shine sweeps across once everything is in place */}
        <rect className="sp-shine" x="-40" y="-20" width="26" height="140" fill="url(#sp-shine-grad)" />
      </g>
    </svg>
  );
}

export default function Splash({ onDone }: { onDone: () => void }) {
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    try { sessionStorage.setItem(SEEN_KEY, "1"); } catch { /* ignore */ }
    const t1 = window.setTimeout(() => setLeaving(true), SHOW_MS);
    const t2 = window.setTimeout(onDone, SHOW_MS + FADE_MS);
    const skip = () => { setLeaving(true); window.setTimeout(onDone, FADE_MS); };
    window.addEventListener("keydown", skip, { once: true });
    return () => { window.clearTimeout(t1); window.clearTimeout(t2); window.removeEventListener("keydown", skip); };
  }, [onDone]);

  return (
    <div
      className={`splash${leaving ? " leaving" : ""}`}
      onClick={() => { setLeaving(true); window.setTimeout(onDone, FADE_MS); }}
    >
      <div className="sp-stage">
        <div className="sp-logo-wrap"><PathosRunner /></div>
        <div className="sp-word">Pathos</div>
        <div className="sp-tag">Run the route that fits today.</div>
      </div>
    </div>
  );
}

// Show the intro once per browser session, only to people who aren't logged
// in, and never to people who've asked their system to reduce motion.
export function shouldShowSplash(loggedIn: boolean): boolean {
  if (loggedIn) return false;
  try {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
    if (sessionStorage.getItem(SEEN_KEY)) return false;
  } catch {
    /* storage blocked: just show it */
  }
  return true;
}
