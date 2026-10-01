import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import ThemeToggle from "../components/ThemeToggle";

function LogRunPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const userId = localStorage.getItem("user_id");

  const routeId = location.state?.routeId as string | undefined;
  const routeName = location.state?.routeName as string | undefined;

  const [distanceMiles, setDistanceMiles] = useState("");
  const [totalMinutes, setTotalMinutes] = useState("");
  const [totalSeconds, setTotalSeconds] = useState("");
  const [rating, setRating] = useState(3);
  const [postRunSoreness, setPostRunSoreness] = useState(3);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!userId) {
      setError("No user found. Please log in again.");
      return;
    }
    const distanceMi = parseFloat(distanceMiles) || 0;
    const totalTimeMin = (parseFloat(totalMinutes) || 0) + (parseFloat(totalSeconds) || 0) / 60;
    if (distanceMi <= 0 || totalTimeMin <= 0) {
      setError("Please enter your distance and total time.");
      return;
    }
    const distanceKmValue = distanceMi * 1.60934;
    const paceMinKm = totalTimeMin / distanceKmValue;
    // 2:30-15:00 min/km covers sprinting to walking; anything else is a typo
    if (paceMinKm < 2.5 || paceMinKm > 15) {
      const perMile = paceMinKm * 1.60934;
      setError(
        `That works out to ${Math.floor(perMile)}:${String(Math.round((perMile % 1) * 60)).padStart(2, "0")} per mile - double-check the distance and time.`
      );
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const response = await fetch("http://127.0.0.1:8000/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          route_id: routeId || null,
          distance_km: distanceKmValue,
          pace_min_km: paceMinKm,
          rating,
          post_run_soreness: postRunSoreness,
        }),
      });
      if (!response.ok) throw new Error(`Server responded with ${response.status}`);
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  if (success) {
    return (
      <div className="app">
        <header className="header">
          <h1>Run logged</h1>
        </header>
        <p>Nice work! This will help shape tomorrow's recommendations.</p>
        <button onClick={() => navigate("/checkin")}>Back to check-in</button>
      </div>
    );
  }

  return (
    <div className="app">
      <ThemeToggle />
      <header className="header">
        <h1>Log your run</h1>
        {routeName && <p>Route: {routeName}</p>}
      </header>

      <form className="form" onSubmit={handleSubmit}>
        <section className="form-section">
          <label>
            Distance (miles)
            <input
              type="number"
              step="0.1"
              min="0"
              value={distanceMiles}
              onChange={(e) => setDistanceMiles(e.target.value)}
              required
            />
          </label>

          <label>Total run time</label>
          <div className="injury-row">
            <label>
              Minutes
              <input
                type="number"
                min="0"
                value={totalMinutes}
                onChange={(e) => setTotalMinutes(e.target.value)}
                required
              />
            </label>
            <label>
              Seconds
              <input
                type="number"
                min="0"
                max="59"
                value={totalSeconds}
                onChange={(e) => setTotalSeconds(e.target.value)}
              />
            </label>
          </div>

          {distanceMiles && (totalMinutes || totalSeconds) && (
            <p className="calculated-pace">
              Avg pace: {(() => {
                const mi = parseFloat(distanceMiles) || 0;
                const totalMin = (parseFloat(totalMinutes) || 0) + (parseFloat(totalSeconds) || 0) / 60;
                if (mi === 0) return "—";
                const paceMin = totalMin / mi;
                const min = Math.floor(paceMin);
                const sec = Math.round((paceMin - min) * 60);
                return `${min}:${sec.toString().padStart(2, "0")}/mi`;
              })()}
            </p>
          )}

          <label>
            <div className="scale-header">
              <span>How was the run overall?</span>
              <span className="slider-value-badge">{rating}/5</span>
            </div>
            <input
              type="range"
              min="1"
              max="5"
              value={rating}
              onChange={(e) => setRating(parseInt(e.target.value))}
            />
            <div className="scale-endpoints">
              <span>Poor</span>
              <span>Great</span>
            </div>
          </label>

          <label>
            <div className="scale-header">
              <span>Soreness after this run</span>
              <span className="slider-value-badge">{postRunSoreness}/10</span>
            </div>
            <input
              type="range"
              min="0"
              max="10"
              value={postRunSoreness}
              onChange={(e) => setPostRunSoreness(parseInt(e.target.value))}
            />
            <div className="scale-endpoints">
              <span>None</span>
              <span>Severe</span>
            </div>
          </label>
        </section>

        {error && <p className="error">Error: {error}</p>}

        <button type="submit" disabled={loading}>
          {loading ? "Saving..." : "Log this run"}
        </button>
      </form>
    </div>
  );
}

export default LogRunPage;