import { useState } from "react";
// "Adjust and regenerate": tweak today's check-in right from the results
// ("no hills", "a mile shorter", "out & back") or ask for 3 different routes,
// without redoing the whole check-in.

export type TodayPrefs = {
  checkin_id: string;
  hills_pref: "avoid" | "want" | null;
  shape_pref: "loop" | "out_and_back" | null;
  surface_preference: "trail" | "road" | null;
  quiet_streets: boolean;
  no_laps?: boolean;
  climb_range?: "under300" | "300_700" | "700_1200" | "over1200" | null;
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

function Group({ label, opts, busy, onAdjust, wide }: {
  label: string; opts: Opt[]; busy: boolean; onAdjust: (c: Adjust, label: string) => void; wide?: boolean;
}) {
  return (
    <div className={`adj-group ${wide ? "wide" : ""}`}>
      <span className="adj-group-label">{label}</span>
      <div className="adj-seg" role="group" aria-label={label}>
        {opts.map((o) => (
          <button key={o.label} type="button" className={o.on ? "on" : ""} aria-pressed={o.on} disabled={busy}
                  onClick={() => onAdjust(o.change, o.label)}>
            {o.icon && <Icon d={ICONS[o.icon]} />}
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function AdjustBar({ prefs, currentMiles, busy, onAdjust, onDifferent }: {
  prefs: TodayPrefs | null;
  currentMiles: number | null;          // the plan, or what today's picks average, for -1 / +1 mi
  busy: boolean;
  onAdjust: (change: Adjust, label: string) => void;
  onDifferent: () => void;
}) {
  const [open, setOpen] = useState(false);
  if (!prefs) return null;
  const miles = prefs.planned_distance_miles ?? currentMiles;
  const CLIMB_TXT: Record<string, string> = { under300: "<300 ft", "300_700": "300–700 ft", "700_1200": "700–1.2k ft", over1200: "1.2k+ ft" };
  const active = [
    prefs.hills_pref === "avoid" ? "Flatter" : prefs.hills_pref === "want" ? "Hillier" : null,
    prefs.surface_preference === "road" ? "Road" : prefs.surface_preference === "trail" ? "Trail" : null,
    prefs.shape_pref === "loop" ? "Loop" : prefs.shape_pref === "out_and_back" ? "Out & back" : null,
    prefs.climb_range ? CLIMB_TXT[prefs.climb_range] : null,
    prefs.quiet_streets ? "Quiet streets" : null,
    prefs.wants_scenic ? "Scenic" : null,
    prefs.no_laps ? "1 lap only" : null,
  ].filter(Boolean) as string[];
  const flip = <K extends keyof Adjust>(key: K, value: Adjust[K], off: Adjust[K]): Adjust =>
    ({ [key]: prefs[key as keyof TodayPrefs] === value ? off : value } as Adjust);
  const half = (x: number) => Math.round(x * 2) / 2;

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
            <b>Adjust picks</b>
            <small>{[miles != null ? `${miles.toFixed(1)} mi` : null, ...active].filter(Boolean).join(" · ") || "Hills, distance, surface, shape"}</small>
          </span>
          <span className={`chevron ${open ? "open" : ""}`} aria-hidden="true">▾</span>
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
        <Group label="Hills" busy={busy} onAdjust={onAdjust} opts={[
          { label: "Flatter", icon: "flat", on: prefs.hills_pref === "avoid", change: flip("hills_pref", "avoid", null) },
          { label: "Hillier", icon: "hill", on: prefs.hills_pref === "want", change: flip("hills_pref", "want", null) },
        ]} />
        {miles != null && (
          <div className="adj-group">
            <span className="adj-group-label">Distance</span>
            <div className="adj-stepper">
              <button type="button" disabled={busy || miles <= 1} aria-label="1 mile shorter"
                      onClick={() => onAdjust({ planned_distance_miles: Math.max(1, half(miles - 1)) }, "1 mi shorter")}>−</button>
              <span className="adj-miles"><b>{miles.toFixed(1)}</b> mi</span>
              <button type="button" disabled={busy} aria-label="1 mile longer"
                      onClick={() => onAdjust({ planned_distance_miles: half(miles + 1) }, "1 mi longer")}>+</button>
            </div>
          </div>
        )}
        <Group label="Surface" busy={busy} onAdjust={onAdjust} opts={[
          { label: "Road", icon: "road", on: prefs.surface_preference === "road", change: flip("surface_preference", "road", null) },
          { label: "Trail", icon: "trail", on: prefs.surface_preference === "trail", change: flip("surface_preference", "trail", null) },
        ]} />
        <Group label="Shape" busy={busy} onAdjust={onAdjust} opts={[
          { label: "Loop", icon: "loop", on: prefs.shape_pref === "loop", change: flip("shape_pref", "loop", null) },
          { label: "Out & back", icon: "oab", on: prefs.shape_pref === "out_and_back", change: flip("shape_pref", "out_and_back", null) },
        ]} />
        <Group label="Total climb (ft)" wide busy={busy} onAdjust={onAdjust} opts={([
          ["under300", "<300"], ["300_700", "300–700"], ["700_1200", "700–1.2k"], ["over1200", "1.2k+"],
        ] as const).map(([v, label]) => ({
          label, on: prefs.climb_range === v, change: { climb_range: prefs.climb_range === v ? null : v },
        }))} />
        <Group label="Extras" wide busy={busy} onAdjust={onAdjust} opts={[
          { label: "Quiet streets", icon: "quiet", on: prefs.quiet_streets, change: { quiet_streets: !prefs.quiet_streets } },
          { label: "Scenic", icon: "scenic", on: prefs.wants_scenic, change: { wants_scenic: !prefs.wants_scenic } },
          { label: "1 lap only", icon: "once", on: !!prefs.no_laps, change: { no_laps: !prefs.no_laps } },
        ]} />
      </div>
      <p className="adj-foot">Each change gets you new picks right away. Tap again to turn an option off.</p>
      </>}
    </section>
  );
}

export default AdjustBar;
