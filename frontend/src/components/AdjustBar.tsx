// "Adjust and regenerate": tweak today's check-in right from the results
// ("no hills", "a mile shorter", "out & back") or ask for 3 different routes,
// without redoing the whole check-in.

export type TodayPrefs = {
  checkin_id: string;
  hills_pref: "avoid" | "want" | null;
  shape_pref: "loop" | "out_and_back" | null;
  surface_preference: "trail" | "road" | null;
  quiet_streets: boolean;
  wants_scenic: boolean;
  planned_distance_miles: number | null;
  available_minutes: number | null;
};

export type Adjust = Partial<Omit<TodayPrefs, "checkin_id" | "available_minutes">>;

type Chip = { label: string; on: boolean; change: Adjust };

function AdjustBar({ prefs, currentMiles, busy, onAdjust, onDifferent }: {
  prefs: TodayPrefs | null;
  currentMiles: number | null;          // the plan, or what today's picks average, for -1 / +1 mi
  busy: boolean;
  onAdjust: (change: Adjust, label: string) => void;
  onDifferent: () => void;
}) {
  if (!prefs) return null;
  const miles = prefs.planned_distance_miles ?? currentMiles;
  const toggle = <K extends keyof Adjust>(key: K, value: Adjust[K], off: Adjust[K]): Adjust =>
    ({ [key]: prefs[key as keyof TodayPrefs] === value ? off : value } as Adjust);
  const chips: Chip[] = [
    { label: "No hills", on: prefs.hills_pref === "avoid", change: toggle("hills_pref", "avoid", null) },
    { label: "Hillier", on: prefs.hills_pref === "want", change: toggle("hills_pref", "want", null) },
    ...(miles ? [
      { label: "1 mi shorter", on: false, change: { planned_distance_miles: Math.max(1, Math.round((miles - 1) * 2) / 2) } },
      { label: "1 mi longer", on: false, change: { planned_distance_miles: Math.round((miles + 1) * 2) / 2 } },
    ] : []),
    { label: "Road", on: prefs.surface_preference === "road", change: toggle("surface_preference", "road", null) },
    { label: "Trail", on: prefs.surface_preference === "trail", change: toggle("surface_preference", "trail", null) },
    { label: "Loop", on: prefs.shape_pref === "loop", change: toggle("shape_pref", "loop", null) },
    { label: "Out & back", on: prefs.shape_pref === "out_and_back", change: toggle("shape_pref", "out_and_back", null) },
    { label: "Quiet streets", on: prefs.quiet_streets, change: { quiet_streets: !prefs.quiet_streets } },
    { label: "Scenic", on: prefs.wants_scenic, change: { wants_scenic: !prefs.wants_scenic } },
  ];
  return (
    <section className="adj-bar" aria-label="Adjust today's picks">
      <div className="adj-head">
        <span className="adj-title">Not quite right? Adjust and get new picks</span>
        <button type="button" className="adj-different" onClick={onDifferent} disabled={busy}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
               strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M16 3h5v5M4 20L21 3M21 16v5h-5M15 15l6 6M4 4l5 5" />
          </svg>
          3 different routes
        </button>
      </div>
      <div className="adj-chips">
        {chips.map((c) => (
          <button key={c.label} type="button" className={`adj-chip ${c.on ? "on" : ""}`} aria-pressed={c.on}
                  disabled={busy} onClick={() => onAdjust(c.change, c.label)}>
            {c.on && <span aria-hidden="true">✓ </span>}{c.label}
          </button>
        ))}
      </div>
      {miles != null && <span className="adj-note">Planned: {miles.toFixed(1)} mi. Changes update today's check-in.</span>}
    </section>
  );
}

export default AdjustBar;
