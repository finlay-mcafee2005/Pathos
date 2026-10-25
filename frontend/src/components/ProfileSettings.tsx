import { useEffect, useState } from "react";
import { API_URL } from "../utils/format";

// Settings: where you run from, and your running profile. Everything here was set at
// signup; now it can be changed (moved, home for the summer, training for a race...).

type Profile = {
  full_name: string;
  address: string | null;
  fitness_level: string;
  goal: string;
  weekly_mileage_avg: number;
  usual_pace_min_mile: number | null;
};

const GOALS = [
  { value: "race_training", title: "Train for a race", sub: "Hit distances, build fitness" },
  { value: "general_fitness", title: "Stay in shape", sub: "Consistent, enjoyable runs" },
  { value: "weight_loss", title: "Get in shape", sub: "Build the habit, steady progress" },
];
const LEVELS = [
  { value: "beginner", title: "Just starting", sub: "Building up to regular runs" },
  { value: "intermediate", title: "Regular runner", sub: "A few runs most weeks" },
  { value: "advanced", title: "Seasoned", sub: "High mileage, hills, races" },
];

function paceParts(p: number | null): [string, string] {
  if (!p) return ["", ""];
  const m = Math.floor(p);
  return [String(m), String(Math.round((p - m) * 60)).padStart(2, "0")];
}

function ProfileSettings() {
  const [saved, setSaved] = useState<Profile | null>(null);
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [goal, setGoal] = useState("general_fitness");
  const [level, setLevel] = useState("beginner");
  const [miles, setMiles] = useState("");
  const [paceMin, setPaceMin] = useState("");
  const [paceSec, setPaceSec] = useState("");
  const [status, setStatus] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  function load(p: Profile) {
    setSaved(p);
    setName(p.full_name ?? "");
    setAddress(p.address ?? "");
    setGoal(p.goal);
    setLevel(p.fitness_level);
    setMiles(p.weekly_mileage_avg ? String(Math.round(p.weekly_mileage_avg)) : "");
    const [m, s] = paceParts(p.usual_pace_min_mile);
    setPaceMin(m);
    setPaceSec(s);
  }

  useEffect(() => {
    fetch(`${API_URL}/me/profile`).then((r) => (r.ok ? r.json() : null)).then((p) => p && load(p)).catch(() => {});
  }, []);

  const pace = paceMin ? parseInt(paceMin, 10) + (parseInt(paceSec || "0", 10) || 0) / 60 : null;
  const paceBad = paceMin !== "" && (pace === null || isNaN(pace) || pace < 4 || pace > 20);
  const milesNum = miles === "" ? 0 : parseFloat(miles);
  const milesBad = isNaN(milesNum) || milesNum < 0 || milesNum > 200;
  const [sm, ss] = paceParts(saved?.usual_pace_min_mile ?? null);
  const changed = !!saved && (
    name.trim() !== (saved.full_name ?? "") || address.trim() !== (saved.address ?? "") ||
    goal !== saved.goal || level !== saved.fitness_level ||
    milesNum !== Math.round(saved.weekly_mileage_avg || 0) || paceMin !== sm || (paceMin !== "" && paceSec !== ss)
  );

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!saved || paceBad || milesBad) return;
    setSaving(true);
    setStatus(null);
    try {
      const res = await fetch(`${API_URL}/me/profile`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: name.trim() || undefined,
          address: address.trim() || undefined,
          goal,
          fitness_level: level,
          weekly_mileage_avg: milesNum,
          ...(pace ? { usual_pace_min_mile: pace } : { clear_pace: true }),
        }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(typeof body?.detail === "string" ? body.detail : "Couldn't save. Check the fields and try again.");
      load(body);
      setStatus({
        kind: "ok",
        text: body.location_label ? `Saved. Your runs now start from ${body.location_label}.` : "Saved. Your next picks will use these.",
      });
    } catch (err) {
      setStatus({ kind: "error", text: err instanceof Error ? err.message : "Something went wrong" });
    } finally {
      setSaving(false);
    }
  }

  if (!saved) return <section className="ac-card"><h2>Running profile</h2><p className="ac-hint">Loading…</p></section>;

  return (
    <form className="ac-card ps-form" onSubmit={save}>
      <h2>Running profile</h2>
      <p className="ac-hint ps-lead">What Pathos uses to pick your routes. Change it any time.</p>

      <label className="ps-field">
        <span className="ps-label">Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
      </label>

      <label className="ps-field">
        <span className="ps-label">Home location</span>
        <input value={address} onChange={(e) => setAddress(e.target.value)} placeholder="Address, cross streets or zip code"
               autoComplete="street-address" />
        <small className="ps-help">Where your runs start when you don't share your current location. A zip code or
          nearby intersection is enough.</small>
      </label>

      <div className="ps-field">
        <span className="ps-label">Goal</span>
        <div className="ps-options">
          {GOALS.map((g) => (
            <button key={g.value} type="button" className={`ps-option ${goal === g.value ? "on" : ""}`}
                    onClick={() => setGoal(g.value)} aria-pressed={goal === g.value}>
              <strong>{g.title}</strong><small>{g.sub}</small>
            </button>
          ))}
        </div>
      </div>

      <div className="ps-field">
        <span className="ps-label">Experience</span>
        <div className="ps-options">
          {LEVELS.map((l) => (
            <button key={l.value} type="button" className={`ps-option ${level === l.value ? "on" : ""}`}
                    onClick={() => setLevel(l.value)} aria-pressed={level === l.value}>
              <strong>{l.title}</strong><small>{l.sub}</small>
            </button>
          ))}
        </div>
      </div>

      <div className="ps-row">
        <label className="ps-field">
          <span className="ps-label">Usual weekly mileage</span>
          <span className="ps-inline">
            <input inputMode="decimal" value={miles} onChange={(e) => setMiles(e.target.value)} className="ps-num" />
            <span className="ps-unit">mi / week</span>
          </span>
        </label>
        <div className="ps-field">
          <span className="ps-label">Easy-run pace <span className="ps-optional">optional</span></span>
          <span className="ps-inline">
            <input inputMode="numeric" value={paceMin} onChange={(e) => setPaceMin(e.target.value.replace(/\D/g, "").slice(0, 2))}
                   className="ps-num small" aria-label="Minutes" placeholder="10" />
            <span className="ps-unit">:</span>
            <input inputMode="numeric" value={paceSec} onChange={(e) => setPaceSec(e.target.value.replace(/\D/g, "").slice(0, 2))}
                   className="ps-num small" aria-label="Seconds" placeholder="00" />
            <span className="ps-unit">/ mi</span>
          </span>
        </div>
      </div>
      {(paceBad || milesBad) && (
        <p className="vf-error">{paceBad ? "Pace should be between 4:00 and 20:00 per mile." : "Weekly mileage should be 0–200."}</p>
      )}

      {status && <p className={status.kind === "ok" ? "ps-ok" : "vf-error"}>{status.text}</p>}
      <div className="ps-actions">
        {changed && <button type="button" className="ac-cancel" onClick={() => { load(saved); setStatus(null); }}>Undo changes</button>}
        <button type="submit" className="ps-save" disabled={!changed || saving || paceBad || milesBad}>
          {saving ? "Saving…" : "Save changes"}
        </button>
      </div>
    </form>
  );
}

export default ProfileSettings;
