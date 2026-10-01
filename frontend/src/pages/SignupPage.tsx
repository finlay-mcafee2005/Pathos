import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";

type Injury = {
  body_part: string;
  severity: string;
  reported_at: string;
};

function SignupPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [dateOfBirth, setDateOfBirth] = useState("");
  const [address, setAddress] = useState("");
  const [fitnessLevel, setFitnessLevel] = useState("beginner");
  const [goal, setGoal] = useState("general_fitness");
  const [weeklyMileage, setWeeklyMileage] = useState("");
  const [clubCode, setClubCode] = useState("");

  const [hasInjury, setHasInjury] = useState(false);
  const [injuries, setInjuries] = useState<Injury[]>([
    { body_part: "", severity: "mild", reported_at: "" },
  ]);

  function updateInjury(index: number, field: keyof Injury, value: string) {
    const updated = [...injuries];
    updated[index] = { ...updated[index], [field]: value };
    setInjuries(updated);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!fullName || !email || !password || !address) {
      setError("Please fill in all required fields.");
      return;
    }

    setLoading(true);
    try {
      const response = await fetch("http://127.0.0.1:8000/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: fullName,
          email,
          password,
          phone_number: phoneNumber || null,
          date_of_birth: dateOfBirth || null,
          address,
          fitness_level: fitnessLevel,
          goal,
          weekly_mileage_avg: parseFloat(weeklyMileage) || 0,
          injuries: hasInjury ? injuries.filter((i) => i.body_part) : [],
          club_join_code: clubCode || null,
        }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `Server responded with ${response.status}`);
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
    <div className="app">
      <header className="header">
        <h1>Create your account</h1>
      </header>

      <form className="form" onSubmit={handleSubmit}>
        <section className="form-section">
          <h2>
            <span className="form-section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="2" />
                <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </span>
            Basic info
          </h2>
          <label>
            Full name
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} required />
          </label>
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
          <label>
            Phone number (optional)
            <input value={phoneNumber} onChange={(e) => setPhoneNumber(e.target.value)} />
          </label>
          <label>
            Date of birth (optional)
            <input type="date" value={dateOfBirth} onChange={(e) => setDateOfBirth(e.target.value)} />
          </label>
          <label>
            Address
            <input
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="City, State or full address"
              required
            />
          </label>
        </section>

        <section className="form-section">
          <h2>
            <span className="form-section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M13 4l-3 8h4l-2 8 7-11h-4l2-5z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" fill="none" />
                <circle cx="6" cy="18" r="2" stroke="currentColor" strokeWidth="2" />
              </svg>
            </span>
            Running profile
          </h2>
          <label>
            Fitness level
            <select value={fitnessLevel} onChange={(e) => setFitnessLevel(e.target.value)}>
              <option value="beginner">Beginner</option>
              <option value="intermediate">Intermediate</option>
              <option value="advanced">Advanced</option>
            </select>
          </label>
          <label>
            Goal
            <select value={goal} onChange={(e) => setGoal(e.target.value)}>
              <option value="race_training">Training for a race</option>
              <option value="general_fitness">Staying in shape</option>
              <option value="weight_loss">Getting in shape / weight loss</option>
            </select>
          </label>
          <label>
            Typical weekly mileage
            <input
              type="number"
              min="0"
              value={weeklyMileage}
              onChange={(e) => setWeeklyMileage(e.target.value)}
            />
          </label>
          <label>
            Club join code (optional)
            <input
              value={clubCode}
              onChange={(e) => setClubCode(e.target.value)}
              placeholder="e.g. PASADENA1"
            />
          </label>
        </section>

        <section className="form-section">
          <h2>
            <span className="form-section-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <path d="M20 4h-3V2h-2v2h-6V2H7v2H4a2 2 0 00-2 2v14a2 2 0 002 2h16a2 2 0 002-2V6a2 2 0 00-2-2z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
                <path d="M9 12h6M12 9v6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </span>
            Injury history
          </h2>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={hasInjury}
              onChange={(e) => setHasInjury(e.target.checked)}
            />
            Do you have any current or recent injuries?
          </label>

          {hasInjury &&
            injuries.map((injury, i) => (
              <div className="injury-row" key={i}>
                <label>
                  Body part
                  <input
                    value={injury.body_part}
                    onChange={(e) => updateInjury(i, "body_part", e.target.value)}
                    placeholder="e.g. left knee"
                  />
                </label>
                <label>
                  Severity
                  <select
                    value={injury.severity}
                    onChange={(e) => updateInjury(i, "severity", e.target.value)}
                  >
                    <option value="mild">Mild</option>
                    <option value="moderate">Moderate</option>
                    <option value="severe">Severe</option>
                  </select>
                </label>
                <label>
                  Date reported
                  <input
                    type="date"
                    value={injury.reported_at}
                    onChange={(e) => updateInjury(i, "reported_at", e.target.value)}
                  />
                </label>
              </div>
            ))}
        </section>

        {error && <p className="error">Error: {error}</p>}

        <button type="submit" disabled={loading}>
          {loading ? "Creating account..." : "Sign up"}
        </button>

        <p className="hint">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </form>
    </div>
  );
}

export default SignupPage;
