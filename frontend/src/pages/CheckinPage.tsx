import { useState } from "react";
import { useNavigate } from "react-router-dom";

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

const ENERGY_WORDS = ["Running on empty", "Running on empty", "Running on empty", "A bit flat", "A bit flat", "Steady", "Steady", "Feeling good", "Feeling good", "Fired up", "Fired up"];
const SLEEP_WORDS = ["", "Restless", "Light", "Okay", "Solid", "Deep"];
const DISTANCE_CHIPS = [2, 3, 4, 5, 6, 8, 10];
const MINUTE_CHIPS = [20, 30, 45, 60, 90];
type Mood = "stressed" | "flat" | "good" | "restless" | "low";
type Intent = "easy" | "workout" | "long" | "explore";
// low on the left to good on the right, matching the energy scale above
const MOODS: { value: Mood; label: string; hint: string }[] = [
  { value: "low", label: "Low", hint: "Keep it gentle" },
  { value: "flat", label: "Flat", hint: "Low motivation" },
  { value: "restless", label: "Restless", hint: "Itching to go" },
  { value: "stressed", label: "Stressed", hint: "Need to clear my head" },
  { value: "good", label: "Good", hint: "Feeling like myself" },
];
const INTENTS: { value: Intent; label: string; hint: string }[] = [
  { value: "easy", label: "Easy", hint: "Recovery pace" },
  { value: "workout", label: "Workout", hint: "Speed or tempo" },
  { value: "long", label: "Long run", hint: "Go the distance" },
  { value: "explore", label: "Explore", hint: "Somewhere new" },
];
const RUN_TIMES: { value: "now" | "morning" | "midday" | "evening"; label: string; phrase: string; when: string }[] = [
  { value: "now", label: "Now", phrase: "", when: "Next hour" },
  { value: "morning", label: "Morning", phrase: " this morning", when: "Around 7 am" },
  { value: "midday", label: "Midday", phrase: " around midday", when: "Around noon" },
  { value: "evening", label: "Evening", phrase: " this evening", when: "Around 6 pm" },
];
const DRIVE_CHIPS: { label: string; value: string }[] = [
  { label: "Near home", value: "" },
  { label: "15 min", value: "15" },
  { label: "30 min", value: "30" },
  { label: "45 min", value: "45" },
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
  type Slot = "now" | "morning" | "midday" | "evening";
  const [runDay, setRunDay] = useState<"today" | "tomorrow">("today");
  const [runSlot, setRunSlot] = useState<Slot>("now");
  const runTime = runDay === "tomorrow" ? `tomorrow_${runSlot}` : runSlot;
  function timePassed(slot: Slot): boolean {
    const h = new Date().getHours();
    return (slot === "morning" && h >= 11) || (slot === "midday" && h >= 15) || (slot === "evening" && h >= 22);
  }
  function pickDay(d: "today" | "tomorrow") {
    setRunDay(d);
    if (d === "tomorrow" && runSlot === "now") setRunSlot("morning");
    if (d === "today" && timePassed(runSlot)) setRunSlot("now");
  }
  const [availableMinutes, setAvailableMinutes] = useState("");
  const [moodNote, setMoodNote] = useState("");
  const [mood, setMood] = useState<Mood | null>(null);
  const [runIntent, setRunIntent] = useState<Intent | null>(null);
  const [lengthMode, setLengthMode] = useState<"miles" | "minutes">("miles");
  const [showNote, setShowNote] = useState(false);
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
          run_time: runTime,
          available_minutes: !plannedDistance && availableMinutes ? parseFloat(availableMinutes) : null,
          mood_note: moodNote.trim() || null,
          mood,
          run_intent: runIntent,
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

  const hours = parseFloat(sleepHours);
  const hoursWord = Number.isNaN(hours)
    ? "Tap + or −"
    : hours >= 8 ? "A full night" : hours >= 7 ? "Solid night" : hours >= 6 ? "A bit short" : "Short night";
  function bumpSleep(delta: number) {
    const next = Number.isNaN(hours) ? 7 : Math.min(14, Math.max(0, hours + delta));
    setSleepHours(String(next));
  }
  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });

  // turn the answers into two plain sentences for the finish card
  const energyPhrase =
    energy <= 2 ? "Low energy" : energy <= 4 ? "A little flat" : energy <= 6 ? "Steady energy" : energy <= 8 ? "Good energy" : "Fired up";
  const sleepPhrase = Number.isNaN(hours)
    ? `${SLEEP_WORDS[sleepQuality].toLowerCase()} sleep`
    : `${hours}h of ${SLEEP_WORDS[sleepQuality].toLowerCase()} sleep`;
  const soreNames = soreParts.map((id) => MUSCLE_GROUPS.find((m) => m.id === id)?.label.toLowerCase() ?? id);
  const sorePhrase =
    soreNames.length === 0
      ? "nothing sore"
      : soreNames.length <= 2
        ? `a sore ${soreNames.join(" and ")}`
        : `${soreNames.length} sore spots`;
  const moodPhrase = mood ? { good: ", feeling good", stressed: ", a bit stressed", restless: ", restless", flat: ", feeling flat", low: ", feeling low" }[mood] : "";
  const feelSentence = `${energyPhrase}${moodPhrase}, ${sleepPhrase}, ${sorePhrase}.`;

  const extras: string[] = [];
  if (soreNames.length > 0) extras.push("goes easy on the sore spots");
  if (wantsScenic) extras.push("has a view");
  if (wantsAdventure) extras.push("is somewhere new");
  const surfaceWord = surfacePreference === "trail" ? " of trail" : surfacePreference === "road" ? " of road" : "";
  const intentWord = runIntent ? { easy: "easy ", workout: "workout ", long: "long ", explore: "" }[runIntent] : "";
  const what = plannedDistance
    ? `${plannedDistance} miles${surfaceWord}${runIntent === "easy" ? ", nice and flat" : runIntent === "workout" ? " with even footing" : ""}`
    : runIntent && !availableMinutes
      ? `a ${intentWord}${surfacePreference || ""} run`.replace("  ", " ").replace(" run", runIntent === "explore" ? " run somewhere new" : " run").replace(/^a easy/, "an easy")
    : availableMinutes
      ? `a ${availableMinutes}-minute ${surfacePreference || ""} run`.replace("  ", " ")
      : `a ${surfacePreference || ""} run`.replace("  ", " ");
  const whenPhrase = runDay === "tomorrow"
    ? ` tomorrow ${runSlot === "midday" ? "around midday" : runSlot}`
    : RUN_TIMES.find((t) => t.value === runSlot)?.phrase ?? "";
  const where = willingToDrive ? ` within a ${willingToDrive}-minute drive` : " close to home";
  const planSentence =
    `We'll look for ${what}${where}${whenPhrase}` +
    (extras.length ? ` that ${extras.length > 1 ? extras.slice(0, -1).join(", ") + " and " + extras[extras.length - 1] : extras[0]}` : "") +
    ".";

  return (
    <div className="app checkin-page">
      <header className="ci-intro">
        <span className="ci-eyebrow">Daily check-in · {today}</span>
        <h1>How's the body today?</h1>
        <p>Four quick questions. Pathos picks the route to match.</p>
      </header>

      <form onSubmit={handleSubmit}>
        <ol className="ci-steps">
          {/* 01 Energy */}
          <li className="ci-step">
            <span className="ci-marker">01</span>
            <section className="ci-card ci-energy-card" style={{ ["--e" as string]: energy / 10 } as React.CSSProperties}>
              <div className="ci-card-head">
                <h2><span className="ci-badge energy" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M13 2L4.5 13.5H11L10 22l8.5-11.5H12L13 2z" /></svg></span>Energy</h2>
                <span className="ci-readout">
                  <span className="ci-big">{energy}</span>
                  <span className="ci-word">{ENERGY_WORDS[energy]}</span>
                </span>
              </div>
              <div className="ci-energy" role="radiogroup" aria-label="Energy level from 0 to 10">
                {Array.from({ length: 11 }, (_, i) => (
                  <button
                    key={i}
                    type="button"
                    role="radio"
                    aria-checked={energy === i}
                    aria-label={`Energy ${i}`}
                    className={`ci-energy-seg ${i <= energy ? "on" : ""} ${energy === i ? "current" : ""}`}
                    style={{ height: `${28 + i * 4}px`, ["--i" as string]: i / 10 } as React.CSSProperties}
                    onClick={() => setEnergy(i)}
                  />
                ))}
              </div>
              <div className="ci-ends">
                <span>Drained</span>
                <span>Electric</span>
              </div>

              <div className="ci-mood">
                <span className="ci-field-label">And your head?</span>
                <div className="ci-mood-row" role="radiogroup" aria-label="Mood">
                  {MOODS.map((m) => (
                    <button
                      key={m.value}
                      type="button"
                      role="radio"
                      aria-checked={mood === m.value}
                      className={`ci-mood-opt mood-${m.value} ${mood === m.value ? "on" : ""}`}
                      onClick={() => setMood(mood === m.value ? null : m.value)}
                    >
                      <span className="ci-mood-dot" aria-hidden="true" />
                      <strong>{m.label}</strong>
                      <small>{m.hint}</small>
                    </button>
                  ))}
                </div>
              </div>
            </section>
          </li>

          {/* 02 Sleep */}
          <li className="ci-step">
            <span className="ci-marker">02</span>
            <section className="ci-card">
              <div className="ci-card-head">
                <h2><span className="ci-badge sleep" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z" /></svg></span>Sleep</h2>
              </div>
              <div className="ci-sleep">
                <div className="ci-sleep-panel">
                <span className="ci-panel-label">Hours</span>
                <div className="ci-stepper">
                  <button type="button" onClick={() => bumpSleep(-0.5)} aria-label="Less sleep">−</button>
                  <div className="ci-stepper-value">
                    <span className={`ci-big ${Number.isNaN(hours) ? "placeholder" : ""}`}>{Number.isNaN(hours) ? 7 : hours}</span>

                  </div>
                  <button type="button" onClick={() => bumpSleep(0.5)} aria-label="More sleep">+</button>
                </div>
                <span className="ci-word">{hoursWord}</span>
                </div>
                <div className="ci-sleep-panel">
                  <span className="ci-panel-label">Quality</span>
                  <div className="ci-moons" role="radiogroup" aria-label="Sleep quality from 1 to 5">
                    {Array.from({ length: 5 }, (_, i) => (
                      <button
                        key={i}
                        type="button"
                        role="radio"
                        aria-checked={sleepQuality === i + 1}
                        aria-label={`Sleep quality ${i + 1}`}
                        className={`ci-moon ${i < sleepQuality ? "on" : ""}`}
                        onClick={() => setSleepQuality(i + 1)}
                      >
                        <svg width="28" height="28" viewBox="0 0 24 24">
                          <path
                            d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"
                            fill={i < sleepQuality ? "currentColor" : "none"}
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinejoin="round"
                          />
                        </svg>
                      </button>
                    ))}
                  </div>
                  <span className="ci-word">{SLEEP_WORDS[sleepQuality]} sleep</span>
                </div>
              </div>
            </section>
          </li>

          {/* 03 Body */}
          <li className="ci-step">
            <span className="ci-marker">03</span>
            <section className="ci-card">
              <div className="ci-card-head">
                <h2><span className="ci-badge body" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="5" r="2" /><path d="M12 8v6M8 10l4 2 4-2M10 21l2-7 2 7" /></svg></span>Anything sore?</h2>
                <button
                  type="button"
                  className={`ci-chip ${soreParts.length === 0 ? "on" : ""}`}
                  onClick={() => setSoreParts([])}
                >
                  Feeling fresh
                </button>
              </div>
              <p className="ci-hint">Tap the muscles that are talking to you today.</p>
              <svg viewBox="0 -20 400 370" className="body-map-dual">
                <text x="130" y="10" textAnchor="middle" className="body-view-label">Front</text>
                <text x="310" y="10" textAnchor="middle" className="body-view-label">Back</text>
                <SilhouetteBody view="front" offsetX={30} />
                <SilhouetteBody view="back" offsetX={210} />
              </svg>
              {soreParts.length > 0 && (
                <div className="ci-sore-list">
                  {soreParts.map((id) => (
                    <button key={id} type="button" className="ci-chip on removable" onClick={() => toggleBodyPart(id)}>
                      {MUSCLE_GROUPS.find((p) => p.id === id)?.label} ✕
                    </button>
                  ))}
                </div>
              )}
            </section>
          </li>

          {/* 04 Today's run */}
          <li className="ci-step">
            <span className="ci-marker">04</span>
            <section className="ci-card">
              <div className="ci-card-head">
                <h2><span className="ci-badge run" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 16c2-.5 3.5-2 5.5-2s3 1.5 5 1.5S18 14 20 14M4 20h16" /><path d="M7 14V9l4-3 3 3h3" /></svg></span>Today's run</h2>
              </div>

              {/* group 1: the run itself */}
              <div className="ci-group">
                <span className="ci-group-label">The run</span>
                <div className="ci-intents" role="radiogroup" aria-label="What this run is for">
                  {INTENTS.map((t) => (
                    <button
                      key={t.value}
                      type="button"
                      role="radio"
                      aria-checked={runIntent === t.value}
                      className={`ci-intent ${runIntent === t.value ? "on" : ""}`}
                      onClick={() => {
                        const next = runIntent === t.value ? null : t.value;
                        setRunIntent(next);
                        setWantsAdventure(next === "explore");
                      }}
                    >
                      <strong>{t.label}</strong>
                      <small>{t.hint}</small>
                    </button>
                  ))}
                </div>

                <div className="ci-length">
                  <div className="ci-length-head">
                    <span className="ci-field-label">{lengthMode === "miles" ? "How far?" : "How long?"}</span>
                    <div className="ci-mini-switch" role="tablist" aria-label="Distance or time">
                      <button type="button" role="tab" aria-selected={lengthMode === "miles"}
                        className={lengthMode === "miles" ? "on" : ""}
                        onClick={() => { setLengthMode("miles"); setAvailableMinutes(""); }}>
                        Miles
                      </button>
                      <button type="button" role="tab" aria-selected={lengthMode === "minutes"}
                        className={lengthMode === "minutes" ? "on" : ""}
                        onClick={() => { setLengthMode("minutes"); setPlannedDistance(""); }}>
                        Minutes
                      </button>
                    </div>
                  </div>
                  <div className="ci-chips">
                    {lengthMode === "miles" ? (
                      <>
                        {DISTANCE_CHIPS.map((d) => (
                          <button
                            key={d}
                            type="button"
                            className={`ci-chip ${plannedDistance === String(d) ? "on" : ""}`}
                            onClick={() => setPlannedDistance(plannedDistance === String(d) ? "" : String(d))}
                          >
                            {d}
                          </button>
                        ))}
                        <input
                          type="number"
                          min="0"
                          step="0.5"
                          className="ci-chip-input"
                          placeholder="Other"
                          aria-label="Other distance in miles"
                          value={DISTANCE_CHIPS.map(String).includes(plannedDistance) ? "" : plannedDistance}
                          onChange={(e) => setPlannedDistance(e.target.value)}
                        />
                      </>
                    ) : (
                      <>
                        {MINUTE_CHIPS.map((m) => (
                          <button
                            key={m}
                            type="button"
                            className={`ci-chip ${availableMinutes === String(m) ? "on" : ""}`}
                            onClick={() => setAvailableMinutes(availableMinutes === String(m) ? "" : String(m))}
                          >
                            {m}
                          </button>
                        ))}
                        <input
                          type="number"
                          min="5"
                          step="5"
                          className="ci-chip-input"
                          placeholder="Other"
                          aria-label="Other time in minutes"
                          value={MINUTE_CHIPS.map(String).includes(availableMinutes) ? "" : availableMinutes}
                          onChange={(e) => setAvailableMinutes(e.target.value)}
                        />
                      </>
                    )}
                  </div>
                </div>
              </div>

              {/* group 2: logistics, as settings rows */}
              <div className="ci-group">
                <span className="ci-group-label">Details</span>
                <div className="ci-rows">
                  <div className="ci-row ci-row-stack">
                    <div className="ci-row-top">
                      <span className="ci-row-label">When</span>
                      <div className="ci-mini-switch" role="tablist" aria-label="Day">
                        {(["today", "tomorrow"] as const).map((d) => (
                          <button
                            key={d}
                            type="button"
                            role="tab"
                            aria-selected={runDay === d}
                            className={runDay === d ? "on" : ""}
                            onClick={() => pickDay(d)}
                          >
                            {d === "today" ? "Today" : "Tomorrow"}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="ci-times">
                      {RUN_TIMES.filter((t) => runDay === "today" || t.value !== "now").map((t) => {
                        const passed = runDay === "today" && timePassed(t.value);
                        return (
                          <button
                            key={t.value}
                            type="button"
                            disabled={passed}
                            className={`ci-time ${runSlot === t.value ? "on" : ""}`}
                            onClick={() => setRunSlot(t.value)}
                            title={passed ? "Already passed today" : undefined}
                          >
                            <strong>{t.label}</strong>
                            <small>{t.when}</small>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div className="ci-row">
                    <span className="ci-row-label">Drive</span>
                    <div className="ci-segmented compact">
                      {DRIVE_CHIPS.map((c) => (
                        <button
                          key={c.label}
                          type="button"
                          className={willingToDrive === c.value ? "on" : ""}
                          onClick={() => setWillingToDrive(c.value)}
                        >
                          {c.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="ci-row">
                    <span className="ci-row-label">Surface</span>
                    <div className="ci-segmented compact">
                      {([["", "Either"], ["road", "Road"], ["trail", "Trail"]] as const).map(([v, label]) => (
                        <button
                          key={label}
                          type="button"
                          className={surfacePreference === v ? "on" : ""}
                          onClick={() => setSurfacePreference(v)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <label className="ci-row ci-row-toggle">
                    <span className="ci-row-label">
                      Make it scenic
                      <small>Views over speed today</small>
                    </span>
                    <span className={`ci-switch ${wantsScenic ? "on" : ""}`}>
                      <input
                        type="checkbox"
                        checked={wantsScenic}
                        onChange={(e) => setWantsScenic(e.target.checked)}
                      />
                      <span aria-hidden="true" />
                    </span>
                  </label>
                </div>
              </div>

              {/* note: tucked away until wanted */}
              {showNote || moodNote ? (
                <label className="ci-note">
                  <span className="ci-field-label">Anything else on your mind?</span>
                  <textarea
                    rows={2}
                    maxLength={280}
                    value={moodNote}
                    onChange={(e) => setMoodNote(e.target.value)}
                    placeholder="Stressful day, want to clear my head..."
                    autoFocus={!moodNote}
                  />
                </label>
              ) : (
                <button type="button" className="ci-add-note" onClick={() => setShowNote(true)}>
                  + Add a note
                </button>
              )}
            </section>
          </li>

          {/* Finish line */}
          <li className="ci-step">
            <span className="ci-marker ci-marker-finish" aria-hidden="true">
              {/* checkered finish flag */}
              <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
                <defs>
                  <clipPath id="finishFlag">
                    <path d="M6 4c3-1.6 5.5 1.4 8.5 0S19 3.2 20 4v9c-1 -0.8-2.5-1.6-5.5 0S9 13.4 6 15z" />
                  </clipPath>
                </defs>
                <path d="M6 4c3-1.6 5.5 1.4 8.5 0S19 3.2 20 4v9c-1 -0.8-2.5-1.6-5.5 0S9 13.4 6 15z" fill="#fff" />
                <g clipPath="url(#finishFlag)" fill="#1D4ED8" opacity="0.85">
                  <rect x="6" y="1" width="3.5" height="3.6" />
                  <rect x="13" y="1" width="3.5" height="3.6" />
                  <rect x="9.5" y="4.6" width="3.5" height="3.6" />
                  <rect x="16.5" y="4.6" width="3.5" height="3.6" />
                  <rect x="6" y="8.2" width="3.5" height="3.6" />
                  <rect x="13" y="8.2" width="3.5" height="3.6" />
                  <rect x="9.5" y="11.8" width="3.5" height="3.6" />
                  <rect x="16.5" y="11.8" width="3.5" height="3.6" />
                </g>
                <path d="M6 3v18" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
              </svg>
            </span>
            <section className="ci-finish">
              <span className="ci-finish-label">Today's read</span>
              <p className="ci-finish-feel">{feelSentence}</p>
              <p className="ci-finish-plan">{planSentence}</p>
              {error && <p className="ci-finish-error">{error}</p>}
              <button type="submit" disabled={loading}>
                {loading ? "Finding routes..." : "Find my routes"}
                <span aria-hidden="true">→</span>
              </button>
            </section>
          </li>
        </ol>
      </form>
    </div>
  );
}

export default CheckinPage;