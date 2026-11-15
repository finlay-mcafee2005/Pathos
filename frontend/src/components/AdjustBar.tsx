import { useEffect, useState } from "react";
import ClimbSlider from "./ClimbSlider";
import { climbShort } from "../climb";
// "Adjust and regenerate": tweak today's check-in right from the results
// ("no hills", "a mile longer", "out & back") or ask for 3 different routes,
// without redoing the whole check-in. Changes collect as a draft (several at once,
// distance in 0.5 mi steps) and apply together with "Update picks".

export type TodayPrefs = {
  checkin_id: string;
  hills_pref: "avoid" | "want" | null;
  shape_pref: "loop" | "out_and_back" | null;
  surface_preference: "trail" | "road" | null;
  quiet_streets: boolean;
  no_laps?: boolean;
  climb_range?: string | null;   // "LO_HI" / "LO_max" feet (see climb.ts)
  wants_scenic: boolean;
  planned_distance_miles: number | null;
  available_minutes: number | null;
};

export type Adjust = Partial<Omit<TodayPrefs, "checkin_id" | "available_minutes">>;

type Opt = { label: string; on: boolean; change: Adjust; icon?: string };

// small line icons (24x24, currentColor)
const ICONS: Record<string, string> = {
  flat: "M3 16h18",
  hill: "M3 18l6-9 4 5 3-4 5 8",
  road: "M8 3L5 21M16 3l3 18M12 5v3M12 11v3M12 17v3",
  trail: "M5 20c3-4 1-7 5-9s6-3 9-7",
  loop: "M12 5a7 7 0 1 1-6.3 4M5 4v5h5",
  oab: "M4 9h13l-3-3M20 15H7l3 3",
  once: "M12 4a8 8 0 1 0 8 8M20 4v5h-5",
  quiet: "M12 21s-7-6-7-11a7 7 0 0 1 14 0c0 5-7 11-7 11zM12 8v4",
  scenic: "M3 19l6-8 4 5 3-3 5 6zM17 5a2 2 0 1 0 0 .1",
};

function Icon({ d }: { d: string }) {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
  );
}

