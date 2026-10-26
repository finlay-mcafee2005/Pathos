import { useEffect, useState } from "react";
import { API_URL } from "../utils/format";

// Settings: routes they asked not to see again (from logging a run), with a way back.
type Avoided = { route_id: string; route_name: string; reason: string | null; since: string };

function AvoidedRoutes() {
  const userId = localStorage.getItem("user_id");
  const [rows, setRows] = useState<Avoided[] | null>(null);

  useEffect(() => {
    if (!userId) return;
    fetch(`${API_URL}/avoided/${userId}`).then((r) => (r.ok ? r.json() : [])).then(setRows).catch(() => setRows([]));
  }, [userId]);

  async function bringBack(id: string) {
    const res = await fetch(`${API_URL}/avoided/${userId}/${id}`, { method: "DELETE" });
    if (res.ok) setRows((prev) => (prev ?? []).filter((r) => r.route_id !== id));
  }

  return (
    <section className="ac-card">
      <h2>Routes you're avoiding</h2>
      {rows === null ? (
        <p className="ac-hint">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="ac-hint">None. When you log a run, you can tick "Don't recommend this route again".</p>
      ) : (
        <ul className="av-list">
          {rows.map((r) => (
            <li key={r.route_id}>
              <span className="av-text">
                <strong>{r.route_name}</strong>
                {r.reason && <small>“{r.reason}”</small>}
              </span>
              <button type="button" className="ac-cancel" onClick={() => bringBack(r.route_id)}>Bring back</button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default AvoidedRoutes;
