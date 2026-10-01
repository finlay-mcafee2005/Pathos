import { useState } from "react";
import { useNavigate } from "react-router-dom";
import ThemeToggle from "../components/ThemeToggle";

const MUSCLE_GROUPS = [
  // Front view
  { id: "chest", label: "Chest", view: "front", path: "M 70 92 Q 68 88 76 87 L 96 90 L 96 118 L 74 116 Q 66 112 70 92 Z M 130 92 Q 132 88 124 87 L 104 90 L 104 118 L 126 116 Q 134 112 130 92 Z" },
  { id: "abs", label: "Abs", view: "front", path: "M 80 122 L 120 122 L 117 168 Q 100 174 83 168 Z" },
  { id: "left_bicep", label: "Left bicep", view: "front", path: "M 60 90 Q 48 96 46 128 L 50 155 Q 57 158 61 150 L 63 118 Z" },
  { id: "right_bicep", label: "Right bicep", view: "front", path: "M 140 90 Q 152 96 154 128 L 150 155 Q 143 158 139 150 L 137 118 Z" },
  { id: "left_quad", label: "Left quad", view: "front", path: "M 76 178 Q 68 210 72 240 Q 73 252 78 258 L 92 258 Q 95 252 94 240 Q 95 210 94 178 Q 85 174 76 178 Z" },
  { id: "right_quad", label: "Right quad", view: "front", path: "M 124 178 Q 132 210 128 240 Q 127 252 122 258 L 108 258 Q 105 252 106 240 Q 105 210 106 178 Q 115 174 124 178 Z" },
  { id: "left_shin", label: "Left shin", view: "front", path: "M 78 264 Q 74 290 77 315 Q 78 325 83 330 L 89 330 Q 91 325 90 315 Q 91 290 89 264 Q 84 262 78 264 Z" },
  { id: "right_shin", label: "Right shin", view: "front", path: "M 122 264 Q 126 290 123 315 Q 122 325 117 330 L 111 330 Q 109 325 110 315 Q 109 290 111 264 Q 116 262 122 264 Z" },

  // Back view
  { id: "traps", label: "Traps", view: "back", path: "M 78 66 Q 100 58 122 66 Q 118 78 112 84 Q 100 80 88 84 Q 82 78 78 66 Z" },
  { id: "upper_back", label: "Upper back", view: "back", path: "M 76 88 Q 100 82 124 88 Q 128 120 122 148 Q 100 154 78 148 Q 72 120 76 88 Z" },
  { id: "lower_back", label: "Lower back", view: "back", path: "M 85 148 Q 100 144 115 148 Q 118 162 113 176 Q 100 180 87 176 Q 82 162 85 148 Z" },
  { id: "left_tricep", label: "Left tricep", view: "back", path: "M 60 90 Q 48 96 46 128 L 50 155 Q 57 158 61 150 L 63 118 Z" },
  { id: "right_tricep", label: "Right tricep", view: "back", path: "M 140 90 Q 152 96 154 128 L 150 155 Q 143 158 139 150 L 137 118 Z" },
  { id: "glutes", label: "Glutes", view: "back", path: "M 78 183 Q 100 176 122 183 Q 124 198 118 212 Q 100 218 82 212 Q 76 198 78 183 Z" },
  { id: "left_hamstring", label: "Left hamstring", view: "back", path: "M 79 216 Q 71 235 75 250 Q 76 255 82 258 L 94 258 Q 97 255 96 250 Q 97 235 96 216 Q 87 213 79 216 Z" },
  { id: "right_hamstring", label: "Right hamstring", view: "back", path: "M 121 216 Q 129 235 125 250 Q 124 255 118 258 L 106 258 Q 103 255 104 250 Q 103 235 104 216 Q 113 213 121 216 Z" },
  { id: "left_calf", label: "Left calf", view: "back", path: "M 76 264 Q 70 290 78 318 Q 80 325 85 328 L 91 328 Q 92 325 90 318 Q 91 290 90 264 Q 83 261 76 264 Z" },
  { id: "right_calf", label: "Right calf", view: "back", path: "M 124 264 Q 130 290 122 318 Q 120 325 115 328 L 109 328 Q 108 325 110 318 Q 109 290 110 264 Q 117 261 124 264 Z" },
];

