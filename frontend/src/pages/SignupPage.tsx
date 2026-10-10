import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import BackgroundSlideshow from "../components/BackgroundSlideshow";
import ThemeToggle from "../components/ThemeToggle";
import { API_URL } from "../utils/format";

type Injury = {
  body_part: string;
  severity: string;
  reported_at: string;
};

const STEPS = [
  { short: "You", title: "Let's get you set up.", sub: "Your login for Pathos." },
  { short: "Home base", title: "Where do you run from?", sub: "We find routes that start near here." },
  { short: "Your running", title: "Tell us how you run.", sub: "So the first recommendations already fit." },
  { short: "Body check", title: "Anything hurting lately?", sub: "Pathos steers you away from surfaces that aggravate it." },
];

const FITNESS_OPTIONS = [
  { value: "beginner", icon: "🌱", title: "Just starting", sub: "Building up to regular runs" },
  { value: "intermediate", icon: "🏃", title: "Regular runner", sub: "A few runs most weeks" },
  { value: "advanced", icon: "⚡", title: "Seasoned", sub: "High mileage, hills, races" },
];

const GOAL_OPTIONS = [
  { value: "race_training", icon: "🏁", title: "Train for a race", sub: "Hit distances, build fitness" },
  { value: "general_fitness", icon: "☀️", title: "Stay in shape", sub: "Consistent, enjoyable runs" },
  { value: "weight_loss", icon: "🔥", title: "Get in shape", sub: "Build the habit, steady progress" },
];

// value = the middle of each range, in miles per week
const MILEAGE_CHIPS = [
  { label: "0–10", value: "5" },
  { label: "10–20", value: "15" },
  { label: "20–30", value: "25" },
  { label: "30–40", value: "35" },
  { label: "40–50", value: "45" },
  { label: "50–60", value: "55" },
];

function passwordStrength(pw: string): { score: number; label: string } {
  let score = 0;
  if (pw.length >= 8) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  const labels = ["Too short", "Warming up", "Getting there", "Strong", "Race ready"];
  return { score, label: pw ? labels[score] : "" };
}

function SignupPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkingArea, setCheckingArea] = useState(false);
  const [areaLabel, setAreaLabel] = useState<string | null>(null);   // confirmed place
  const [checkedAddress, setCheckedAddress] = useState("");

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [phoneNumber, setPhoneNumber] = useState("");
  const [dateOfBirth, setDateOfBirth] = useState("");
  const [address, setAddress] = useState("");
  const [fitnessLevel, setFitnessLevel] = useState("beginner");
  const [goal, setGoal] = useState("general_fitness");
  const [weeklyMileage, setWeeklyMileage] = useState("");
  const [mileageOther, setMileageOther] = useState(false);
  const [paceMin, setPaceMin] = useState("");
  const [paceSec, setPaceSec] = useState("");
  // easy pace in minutes per mile, or null if blank / out of range (4:00-20:00)
  const paceValue = (() => {
    if (!paceMin) return null;
    const v = parseInt(paceMin, 10) + (parseInt(paceSec || "0", 10) || 0) / 60;
    return v >= 4 && v <= 20 ? Math.round(v * 100) / 100 : null;
  })();
  const paceInvalid = paceMin !== "" && paceValue === null;
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

  function addInjury() {
    setInjuries([...injuries, { body_part: "", severity: "mild", reported_at: "" }]);
  }

  function removeInjury(index: number) {
    setInjuries(injuries.filter((_, i) => i !== index));
  }

  // check the current step before moving on
  function stepError(s: number): string | null {
    if (s === 0) {
      if (!fullName.trim()) return "What should we call you?";
      if (!/^\S+@\S+\.\S+$/.test(email)) return "That email doesn't look quite right.";
      if (password.length < 6) return "Use at least 6 characters for your password.";
    }
    if (s === 1 && !address.trim()) return "Add an address or neighborhood so we can find routes near you.";
    return null;
  }

  async function next() {
    const problem = stepError(step);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    // step 2: make sure the location is a real place Pathos covers before moving on
    if (step === 1 && address.trim() !== checkedAddress) {
      setCheckingArea(true);
      try {
        const res = await fetch(API_URL + "/check-area", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ address: address.trim() }),
        });
        const body = await res.json().catch(() => null);
        if (!res.ok) {
          setAreaLabel(null);
          setError(body?.detail ?? "Couldn't check that location.");
          return;
        }
        setAreaLabel(body.label);
        setCheckedAddress(address.trim());
      } catch {
        setError("Couldn't reach Pathos to check that location. Is the backend running?");
        return;
      } finally {
        setCheckingArea(false);
      }
    }
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  }

  function back() {
    setError(null);
    setStep((s) => Math.max(s - 1, 0));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (step < STEPS.length - 1) {
      next();
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const response = await fetch(API_URL + "/signup", {
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
          usual_pace_min_mile: paceValue,
          injuries: hasInjury ? injuries.filter((i) => i.body_part) : [],
          club_join_code: clubCode || null,
        }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        const detail: string = body?.detail || `Server responded with ${response.status}`;
        // send them back to the step that needs fixing
        if (/route|address|location/i.test(detail)) setStep(1);
        else if (/club/i.test(detail)) setStep(2);
        else if (/email/i.test(detail)) setStep(0);
        throw new Error(detail);
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

  const strength = passwordStrength(password);
  const firstName = fullName.trim().split(" ")[0];
  const isLast = step === STEPS.length - 1;

  return (
    <div className="split-auth-page signup-page">
      <ThemeToggle />
      <div className="split-auth-panel">
        <div className="split-auth-content su-content">
          <Link to="/login" className="auth-brand su-brand">
            <img src="/pathos-logo.png" alt="Pathos logo" width={52} height={52} />
            <span className="auth-brand-name">Pathos</span>
          </Link>

          {/* progress: four checkpoints on a line */}
          <div className="su-progress" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
            <div className="su-progress-track">
              <span className="su-progress-fill" style={{ width: `${(step / (STEPS.length - 1)) * 100}%` }} />
            </div>
            {STEPS.map((st, i) => (
              <button
                key={st.short}
                type="button"
                className={`su-checkpoint ${i < step ? "done" : ""} ${i === step ? "current" : ""}`}
                style={{ left: `${(i / (STEPS.length - 1)) * 100}%` }}
                onClick={() => i < step && setStep(i)}
                disabled={i > step}
                aria-label={st.short}
              >
                {i < step ? "✓" : i + 1}
              </button>
            ))}
          </div>

          <div key={step} className="su-step">
            <span className="auth-eyebrow">Mile {step + 1} of {STEPS.length} · {STEPS[step].short}</span>
            <h1>
              {step === 2 && firstName ? `Nice to meet you, ${firstName}.` : STEPS[step].title}
            </h1>
            <p className="auth-sub">{step === 2 && firstName ? STEPS[2].title + " " + STEPS[2].sub : STEPS[step].sub}</p>

            <form className="form" onSubmit={handleSubmit} noValidate>
              {step === 0 && (
                <section className="form-section">
                  <label>
                    Full name
                    <input value={fullName} onChange={(e) => setFullName(e.target.value)} autoFocus autoComplete="name" />
                  </label>
                  <label>
                    Email
                    <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
                  </label>
                  <label>
                    Password
                    <span className="su-password">
                      <input
                        type={showPassword ? "text" : "password"}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        autoComplete="new-password"
                      />
                      <button type="button" className="su-show" onClick={() => setShowPassword(!showPassword)}>
                        {showPassword ? "Hide" : "Show"}
                      </button>
                    </span>
                  </label>
                  {password && (
                    <div className="su-strength">
                      <span className="su-strength-bars" aria-hidden="true">
                        {[0, 1, 2, 3].map((i) => (
                          <i key={i} className={i < strength.score ? "on" : ""} />
                        ))}
                      </span>
                      <span>{strength.label}</span>
                    </div>
                  )}
                </section>
              )}

              {step === 1 && (
                <section className="form-section">
                  <label>
                    Home address or neighborhood
                    <span className="su-address">
                      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M12 21s-7-6.5-7-11.5A7 7 0 0112 2a7 7 0 017 7.5C19 14.5 12 21 12 21z" />
                        <circle cx="12" cy="9.5" r="2.5" />
                      </svg>
                      <input
                        value={address}
                        onChange={(e) => {
                          setAddress(e.target.value);
                          setAreaLabel(null);
                        }}
                        placeholder="e.g. Eagle Rock, Los Angeles"
                        autoFocus
                        autoComplete="street-address"
                      />
                    </span>
                  </label>
                  {areaLabel && address.trim() === checkedAddress ? (
                    <p className="su-note su-area-ok">✓ Found {areaLabel}. Routes nearby.</p>
                  ) : (
                    <p className="su-note">
                      Pathos currently covers northeast LA, Glendale, Burbank, Pasadena and the nearby foothills.
                    </p>
                  )}
                  <details className="su-optional">
                    <summary>Optional details</summary>
                    <label>
                      Phone number
                      <input value={phoneNumber} onChange={(e) => setPhoneNumber(e.target.value)} autoComplete="tel" />
                    </label>
                    <label>
                      Date of birth
                      <input type="date" value={dateOfBirth} onChange={(e) => setDateOfBirth(e.target.value)} />
                    </label>
                  </details>
                </section>
              )}

              {step === 2 && (
                <section className="form-section su-choices">
                  <span className="su-label">Where are you at?</span>
                  <div className="su-options">
                    {FITNESS_OPTIONS.map((o) => (
                      <button
                        key={o.value}
                        type="button"
                        className={`su-option ${fitnessLevel === o.value ? "on" : ""}`}
                        aria-pressed={fitnessLevel === o.value}
                        onClick={() => setFitnessLevel(o.value)}
                      >
                        <span className="su-option-icon">{o.icon}</span>
                        <strong>{o.title}</strong>
                        <small>{o.sub}</small>
                      </button>
                    ))}
                  </div>

                  <span className="su-label">What's the goal?</span>
                  <div className="su-options">
                    {GOAL_OPTIONS.map((o) => (
                      <button
                        key={o.value}
                        type="button"
                        className={`su-option ${goal === o.value ? "on" : ""}`}
                        aria-pressed={goal === o.value}
                        onClick={() => setGoal(o.value)}
                      >
                        <span className="su-option-icon">{o.icon}</span>
                        <strong>{o.title}</strong>
                        <small>{o.sub}</small>
                      </button>
                    ))}
                  </div>

                  <span className="su-label">Miles in a typical week</span>
                  <div className="ci-chips">
                    {MILEAGE_CHIPS.map((c) => (
                      <button
                        key={c.label}
                        type="button"
                        className={`ci-chip ${!mileageOther && weeklyMileage === c.value ? "on" : ""}`}
                        onClick={() => {
                          setMileageOther(false);
                          setWeeklyMileage(!mileageOther && weeklyMileage === c.value ? "" : c.value);
                        }}
                      >
                        {c.label}
                      </button>
                    ))}
                    <button
                      type="button"
                      className={`ci-chip ${mileageOther ? "on" : ""}`}
                      onClick={() => {
                        setMileageOther(!mileageOther);
                        setWeeklyMileage("");
                      }}
                    >
                      Other
                    </button>
                  </div>
                  {mileageOther && (
                    <span className="su-pace-input su-miles-other">
                      <input
                        inputMode="decimal"
                        maxLength={5}
                        autoFocus
                        value={weeklyMileage}
                        onChange={(e) => setWeeklyMileage(e.target.value.replace(/[^\d.]/g, ""))}
                        placeholder="70"
                        aria-label="Miles per week"
                      />
                      <span className="su-pace-unit">mi / week</span>
                    </span>
                  )}

                  <div className="su-pace">
                    <span className="su-label">
                      Easy-run pace <span className="su-optional-tag">optional</span>
                    </span>
                    <div className="su-pace-row">
                      <span className="su-pace-input">
                        <input
                          inputMode="numeric"
                          maxLength={2}
                          value={paceMin}
                          onChange={(e) => setPaceMin(e.target.value.replace(/\D/g, ""))}
                          placeholder="9"
                          aria-label="Pace minutes"
                        />
                        <span className="su-pace-colon">:</span>
                        <input
                          inputMode="numeric"
                          maxLength={2}
                          value={paceSec}
                          onChange={(e) => {
                            const v = e.target.value.replace(/\D/g, "");
                            setPaceSec(v && parseInt(v, 10) > 59 ? "59" : v);
                          }}
                          placeholder="30"
                          aria-label="Pace seconds"
                        />
                        <span className="su-pace-unit">/mi</span>
                      </span>
                      <span className="su-pace-hint">
                        {paceInvalid
                          ? "Enter a pace between 4:00 and 20:00 per mile."
                          : "Your comfortable, everyday pace, not race pace. Used for time estimates until you log runs."}
                      </span>
                    </div>
                  </div>

                  <label className="su-club">
                    Club join code <span className="su-optional-tag">optional</span>
                    <input value={clubCode} onChange={(e) => setClubCode(e.target.value.toUpperCase())} placeholder="e.g. PASADENA1" />
                  </label>
                </section>
              )}

              {step === 3 && (
                <section className="form-section su-choices">
                  <div className="su-yesno">
                    <button
                      type="button"
                      className={`su-option ${!hasInjury ? "on" : ""}`}
                      aria-pressed={!hasInjury}
                      onClick={() => setHasInjury(false)}
                    >
                      <span className="su-option-icon">💪</span>
                      <strong>All good</strong>
                      <small>No current injuries</small>
                    </button>
                    <button
                      type="button"
                      className={`su-option ${hasInjury ? "on" : ""}`}
                      aria-pressed={hasInjury}
                      onClick={() => setHasInjury(true)}
                    >
                      <span className="su-option-icon">🩹</span>
                      <strong>Something's up</strong>
                      <small>A current or recent injury</small>
                    </button>
                  </div>

                  {hasInjury && (
                    <div className="su-injuries">
                      {injuries.map((injury, i) => (
                        <div className="su-injury" key={i}>
                          <div className="su-injury-head">
                            <span className="su-label">Injury {injuries.length > 1 ? i + 1 : ""}</span>
                            {injuries.length > 1 && (
                              <button type="button" className="su-remove" onClick={() => removeInjury(i)}>
                                Remove
                              </button>
                            )}
                          </div>
                          <label>
                            Where?
                            <input
                              value={injury.body_part}
                              onChange={(e) => updateInjury(i, "body_part", e.target.value)}
                              placeholder="e.g. left knee"
                            />
                          </label>
                          <div className="ci-segmented su-severity">
                            {["mild", "moderate", "severe"].map((sev) => (
                              <button
                                key={sev}
                                type="button"
                                className={injury.severity === sev ? "on" : ""}
                                onClick={() => updateInjury(i, "severity", sev)}
                              >
                                {sev.charAt(0).toUpperCase() + sev.slice(1)}
                              </button>
                            ))}
                          </div>
                          <label>
                            When did it start?
                            <input
                              type="date"
                              value={injury.reported_at}
                              onChange={(e) => updateInjury(i, "reported_at", e.target.value)}
                            />
                          </label>
                        </div>
                      ))}
                      <button type="button" className="su-add" onClick={addInjury}>
                        + Add another
                      </button>
                    </div>
                  )}
                </section>
              )}

              {error && <p className="su-error">{error}</p>}

              <div className="su-nav">
                {step > 0 && (
                  <button type="button" className="su-back" onClick={back}>
                    ← Back
                  </button>
                )}
                <button type="submit" className="su-next" disabled={loading || checkingArea}>
                  {loading ? "Creating your account..." : checkingArea ? "Checking location..." : isLast ? "Start running →" : "Continue →"}
                </button>
              </div>
            </form>

            <p className="hint su-login">
              Already have an account? <Link to="/login">Log in</Link>
            </p>
          </div>
        </div>
      </div>

      <div className="split-auth-image">
        <BackgroundSlideshow />
        <div className="auth-photo-caption">
          <span className="auth-photo-pill">Los Angeles · Glendale · Pasadena</span>
          <h2>Routes that fit how you feel.</h2>
          <p>A few quick questions now, and your first recommendations are already tuned to you.</p>
        </div>
      </div>
    </div>
  );
}

export default SignupPage;