function Group({ label, opts, busy, onPick, wide }: {
  label: string; opts: Opt[]; busy: boolean; onPick: (c: Adjust) => void; wide?: boolean;
}) {
  return (
    <div className={`adj-group ${wide ? "wide" : ""}`}>
      <span className="adj-group-label">{label}</span>
      <div className="adj-seg" role="group" aria-label={label}>
        {opts.map((o) => (
          <button key={o.label} type="button" className={o.on ? "on" : ""} aria-pressed={o.on} disabled={busy}
                  onClick={() => onPick(o.change)}>
            {o.icon && <Icon d={ICONS[o.icon]} />}
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

const LABELS: Record<string, (v: unknown) => string> = {
  hills_pref: (v) => (v === "avoid" ? "flatter" : v === "want" ? "hillier" : "any hills"),
  surface_preference: (v) => (v ? String(v) : "any surface"),
  shape_pref: (v) => (v === "loop" ? "loop" : v === "out_and_back" ? "out & back" : "any shape"),
  climb_range: (v) => climbShort(v as string) || "any climb",
  quiet_streets: (v) => (v ? "quiet streets" : "no quiet-streets limit"),
  wants_scenic: (v) => (v ? "scenic" : "not scenic"),
  no_laps: (v) => (v ? "1 lap only" : "laps ok"),
  planned_distance_miles: (v) => `${Number(v).toFixed(1)} mi`,
};

function AdjustBar({ prefs, currentMiles, busy, onAdjust, onDifferent }: {
  prefs: TodayPrefs | null;
  currentMiles: number | null;          // the plan, or what today's picks average, for the distance stepper
  busy: boolean;
  onAdjust: (change: Adjust, label: string) => void;
  onDifferent: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Adjust>({});      // changes not applied yet
  // a new check-in came back (changes applied): start a fresh draft
  useEffect(() => { setDraft({}); }, [prefs?.checkin_id]);
  if (!prefs) return null;

  const view = { ...prefs, ...draft } as TodayPrefs;   // what the controls show
  const planMiles = prefs.planned_distance_miles ?? currentMiles;
  const miles = draft.planned_distance_miles ?? planMiles;
  // only what really differs from today's check-in
  const changes = Object.fromEntries(Object.entries(draft).filter(([k, v]) => {
    if (k === "planned_distance_miles") return v != null && planMiles != null && Math.abs((v as number) - planMiles) > 0.01;
    return (v ?? null) !== ((prefs as Record<string, unknown>)[k] ?? null);
  })) as Adjust;
  const nChanges = Object.keys(changes).length;

  const active = [
    prefs.hills_pref === "avoid" ? "Flatter" : prefs.hills_pref === "want" ? "Hillier" : null,
    prefs.surface_preference === "road" ? "Road" : prefs.surface_preference === "trail" ? "Trail" : null,
    prefs.shape_pref === "loop" ? "Loop" : prefs.shape_pref === "out_and_back" ? "Out & back" : null,
    climbShort(prefs.climb_range) || null,
    prefs.quiet_streets ? "Quiet streets" : null,
    prefs.wants_scenic ? "Scenic" : null,
    prefs.no_laps ? "1 lap only" : null,
  ].filter(Boolean) as string[];
  const flip = <K extends keyof Adjust>(key: K, value: Adjust[K], off: Adjust[K]): Adjust =>
    ({ [key]: view[key as keyof TodayPrefs] === value ? off : value } as Adjust);
  const pick = (c: Adjust) => setDraft((d) => ({ ...d, ...c }));
  const half = (x: number) => Math.round(x * 2) / 2;
  const stepMiles = (delta: number) => miles != null && pick({ planned_distance_miles: Math.max(0.5, half(miles + delta)) });

  function apply() {
    if (!nChanges) return;
    const label = Object.entries(changes).map(([k, v]) => (LABELS[k] ?? String)(v)).join(", ");
    onAdjust(changes, label);
  }

  return (
    <section className={`adj-card ${open ? "open" : "closed"}`} aria-label="Fine-tune today's picks">
      <div className="adj-top">
        <button type="button" className="adj-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
          <span className="adj-toggle-icon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
                 strokeLinecap="round" strokeLinejoin="round"><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0" />
              <circle cx="16" cy="6" r="2" /><circle cx="10" cy="12" r="2" /><circle cx="18" cy="18" r="2" /></svg>
          </span>
          <span className="adj-toggle-text">
            <span className="adj-title-row">
              <b>Adjust picks</b>
              <span className="adj-edit">{open ? "Done" : "Edit"}
                <span className={`chevron ${open ? "open" : ""}`} aria-hidden="true">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6" /></svg>
                </span>
              </span>
            </span>
            {/* what today's picks are set to, as small chips */}
            <span className="adj-set">
              {[planMiles != null ? `${planMiles.toFixed(1)} mi` : null, ...active].filter(Boolean).length
                ? [planMiles != null ? `${planMiles.toFixed(1)} mi` : null, ...active].filter(Boolean).map((t) => (
                    <span key={t as string} className="adj-set-chip">{t}</span>))
                : <span className="adj-set-empty">Hills, distance, surface, shape</span>}
            </span>
          </span>
        </button>
        <button type="button" className="adj-shuffle" onClick={onDifferent} disabled={busy} title="Show 3 routes you haven't seen yet">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
               strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M16 3h5v5M4 20L21 3M21 16v5h-5M15 15l6 6M4 4l5 5" />
          </svg>
          <span>New routes</span>
        </button>
      </div>

      {open && <>
      <div className="adj-grid">
        <Group label="Hills" busy={busy} onPick={pick} opts={[
          { label: "Flatter", icon: "flat", on: view.hills_pref === "avoid", change: flip("hills_pref", "avoid", null) },
          { label: "Hillier", icon: "hill", on: view.hills_pref === "want", change: flip("hills_pref", "want", null) },
        ]} />
        {miles != null && (
          <div className="adj-group">
            <span className="adj-group-label">Distance</span>
            <div className="adj-stepper">
              <button type="button" disabled={busy || miles <= 0.5} aria-label="Half a mile shorter"
                      onClick={() => stepMiles(-0.5)}>−</button>
              <span className="adj-miles"><b>{miles.toFixed(1)}</b> mi</span>
              <button type="button" disabled={busy} aria-label="Half a mile longer"
                      onClick={() => stepMiles(0.5)}>+</button>
            </div>
          </div>
        )}
        <Group label="Surface" busy={busy} onPick={pick} opts={[
          { label: "Road", icon: "road", on: view.surface_preference === "road", change: flip("surface_preference", "road", null) },
          { label: "Trail", icon: "trail", on: view.surface_preference === "trail", change: flip("surface_preference", "trail", null) },
        ]} />
        <Group label="Shape" busy={busy} onPick={pick} opts={[
          { label: "Loop", icon: "loop", on: view.shape_pref === "loop", change: flip("shape_pref", "loop", null) },
          { label: "Out & back", icon: "oab", on: view.shape_pref === "out_and_back", change: flip("shape_pref", "out_and_back", null) },
        ]} />
        <div className="adj-group wide">
          <span className="adj-group-label">Total climb (ft)</span>
          <ClimbSlider value={view.climb_range ?? ""} disabled={busy}
                       onChange={(v) => pick({ climb_range: v || null })} />
        </div>
        <Group label="Extras" wide busy={busy} onPick={pick} opts={[
          { label: "Quiet streets", icon: "quiet", on: view.quiet_streets, change: { quiet_streets: !view.quiet_streets } },
          { label: "Scenic", icon: "scenic", on: view.wants_scenic, change: { wants_scenic: !view.wants_scenic } },
          { label: "1 lap only", icon: "once", on: !!view.no_laps, change: { no_laps: !view.no_laps } },
        ]} />
      </div>
      <div className="adj-apply">
        <p className="adj-foot">
          {nChanges ? `${nChanges} change${nChanges === 1 ? "" : "s"} ready. Make as many as you like, then update.`
            : "Make as many changes as you like, then tap Update picks."}
        </p>
        <div className="adj-apply-buttons">
          {nChanges > 0 && (
            <button type="button" className="adj-reset" disabled={busy} onClick={() => setDraft({})}>Reset</button>
          )}
          <button type="button" className="adj-update" disabled={busy || !nChanges} onClick={apply}>
            Update picks
          </button>
        </div>
      </div>
      </>}
    </section>
  );
}

export default AdjustBar;
