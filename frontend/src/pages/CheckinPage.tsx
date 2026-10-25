import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import BodyMap from "../components/BodyMap";
import { API_URL } from "../utils/format";

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
  { id: "left_shoulder", label: "Left shoulder", view: "front", path: "" },
  { id: "right_shoulder", label: "Right shoulder", view: "front", path: "" },
  { id: "left_forearm", label: "Left forearm", view: "front", path: "" },
  { id: "right_forearm", label: "Right forearm", view: "front", path: "" },
  { id: "obliques", label: "Obliques", view: "front", path: "" },
  { id: "left_adductor", label: "Left inner thigh", view: "front", path: "" },
  { id: "right_adductor", label: "Right inner thigh", view: "front", path: "" },
  { id: "left_hip", label: "Left hip", view: "back", path: "" },
  { id: "right_hip", label: "Right hip", view: "back", path: "" },
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
  { value: "workout", label: "Workout", hint: "Tempo or intervals" },
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
  const [hillsPref, setHillsPref] = useState<"" | "avoid" | "want">("");
  const [quietStreets, setQuietStreets] = useState(false);
  const [shapePref, setShapePref] = useState<"" | "loop" | "out_and_back">("");

  // who you're running with today: just you, or one of your Run together groups
  const [searchParams] = useSearchParams();
  const [myGroups, setMyGroups] = useState<{ id: string; name: string }[]>([]);
  const [runWith, setRunWith] = useState<string>(searchParams.get("group") ?? "");
  useEffect(() => {
    if (!userId) return;
    fetch(`${API_URL}/run-groups/mine/${userId}`)
      .then((r) => (r.ok ? r.json() : []))
      .then((gs: { id: string; name: string }[]) => {
        setMyGroups(gs);
        setRunWith((cur) => (cur && gs.some((g) => g.id === cur) ? cur : ""));
      })
      .catch(() => {});
  }, [userId]);
  const runWithGroup = myGroups.find((g) => g.id === runWith) ?? null;

  // "Same as yesterday": the last check-in from an earlier day, if any
  type LastCheckin = {
    days_ago: number; energy_score: number; sleep_hours: number | null; sleep_quality: number | null;
    sore_body_parts: string[]; mood: Mood | null; run_intent: Intent | null;
    planned_distance_miles: number | null; available_minutes: number | null;
    willing_to_drive_miles: number | null; surface_preference: "trail" | "road" | null;
    wants_scenic: boolean; hills_pref: "avoid" | "want" | null; quiet_streets?: boolean;
    shape_pref?: "loop" | "out_and_back" | null;
  };
  const [last, setLast] = useState<LastCheckin | null>(null);
  const [copied, setCopied] = useState(false);
  // what the form held before "Same as yesterday", so it can be undone
  const [beforeCopy, setBeforeCopy] = useState<null | {
    energy: number; sleepHours: string; sleepQuality: number; soreParts: string[];
    mood: Mood | null; runIntent: Intent | null; lengthMode: "miles" | "minutes";
    plannedDistance: string; availableMinutes: string; willingToDrive: string;
    surfacePreference: "" | "trail" | "road"; wantsScenic: boolean; hillsPref: "" | "avoid" | "want"; quietStreets: boolean;
    shapePref: "" | "loop" | "out_and_back";
  }>(null);

  function undoCopy() {
    if (!beforeCopy) return;
    const b = beforeCopy;
    setEnergy(b.energy);
    setSleepHours(b.sleepHours);
    setSleepQuality(b.sleepQuality);
    setSoreParts(b.soreParts);
    setMood(b.mood);
    setRunIntent(b.runIntent);
    setLengthMode(b.lengthMode);
    setPlannedDistance(b.plannedDistance);
    setAvailableMinutes(b.availableMinutes);
    setWillingToDrive(b.willingToDrive);
    setSurfacePreference(b.surfacePreference);
    setWantsScenic(b.wantsScenic);
    setHillsPref(b.hillsPref);
    setQuietStreets(b.quietStreets);
    setShapePref(b.shapePref);
    setBeforeCopy(null);
    setCopied(false);
  }
  useEffect(() => {
    if (!userId) return;
    fetch(`${API_URL}/checkins/${userId}/last`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setLast(d))
      .catch(() => {});
  }, [userId]);

  function copyLast() {
    if (!last) return;
    setBeforeCopy({
      energy, sleepHours, sleepQuality, soreParts, mood, runIntent, lengthMode,
      plannedDistance, availableMinutes, willingToDrive, surfacePreference, wantsScenic, hillsPref, quietStreets, shapePref,
    });
    setEnergy(last.energy_score);
    setSleepHours(last.sleep_hours != null ? String(last.sleep_hours) : "");
    if (last.sleep_quality != null) setSleepQuality(last.sleep_quality);
    setSoreParts(last.sore_body_parts);
    setMood(last.mood);
    setRunIntent(last.run_intent);
    if (last.planned_distance_miles) {
      setLengthMode("miles");
      setPlannedDistance(String(last.planned_distance_miles));
      setAvailableMinutes("");
    } else if (last.available_minutes) {
      setLengthMode("minutes");
      setAvailableMinutes(String(last.available_minutes));
      setPlannedDistance("");
    } else {
      setPlannedDistance("");
      setAvailableMinutes("");
    }
    // drive limit was stored as miles at ~20 mph; snap back to the 15/30/45 min chips
    const mi = last.willing_to_drive_miles;
    if (!mi || mi <= 2.5) setWillingToDrive("");
    else setWillingToDrive(String([15, 30, 45].reduce((a, b) => (Math.abs(b - mi * 3) < Math.abs(a - mi * 3) ? b : a))));
    setSurfacePreference(last.surface_preference ?? "");
    setWantsScenic(last.wants_scenic);
    setHillsPref(last.hills_pref ?? "");
    setQuietStreets(!!last.quiet_streets);
    setShapePref(last.shape_pref ?? "");
    setCopied(true);
  }
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [bodyTouched, setBodyTouched] = useState(false);
  function toggleBodyPart(id: string) {
    setBodyTouched(true);
    setSoreParts((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
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
      const response = await fetch(API_URL + "/checkins", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          energy_score: energy,
          sleep_hours: sleepHours ? parseFloat(sleepHours) : null,
          sleep_quality: sleepQuality,
          sore_body_parts: soreParts,
          planned_distance_miles: plannedDistance ? parseFloat(plannedDistance) : null,
          // "Near home" = start within ~2 mi (run or a very short hop there);
          // drive times assume ~20 mph average city driving
          willing_to_drive_miles: willingToDrive ? (parseFloat(willingToDrive) / 60) * 20 : 2,
          wants_adventure: wantsAdventure,
          wants_scenic: wantsScenic,
          surface_preference: surfacePreference || null,
          run_time: runTime,
          available_minutes: !plannedDistance && availableMinutes ? parseFloat(availableMinutes) : null,
          mood_note: moodNote.trim() || null,
          mood,
          run_intent: runIntent,
          hills_pref: hillsPref || null,
          quiet_streets: quietStreets,
          shape_pref: shapePref || null,
        }),
      });
      if (!response.ok) throw new Error(`Server responded with ${response.status}`);
      navigate(runWithGroup ? `/run-together?group=${runWithGroup.id}&auto=1` : "/recommendations");
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
        ? (soreNames.length === 1 && !/s$/.test(soreNames[0]) ? "a " : "") + `sore ${soreNames.join(" and ")}`
        : `${soreNames.length} sore spots`;
  const moodPhrase = mood ? { good: ", feeling good", stressed: ", a bit stressed", restless: ", restless", flat: ", feeling flat", low: ", feeling low" }[mood] : "";
  const feelSentence = `${energyPhrase}${moodPhrase}, ${sleepPhrase}, ${sorePhrase}.`;

  // ---- progress tracker + always-reachable submit bar ----
  const STEP_NAMES = ["Energy", "Sleep", "Body", "Run"];
  const stepDone = [
    mood !== null || energy !== 5,
    sleepHours !== "" || sleepQuality !== 3,
    bodyTouched || soreParts.length > 0,
    runIntent !== null || !!plannedDistance || !!availableMinutes,
  ];
  const finishRef = useRef<HTMLLIElement>(null);
  const [finishVisible, setFinishVisible] = useState(false);
  const [activeStep, setActiveStep] = useState(1);
  useEffect(() => {
    const finish = finishRef.current;
    const io = new IntersectionObserver(([e]) => setFinishVisible(e.isIntersecting), { threshold: 0.2 });
    if (finish) io.observe(finish);
    const steps = [1, 2, 3, 4].map((i) => document.getElementById(`ci-step-${i}`)).filter(Boolean) as HTMLElement[];
    const so = new IntersectionObserver((entries) => {
      const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (vis[0]) setActiveStep(Number(vis[0].target.id.replace("ci-step-", "")));
    }, { rootMargin: "-140px 0px -55% 0px" });
    steps.forEach((el) => so.observe(el));
    return () => { io.disconnect(); so.disconnect(); };
  }, []);
  function jumpTo(i: number) {
    const el = document.getElementById(`ci-step-${i}`);
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 140, behavior: "smooth" });
  }

  const extras: string[] = [];
  if (soreNames.length > 0) extras.push("goes easy on the sore spots");
  if (wantsScenic) extras.push("has a view");
  if (quietStreets) extras.push("sticks to quiet side streets");
  if (shapePref === "out_and_back") extras.push("is an out-and-back");
  if (shapePref === "loop") extras.push("is a loop");
  if (wantsAdventure) extras.push("is somewhere new");
  const surfaceWord = surfacePreference === "trail" ? " of trail" : surfacePreference === "road" ? " of road" : "";
  const intentWord = runIntent ? { easy: "easy ", workout: "workout ", long: "long ", explore: "" }[runIntent] : "";
  const what = plannedDistance
    ? `${plannedDistance} miles${surfaceWord}${runIntent === "easy" ? ", nice and flat" : runIntent === "workout" ? ", flat with few turns for holding a pace" : ""}`
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
        {last && !copied && (
          <button type="button" className="ci-same" onClick={copyLast}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
                 strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" />
            </svg>
            {last.days_ago === 1 ? "Same as yesterday" : `Same as last check-in (${last.days_ago} days ago)`}
          </button>
        )}
        {last && copied && (
          <span className="ci-same done">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
                 strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M5 12.5l4.5 4.5L19 7.5" />
            </svg>
            Filled in. Change anything that's different.
            <button type="button" className="ci-same-undo" onClick={undoCopy}>Undo</button>
          </span>
        )}
      </header>

      <form onSubmit={handleSubmit}>
      <nav className="ci-tracker" aria-label="Check-in progress">
        {STEP_NAMES.map((name, i) => (
          <button
            key={name}
            type="button"
            className={`${stepDone[i] ? "done" : ""} ${activeStep === i + 1 ? "active" : ""}`}
            onClick={() => jumpTo(i + 1)}
          >
            <span className="ci-tracker-dot">{stepDone[i] ? "✓" : i + 1}</span>
            {name}
          </button>
        ))}
        <button
          type="submit"
          className={`ci-tracker-go ${finishVisible ? "faded" : ""}`}
          disabled={loading}
          title={feelSentence}
        >
          {loading ? "Finding..." : runWithGroup ? "Find our route" : "Find my routes"} <span aria-hidden="true">→</span>
        </button>
      </nav>

        <ol className="ci-steps">
          {/* 01 Energy */}
          <li className="ci-step" id="ci-step-1">
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
          <li className="ci-step" id="ci-step-2">
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
          <li className="ci-step" id="ci-step-3">
            <span className="ci-marker">03</span>
            <section className="ci-card">
              <div className="ci-card-head">
                <h2><span className="ci-badge body" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="5" r="2" /><path d="M12 8v6M8 10l4 2 4-2M10 21l2-7 2 7" /></svg></span>Anything sore?</h2>
                <button
                  type="button"
                  className={`ci-chip ${soreParts.length === 0 ? "on" : ""}`}
                  onClick={() => { setSoreParts([]); setBodyTouched(true); }}
                >
                  Feeling fresh
                </button>
              </div>
              <div className="ci-body-grid">
                <BodyMap
                  selected={soreParts}
                  onToggle={toggleBodyPart}
                  labels={Object.fromEntries(MUSCLE_GROUPS.map((m) => [m.id, m.label]))}
                />
                <div className="ci-body-side">
                  <p className="ci-hint">Tap the muscles that are talking to you today. Tap again to clear.</p>
                  {soreParts.length > 0 ? (
                    <>
                      <span className="ci-body-count">{soreParts.length} sore {soreParts.length === 1 ? "spot" : "spots"}</span>
                      <div className="ci-sore-list">
                        {soreParts.map((id) => (
                          <button key={id} type="button" className="ci-chip on removable" onClick={() => toggleBodyPart(id)}>
                            {MUSCLE_GROUPS.find((p) => p.id === id)?.label} ✕
                          </button>
                        ))}
                      </div>
                      <p className="ci-body-note">Pathos will favor softer surfaces and gentler routes for these.</p>
                    </>
                  ) : (
                    <p className="ci-body-empty">{bodyTouched ? "Nothing sore. Nice." : "Nothing selected yet."}</p>
                  )}
                </div>
              </div>
            </section>
          </li>

          {/* 04 Today's run */}
          <li className="ci-step" id="ci-step-4">
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
                {runIntent === "workout" && (
                  <p className="ci-intent-help">
                    For a pace workout: we'll pick flat routes with even footing and few turns, so
                    you can hold your speed. Tracks count. Want hills instead? Set Hills to "Want them".
                  </p>
                )}

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
                  <div className="ci-row">
                    <span className="ci-row-label">Hills</span>
                    <div className="ci-segmented compact">
                      {([["avoid", "Avoid"], ["", "Don't mind"], ["want", "Want them"]] as const).map(([v, label]) => (
                        <button
                          key={label}
                          type="button"
                          className={hillsPref === v ? "on" : ""}
                          onClick={() => setHillsPref(v)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="ci-row">
                    <span className="ci-row-label">Route shape</span>
                    <div className="ci-segmented compact">
                      {([["loop", "Loop"], ["", "Either"], ["out_and_back", "Out & back"]] as const).map(([v, label]) => (
                        <button
                          key={label}
                          type="button"
                          className={shapePref === v ? "on" : ""}
                          onClick={() => setShapePref(v)}
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
                  <label className="ci-row ci-row-toggle">
                    <span className="ci-row-label">
                      Quiet side streets only
                      <small>No busy roads, freeway crossings or downtown</small>
                    </span>
                    <span className={`ci-switch ${quietStreets ? "on" : ""}`}>
                      <input
                        type="checkbox"
                        checked={quietStreets}
                        onChange={(e) => setQuietStreets(e.target.checked)}
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
          <li className="ci-step" ref={finishRef}>
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
              {myGroups.length > 0 && (
                <div className="ci-runwith">
                  <span className="ci-runwith-label">Running with</span>
                  <div className="ci-runwith-options">
                    <button type="button" className={!runWithGroup ? "on" : ""} onClick={() => setRunWith("")}>
                      Just me
                    </button>
                    {myGroups.map((g) => (
                      <button key={g.id} type="button" className={runWith === g.id ? "on" : ""} onClick={() => setRunWith(g.id)}>
                        {g.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {error && <p className="ci-finish-error">{error}</p>}
              <button type="submit" disabled={loading}>
                {loading ? "Finding routes..." : runWithGroup ? `Find our route with ${runWithGroup.name}` : "Find my routes"}
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