function CheckinPage() {
  const navigate = useNavigate();
  const userId = localStorage.getItem("user_id");

  const [energy, setEnergy] = useState(5);
  const [sleepHours, setSleepHours] = useState("");
  const [sleepQuality, setSleepQuality] = useState(3);
  const [soreParts, setSoreParts] = useState<string[]>([]);
  const [plannedDistance, setPlannedDistance] = useState("");
  const [willingToDrive, setWillingToDrive] = useState("");
  const [wantsAdventure, setWantsAdventure] = useState(false);
  const [wantsScenic, setWantsScenic] = useState(false);
  const [surfacePreference, setSurfacePreference] = useState<"" | "trail" | "road">("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleBodyPart(id: string) {
    setSoreParts((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
    );
  }

  function SilhouetteBody({ view, offsetX }: { view: "front" | "back"; offsetX: number }) {
  return (
    <g transform={`translate(${offsetX}, 15)`}>
      <ellipse cx="100" cy="35" rx="19" ry="23" className="body-shape" />
      <path
        d="M 70 58 Q 68 55 74 55 L 126 55 Q 132 55 130 58 L 136 130 Q 137 148 122 152 L 78 152 Q 63 148 64 130 Z"
        className="body-shape"
      />
      <path d="M 68 58 Q 50 62 46 122 L 50 158 Q 57 161 62 153 L 66 128 Q 68 88 78 60 Z" className="body-shape" />
      <path d="M 132 58 Q 150 62 154 122 L 150 158 Q 143 161 138 153 L 134 128 Q 132 88 122 60 Z" className="body-shape" />
      <path d="M 78 152 L 122 152 L 127 182 Q 100 191 73 182 Z" className="body-shape" />
      <path d="M 79 184 Q 73 220 77 260 L 82 328 Q 82 335 89 335 Q 96 335 96 328 L 100 260 Q 101 220 97 187 Z" className="body-shape" />
      <path d="M 121 184 Q 127 220 123 260 L 118 328 Q 118 335 111 335 Q 104 335 104 328 L 100 260 Q 99 220 103 187 Z" className="body-shape" />
      <ellipse cx="89" cy="339" rx="12" ry="6" className="body-shape" />
      <ellipse cx="111" cy="339" rx="12" ry="6" className="body-shape" />

      {MUSCLE_GROUPS.filter((m) => m.view === view).map((m) => (
        <path
          key={m.id}
          d={m.path}
          className={`muscle-region ${soreParts.includes(m.id) ? "active" : ""}`}
          onClick={() => toggleBodyPart(m.id)}
        >
          <title>{m.label}</title>
        </path>
      ))}
    </g>
  );
}

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!userId) {
      setError("No user found. Please sign up again.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("http://127.0.0.1:8000/checkins", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          energy_score: energy,
          sleep_hours: sleepHours ? parseFloat(sleepHours) : null,
          sleep_quality: sleepQuality,
          sore_body_parts: soreParts,
          planned_distance_miles: plannedDistance ? parseFloat(plannedDistance) : null,
          willing_to_drive_miles: willingToDrive ? (parseFloat(willingToDrive) / 60) * 30 : null,
          wants_adventure: wantsAdventure,
          wants_scenic: wantsScenic,
          surface_preference: surfacePreference || null,
        }),
      });
      if (!response.ok) throw new Error(`Server responded with ${response.status}`);
      navigate("/recommendations");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <ThemeToggle />
      <header className="header">
        <h1>Daily check-in</h1>
      </header>

      <form className="form" onSubmit={handleSubmit}>
        <section className="form-section">
          <h2>
            <span className="form-section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" fill="currentColor" />
              </svg>
            </span>
            Mental energy
          </h2>
          <label>
            <div className="scale-header">
              <span>Energy level</span>
              <span className="slider-value-badge">{energy}</span>
            </div>
            <div className="energy-bars">
              {Array.from({ length: 10 }, (_, i) => (
                <div key={i} className={`energy-bar ${i < energy ? "filled" : ""}`} />
              ))}
            </div>
            <div className="scale-endpoints">
              <span>Low</span>
              <span>High</span>
            </div>
            <input
              type="range"
              min="0"
              max="10"
              value={energy}
              onChange={(e) => setEnergy(parseInt(e.target.value))}
            />
          </label>
        </section>

        <section className="form-section">
          <h2>
            <span className="form-section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <rect x="2" y="10" width="20" height="8" rx="2" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
                <path d="M4 10V7a2 2 0 012-2h12a2 2 0 012 2v3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            Sleep last night
          </h2>
          <label>
            Hours of sleep
            <input
              type="number"
              step="0.5"
              min="0"
              value={sleepHours}
              onChange={(e) => setSleepHours(e.target.value)}
            />
          </label>
          <label>
            <div className="scale-header">
              <span>Sleep quality</span>
              <span className="slider-value-badge">{sleepQuality}/5</span>
            </div>
            <div className="quality-moons">
              {Array.from({ length: 5 }, (_, i) => (
                <svg
                  key={i}
                  width="30"
                  height="30"
                  viewBox="0 0 24 24"
                  className={`quality-moon ${i < sleepQuality ? "filled" : ""}`}
                >
                  <path
                    d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"
                    fill={i < sleepQuality ? "currentColor" : "none"}
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinejoin="round"
                  />
                </svg>
              ))}
            </div>
            <div className="scale-endpoints">
              <span>Poor</span>
              <span>Great</span>
            </div>
            <input
              type="range"
              min="1"
              max="5"
              value={sleepQuality}
              onChange={(e) => setSleepQuality(parseInt(e.target.value))}
            />
          </label>
        </section>

        <section className="form-section">
          <h2>
            <span className="form-section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="2" />
                <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </span>
            Where are you sore?
          </h2>
          <p className="hint">Tap any muscle areas that feel sore today.</p>
          <svg viewBox="0 -20 400 370" className="body-map-dual">
  <text x="130" y="10" textAnchor="middle" className="body-view-label">Front</text>
  <text x="310" y="10" textAnchor="middle" className="body-view-label">Back</text>
  <SilhouetteBody view="front" offsetX={30} />
  <SilhouetteBody view="back" offsetX={210} />
