import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { API_URL } from "../utils/format";
import { saveSession } from "../utils/session";

function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(token ? null : "This link is missing its code. Ask for a new reset link.");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 6) return setError("Use at least 6 characters for your password.");
    if (password !== confirm) return setError("Those two passwords don't match.");
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(API_URL + "/password/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new Error(body?.detail ?? "That didn't work. Ask for a new reset link.");
      try { sessionStorage.removeItem("pathos_me"); } catch { /* ignore */ }
      saveSession(body.user_id, body.token);   // log them straight in
      navigate("/checkin");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="vf-page">
      <div className="vf-card">
        <img src="/favicon.png" alt="" width={56} height={56} className="vf-logo" />
        <h1>Choose a new password</h1>
        <p>At least 6 characters. You'll be logged in right after.</p>
        <form className="vf-form" onSubmit={submit}>
          <label>
            New password
            <input key={show ? "pw-shown" : "pw-hidden"} type={show ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" required autoFocus={!show} />
          </label>
          <label>
            Confirm new password
            <input key={show ? "cf-shown" : "cf-hidden"} type={show ? "text" : "password"} value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" required />
          </label>
          {/* Safari keeps AutoFilled password boxes masked even after switching to text,
              so the boxes are swapped for fresh ones (same values) when toggled */}
          <label className="vf-show">
            <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} /> Show passwords
          </label>
          {error && <p className="vf-error">{error}</p>}
          <button type="submit" className="vf-button" disabled={loading || !token}>{loading ? "Saving…" : "Save new password"}</button>
        </form>
        {error && /expired|used|missing/i.test(error) && <Link to="/forgot-password" className="vf-link">Send me a new link</Link>}
      </div>
    </div>
  );
}

export default ResetPasswordPage;
