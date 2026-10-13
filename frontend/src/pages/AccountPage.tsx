import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { API_URL } from "../utils/format";
import { clearSession } from "../utils/session";

type Me = { email: string; first_name: string; email_verified: boolean };

function AccountPage() {
  const navigate = useNavigate();
  const [me, setMe] = useState<Me | null>(null);
  const [verifyMsg, setVerifyMsg] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [sure, setSure] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/me`).then((r) => (r.ok ? r.json() : null)).then(setMe).catch(() => {});
  }, []);

  async function resend() {
    const res = await fetch(`${API_URL}/verify-email/resend`, { method: "POST" });
    const body = await res.json().catch(() => null);
    setVerifyMsg(res.ok ? "Sent! Check your inbox (and spam)." : body?.detail ?? "Couldn't send right now.");
  }

  async function deleteAccount(e: React.FormEvent) {
    e.preventDefault();
    setDeleting(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/me/delete`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.detail ?? "Couldn't delete your account. Try again.");
      clearSession();
      navigate("/login?deleted=1");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="app account-page">
      <header className="ci-intro">
        <span className="ci-eyebrow">Account</span>
        <h1>Your account</h1>
      </header>

      <section className="ac-card">
        <h2>Email</h2>
        <div className="ac-row">
          <span className="ac-email">{me?.email ?? "…"}</span>
          {me && (me.email_verified
            ? <span className="ac-badge ok">✓ Verified</span>
            : <span className="ac-badge">Not verified</span>)}
        </div>
        {me && !me.email_verified && (
          <p className="ac-hint">
            {verifyMsg ?? "Verify your email so you can reset your password if you forget it."}{" "}
            {!verifyMsg && <button type="button" className="ac-link" onClick={resend}>Send verification link</button>}
          </p>
        )}
      </section>

      <section className="ac-card danger">
        <h2>Delete account</h2>
        <p className="ac-hint">
          Permanently deletes your account and everything linked to it: check-ins, runs, saved routes and
          recommendations. Run-together groups you created pass to another member. This can't be undone.
        </p>
        {!open ? (
          <button type="button" className="ac-danger-btn" onClick={() => setOpen(true)}>Delete my account…</button>
        ) : (
          <form className="ac-delete" onSubmit={deleteAccount}>
            <label>
              Enter your password to confirm
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required autoFocus />
            </label>
            <label className="ac-check">
              <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} />
              I understand this permanently deletes my Pathos data.
            </label>
            {error && <p className="vf-error">{error}</p>}
            <div className="ac-actions">
              <button type="button" className="ac-cancel" onClick={() => { setOpen(false); setPassword(""); setSure(false); setError(null); }}>Cancel</button>
              <button type="submit" className="ac-danger-btn solid" disabled={!sure || !password || deleting}>
                {deleting ? "Deleting…" : "Delete forever"}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}

export default AccountPage;
