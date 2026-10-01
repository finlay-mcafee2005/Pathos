import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import BackgroundSlideshow from "../components/BackgroundSlideshow";
import ThemeToggle from "../components/ThemeToggle";

function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("http://127.0.0.1:8000/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!response.ok) {
        throw new Error("Invalid email or password");
      }
      const data = await response.json();
      localStorage.setItem("user_id", data.user_id);
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
          <div className="auth-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
              <path d="M13 4l-3 8h4l-2 8 7-11h-4l2-5z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" fill="none" />
              <circle cx="6" cy="18" r="2" stroke="currentColor" strokeWidth="2" />
            </svg>
          </div>
          <p className="auth-eyebrow">Welcome back</p>
          <h1>Log in</h1>

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
              {loading ? "Logging in..." : "Log in"}
            </button>

            <p className="hint">
              Don't have an account? <Link to="/signup">Sign up</Link>
            </p>
          </form>
        </div>
      </div>
      <div className="split-auth-image">
        <BackgroundSlideshow />
      </div>
    </div>
  );
}

export default LoginPage;