</svg>
          {soreParts.length > 0 && (
            <p className="selected-parts">
              Selected: {soreParts.map((id) => MUSCLE_GROUPS.find((p) => p.id === id)?.label).join(", ")}
            </p>
          )}
        </section>

        <section className="form-section">
          <h2>
            <span className="form-section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M13 4l-3 8h4l-2 8 7-11h-4l2-5z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" fill="none" />
                <circle cx="6" cy="18" r="2" stroke="currentColor" strokeWidth="2" />
              </svg>
            </span>
            Today's run
          </h2>
          <label>
            How many miles are you thinking of running?
            <input
              type="number"
              min="0"
              value={plannedDistance}
              onChange={(e) => setPlannedDistance(e.target.value)}
            />
          </label>
          <label>
            How long are you willing to drive to a trailhead? (minutes, optional)
            <input
              type="number"
              min="0"
              value={willingToDrive}
              onChange={(e) => setWillingToDrive(e.target.value)}
              placeholder="Leave blank for routes near home"
            />
          </label>
          <label className="checkbox-row">
            <span>Want to try something new today?</span>
            <input
              type="checkbox"
              checked={wantsAdventure}
              onChange={(e) => setWantsAdventure(e.target.checked)}
            />
          </label>
          <label className="checkbox-row">
            <span>Prefer something scenic today?</span>
            <input
              type="checkbox"
              checked={wantsScenic}
              onChange={(e) => setWantsScenic(e.target.checked)}
            />
          </label>
          <label>
            Road or trail today?
            <select
              value={surfacePreference}
              onChange={(e) => setSurfacePreference(e.target.value as "" | "trail" | "road")}
            >
              <option value="">No preference</option>
              <option value="road">Road</option>
              <option value="trail">Trail</option>
            </select>
          </label>
        </section>

        {error && <p className="error">Error: {error}</p>}

        <button type="submit" disabled={loading}>
          {loading ? "Submitting..." : "Get my recommendations"}
        </button>
      </form>
    </div>
  );
}

export default CheckinPage;