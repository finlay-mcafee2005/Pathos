import { useState } from "react";
import { Link } from "react-router-dom";
import { API_URL } from "../utils/format";

function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(API_URL + "/password/forgot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (!res.ok) throw new Error("Couldn't send right now. Try again in a moment.");
      setSent(true);
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
        {sent ? (
          <>
            <div className="vf-check" aria-hidden="true">✉</div>
            <h1>Check your email</h1>
            <p>If <strong>{email}</strong> has a Pathos account, we sent a link to reset your password. It works for 1 hour. Check spam if it doesn't show up.</p>
            <Link to="/login" className="vf-button">Back to log in</Link>
          </>
        ) : (
          <>
            <h1>Forgot your password?</h1>
            <p>Enter your email and we'll send you a link to choose a new one.</p>
            <form className="vf-form" onSubmit={submit}>
              <label>
                Email
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required autoFocus />
              </label>
              {error && <p className="vf-error">{error}</p>}
              <button type="submit" className="vf-button" disabled={loading}>{loading ? "Sending…" : "Send reset link"}</button>
            </form>
            <Link to="/login" className="vf-link">Back to log in</Link>
          </>
        )}
      </div>
    </div>
  );
}

export default ForgotPasswordPage;
