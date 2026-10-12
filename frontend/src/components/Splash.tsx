import { useEffect, useState } from "react";
import "./Splash.css";

// Intro shown once per browser session, before the login page:
// the Pathos logo builds itself, then the runner takes off along the trail.
// Click / tap / any key skips it. Skipped entirely for reduced-motion users.

const SHOW_MS = 3000;   // how long the intro plays before fading out
const FADE_MS = 500;
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
        <clipPath id="sp-tile">
          <rect x="0" y="0" width="100" height="100" rx="24" />
        </clipPath>
      </defs>
      <g clipPath="url(#sp-tile)">
        <rect className="sp-bg" x="0" y="0" width="100" height="100" />
        <circle className="sp-sun" cx="30" cy="25" r="6.5" />
        {/* hills drift past for a sense of speed (two copies loop seamlessly) */}
        <g className="sp-scenery">
          <path className="sp-hills"
            d="M2 47.5 Q10 40 20 34 Q24 31.5 28 34 L35 39 Q39 36 42 37 Q52 43 66 47.5 Z" />
          <path className="sp-hills"
            d="M106 47.5 Q114 40 124 34 Q128 31.5 132 34 L139 39 Q143 36 146 37 Q156 43 170 47.5 Z" />
        </g>
        {/* the winding trail draws itself in */}
        <path className="sp-trail" pathLength={100}
          d="M46 104 C18 96 4 86 16 78 C30 69 70 70 86 62 C96 57 86 51 64 48 L52 47.5" />
        {/* the runner: drawn twice, a blue outline pass then the white figure,
            so the limbs stay readable where they cross the white trail */}
        <Runner stroke="#0B6CEB" extra={3.2} />
        <Runner stroke="#fff" extra={0} />
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
        <PathosRunner />
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
