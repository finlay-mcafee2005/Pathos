import { useEffect, useState } from "react";
import { API_URL } from "../utils/format";
import UsualSpots, { type Spot } from "./UsualSpots";

// Settings card: places they usually run (set at signup, changeable here).
function UsualSpotsSettings() {
  const [saved, setSaved] = useState<Spot[] | null>(null);
  const [spots, setSpots] = useState<Spot[]>([]);
  const [status, setStatus] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/me/profile`).then((r) => (r.ok ? r.json() : null)).then((p) => {
      if (!p) return;
      setSaved(p.usual_spots ?? []);
      setSpots(p.usual_spots ?? []);
    }).catch(() => {});
  }, []);

  const sig = (l: Spot[]) => l.map((s) => `${s.key}:${s.often}`).join();
  const changed = saved !== null && sig(spots) !== sig(saved);

  async function save() {
    setSaving(true);
    setStatus(null);
    try {
      const res = await fetch(`${API_URL}/me/profile`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ usual_spots: spots.map(({ key, often }) => ({ key, often })) }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.detail ?? "Couldn't save. Try again.");
      setSaved(body.usual_spots ?? spots);
      setSpots(body.usual_spots ?? spots);
      setStatus({ kind: "ok", text: "Saved. Your next picks use these." });
    } catch (err) {
      setStatus({ kind: "error", text: err instanceof Error ? err.message : "Something went wrong" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="ac-card ps-form">
      <h2>Where you usually run</h2>
      <p className="ps-help ps-lead">
        Pathos looks for runs like these, and mixes in new places instead of sending you to the same ones every day.
      </p>
      <UsualSpots value={spots} onChange={(l) => { setSpots(l); setStatus(null); }} />
      {status && <p className={status.kind === "ok" ? "ps-ok" : "vf-error"}>{status.text}</p>}
      <div className="ps-actions">
        {changed && <button type="button" className="ac-cancel" onClick={() => { setSpots(saved ?? []); setStatus(null); }}>Undo changes</button>}
        <button type="button" className="ps-save" disabled={!changed || saving} onClick={save}>
          {saving ? "Saving…" : "Save places"}
        </button>
      </div>
    </section>
  );
}

export default UsualSpotsSettings;
