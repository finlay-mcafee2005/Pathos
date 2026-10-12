import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import BackgroundSlideshow from "../components/BackgroundSlideshow";
import ThemeToggle from "../components/ThemeToggle";
import { API_URL } from "../utils/format";
import { saveSession } from "../utils/session";

function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).has("expired")
      ? "Your session ended. Please log in again."
      : null
  );

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(API_URL + "/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        throw new Error("Invalid email or password");
      }
      const data = await response.json();
      saveSession(data.user_id, data.token);
      navigate("/checkin");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="split-auth-page">
      <ThemeToggle />
      <div className="split-auth-panel">
        <div className="split-auth-content">
          <div className="auth-brand">
            <img src="/pathos-logo.png" alt="Pathos logo" width={72} height={72} />
            <span className="auth-brand-name">Pathos</span>
          </div>
          <p className="auth-eyebrow">Welcome back</p>
          <h1>Log in</h1>
          <p className="auth-sub">Check in and get today's routes.</p>

          <form className="form" onSubmit={handleSubmit}>
            <section className="form-section">
              <label>
                Email
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              </label>
              <label>
                Password
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
              </label>
            </section>

            {error && <p className="error">Error: {error}</p>}

            <button type="submit" disabled={loading}>
              {loading ? "Logging in..." : "Log in →"}
            </button>

            <p className="hint">
              Don't have an account? <Link to="/signup">Sign up</Link>
            </p>
          </form>
        </div>
      </div>
      <div className="split-auth-image">
        <BackgroundSlideshow />
        <div className="auth-photo-caption">
          <span className="auth-photo-pill">Los Angeles · Glendale · Pasadena</span>
          <h2>Run the route that fits today.</h2>
          <p>Tell Pathos how your body feels. It picks the trail or road to match.</p>
        </div>
      </div>
    </div>
  );
}

export default LoginPage;