import { useEffect, useState } from "react";
import { API_URL } from "../utils/format";

// Gentle nudge for accounts that haven't clicked the email link yet.
// The app works either way; this just sits at the top until verified.
type Me = { email: string; email_verified: boolean };
const ME_KEY = "pathos_me";
const HIDE_KEY = "pathos_verify_hidden";

function readCache(): Me | null {
  try { return JSON.parse(sessionStorage.getItem(ME_KEY) || "null"); } catch { return null; }
}

function VerifyBanner() {
  const [me, setMe] = useState<Me | null>(readCache);
  const [hidden, setHidden] = useState(() => {
    try { return sessionStorage.getItem(HIDE_KEY) === "1"; } catch { return false; }
  });
  const [msg, setMsg] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (me?.email_verified) return;
    fetch(`${API_URL}/me`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: Me | null) => {
        if (!data) return;
        setMe(data);
        try { sessionStorage.setItem(ME_KEY, JSON.stringify(data)); } catch { /* ignore */ }
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!me || me.email_verified || hidden) return null;

  async function resend() {
    setSending(true);
    try {
      const res = await fetch(`${API_URL}/verify-email/resend`, { method: "POST" });
      const body = await res.json().catch(() => null);
      if (body?.already_verified) {
        const next = { ...me!, email_verified: true };
        setMe(next);
        try { sessionStorage.setItem(ME_KEY, JSON.stringify(next)); } catch { /* ignore */ }
        return;
      }
      setMsg(res.ok ? "Sent! Check your inbox (and spam)." : body?.detail ?? "Couldn't send right now.");
    } finally {
      setSending(false);
    }
  }

  function hide() {
    setHidden(true);
    try { sessionStorage.setItem(HIDE_KEY, "1"); } catch { /* ignore */ }
  }

  return (
    <div className="vb-banner" role="status">
      <span className="vb-icon" aria-hidden="true">✉️</span>
      <span className="vb-text">
        {msg ?? <>Verify your email. We sent a link to <strong>{me.email}</strong>.</>}
      </span>
      {!msg && (
        <button type="button" className="vb-resend" onClick={resend} disabled={sending}>
          {sending ? "Sending…" : "Resend"}
        </button>
      )}
      <button type="button" className="vb-close" onClick={hide} aria-label="Hide for now">✕</button>
    </div>
  );
}

export default VerifyBanner;
