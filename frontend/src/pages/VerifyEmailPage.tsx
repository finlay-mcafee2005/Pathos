import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { API_URL } from "../utils/format";
import { isLoggedIn } from "../utils/session";

// Landing page for the "Verify my email" link. Works whether or not the
// person is logged in on this device (they may open the email on their phone).
type State = { kind: "working" } | { kind: "done"; email: string } | { kind: "error"; message: string };

function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<State>({ kind: "working" });
  const [resent, setResent] = useState<string | null>(null);
  const sent = useRef(false);
  const loggedIn = isLoggedIn();

  useEffect(() => {
    if (sent.current) return;           // StrictMode runs effects twice in dev
    sent.current = true;
    if (!token) {
      setState({ kind: "error", message: "This link is missing its code. Open the latest email from Pathos and tap the button again." });
      return;
    }
    fetch(API_URL + "/verify-email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (res) => {
        const body = await res.json().catch(() => null);
        if (!res.ok) throw new Error(body?.detail ?? "That link didn't work.");
        try { sessionStorage.removeItem("pathos_me"); } catch { /* ignore */ }
        setState({ kind: "done", email: body.email });
      })
      .catch((err) => setState({ kind: "error", message: err instanceof Error ? err.message : "That link didn't work." }));
  }, [token]);

  async function resend() {
    const res = await fetch(API_URL + "/verify-email/resend", { method: "POST" });
    const body = await res.json().catch(() => null);
    setResent(res.ok ? `Sent a new link to ${body?.email ?? "your email"}.` : body?.detail ?? "Couldn't send right now.");
  }

  return (
    <div className="vf-page">
      <div className="vf-card">
        <img src="/favicon.png" alt="" width={56} height={56} className="vf-logo" />
        {state.kind === "working" && (
          <>
            <div className="vf-spinner" aria-hidden="true" />
            <h1>Verifying your email…</h1>
          </>
        )}
        {state.kind === "done" && (
          <>
            <div className="vf-check" aria-hidden="true">✓</div>
            <h1>You're verified!</h1>
            <p><strong>{state.email}</strong> is confirmed. Thanks for helping keep Pathos accounts safe.</p>
            <Link to={loggedIn ? "/checkin" : "/login"} className="vf-button">
              {loggedIn ? "Go to today's check-in →" : "Log in to Pathos →"}
            </Link>
          </>
        )}
        {state.kind === "error" && (
          <>
            <div className="vf-check vf-warn" aria-hidden="true">!</div>
            <h1>That link didn't work</h1>
            <p>{state.message}</p>
            {loggedIn ? (
              <>
                <button type="button" className="vf-button" onClick={resend}>Send me a new link</button>
                {resent && <p className="vf-note">{resent}</p>}
              </>
            ) : (
              <Link to="/login" className="vf-button">Log in to send a new link →</Link>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default VerifyEmailPage;
