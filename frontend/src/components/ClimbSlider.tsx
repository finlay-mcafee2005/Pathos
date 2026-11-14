import { useEffect, useState } from "react";
import { CLIMB_MAX, CLIMB_STEP, climbShort, encodeClimb, parseClimb } from "../climb";

// Two-handle slider for total climb (feet). With commitOnRelease, onChange fires only
// when a handle is let go (the Adjust card regenerates picks on every change).
function ClimbSlider({ value, onChange, commitOnRelease = false, disabled = false }: {
  value: string;
  onChange: (v: string) => void;
  commitOnRelease?: boolean;
  disabled?: boolean;
}) {
  const [range, setRange] = useState<[number, number]>(() => parseClimb(value));
  useEffect(() => { setRange(parseClimb(value)); }, [value]);
  const [lo, hi] = range;

  function move(which: 0 | 1, n: number) {
    const next: [number, number] = which === 0 ? [Math.min(n, hi), hi] : [lo, Math.max(n, lo)];
    setRange(next);
    if (!commitOnRelease) onChange(encodeClimb(next[0], next[1]));
  }
  function commit() {
    if (!commitOnRelease) return;
    const v = encodeClimb(lo, hi);
    if (v !== (value || "")) onChange(v);
  }
  // the fill lines up with the thumb centres (22px thumbs sit inset by half their width)
  const pct = (n: number) => (n / CLIMB_MAX) * 100;
  const label = climbShort(encodeClimb(lo, hi)) || "Any climb";
  const isAny = lo <= 0 && hi >= CLIMB_MAX;
  const ftTxt = (n: number) => (n >= CLIMB_MAX ? `${CLIMB_MAX.toLocaleString("en-US")}+ ft` : `${n.toLocaleString("en-US")} ft`);

  return (
    <div className={`climb-slider ${disabled ? "disabled" : ""}`}>
      <div className="climb-head">
        <span className={`climb-value ${isAny ? "any" : ""}`}>{label}</span>
        {!isAny && (
          <button type="button" className="climb-clear" disabled={disabled}
                  onClick={() => { setRange([0, CLIMB_MAX]); onChange(""); }}>
            Any
          </button>
        )}
      </div>
      <div className="climb-track-wrap">
        <div className="climb-track" />
        <div className="climb-fill" style={{ left: `calc(11px + (100% - 22px) * ${pct(lo) / 100})`, right: `calc(11px + (100% - 22px) * ${1 - pct(hi) / 100})` }} />
        <input type="range" min={0} max={CLIMB_MAX} step={CLIMB_STEP} value={lo} disabled={disabled}
               aria-label="Minimum total climb" aria-valuetext={ftTxt(lo)}
               className={lo > CLIMB_MAX * 0.9 ? "on-top" : ""}
               onChange={(e) => move(0, Number(e.target.value))}
               onPointerUp={commit} onKeyUp={commit} onBlur={commit} />
        <input type="range" min={0} max={CLIMB_MAX} step={CLIMB_STEP} value={hi} disabled={disabled}
               aria-label="Maximum total climb" aria-valuetext={ftTxt(hi)}
               onChange={(e) => move(1, Number(e.target.value))}
               onPointerUp={commit} onKeyUp={commit} onBlur={commit} />
      </div>
      <div className="climb-scale" aria-hidden="true">
        <span>0</span><span>500</span><span>1,000</span><span>1,500</span><span>2,000+</span>
      </div>
    </div>
  );
}

export default ClimbSlider;
