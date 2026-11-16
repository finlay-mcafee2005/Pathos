import { useEffect, useState } from "react";
import { API_URL } from "../utils/format";
import { DEFAULT_ORDER, fullOrder } from "../utils/priorities";
import PriorityRanker from "./PriorityRanker";

// Settings card: what matters most on a run (set at signup, changeable here).
function PrioritySettings() {
  const [saved, setSaved] = useState<string[] | null>(null);   // [] = never ranked
  const [order, setOrder] = useState<string[]>(DEFAULT_ORDER);
  const [status, setStatus] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/me/profile`).then((r) => (r.ok ? r.json() : null)).then((p) => {
      if (!p) return;
      setSaved(p.priorities ?? []);
      setOrder(fullOrder(p.priorities));
    }).catch(() => {});
  }, []);

  const changed = saved !== null && order.join() !== (saved.length ? fullOrder(saved) : DEFAULT_ORDER).join();
  const neverRanked = saved !== null && saved.length === 0;

  async function save(priorities: string[]) {
    setSaving(true);
    setStatus(null);
    try {
      const res = await fetch(`${API_URL}/me/profile`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ priorities }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.detail ?? "Couldn't save. Try again.");
      setSaved(body.priorities ?? priorities);
      setOrder(fullOrder(body.priorities ?? priorities));
      setStatus({ kind: "ok", text: priorities.length ? "Saved. Your next picks use this order." : "Cleared. Everything counts the same again." });
    } catch (err) {
      setStatus({ kind: "error", text: err instanceof Error ? err.message : "Something went wrong" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="ac-card ps-form">
      <h2>What matters most on a run</h2>
      <p className="ps-help ps-lead">
        Drag to put what you care about most at the top. Pathos leans on the top ones more when it picks your routes.
        {neverRanked && " You haven't ranked these yet, so right now they all count the same."}
      </p>
      <PriorityRanker order={order} onChange={(o) => { setOrder(o); setStatus(null); }} />
      {status && <p className={status.kind === "ok" ? "ps-ok" : "vf-error"}>{status.text}</p>}
      <div className="ps-actions">
        {!neverRanked && !changed && (
          <button type="button" className="ac-cancel" disabled={saving} onClick={() => save([])}>Make them all equal</button>
        )}
        {changed && (
          <button type="button" className="ac-cancel" onClick={() => { setOrder(saved && saved.length ? fullOrder(saved) : DEFAULT_ORDER); setStatus(null); }}>
            Undo changes
          </button>
        )}
        <button type="button" className="ps-save" disabled={saving || (!changed && !neverRanked)} onClick={() => save(order)}>
          {saving ? "Saving…" : "Save order"}
        </button>
      </div>
    </section>
  );
}

export default PrioritySettings;
