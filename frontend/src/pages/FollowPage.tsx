import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { MapContainer, TileLayer, Polyline, CircleMarker, Circle, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { runPath, cumulativeMeters, metersBetween, formatNote, type PlanInput, type RunFormat } from "../utils/routeExport";
import { API_URL } from "../utils/format";

type Cue = { text: string; street: string; icon: string; lat: number; lon: number };
type PlacedCue = Cue & { at: number };   // meters from the start of the route

const ICON_ANGLE: Record<string, number> = {
  straight: 0, depart: 0, "slight right": 45, right: 90, "sharp right": 135, uturn: 180,
  "sharp left": -135, left: -90, "slight left": -45,
};

function TurnIcon({ icon, size = 34 }: { icon: string; size?: number }) {
  if (icon === "finish") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M5 21V4M5 4h11l-2 4 2 4H5" />
      </svg>
    );
  }
  if (icon === "uturn") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M8 20V9a4 4 0 018 0v3M13 9l3 3 3-3" />
      </svg>
    );
  }
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"
      style={{ transform: `rotate(${ICON_ANGLE[icon] ?? 0}deg)` }} aria-hidden="true">
      <path d="M12 20V5M6 11l6-6 6 6" />
    </svg>
  );
}

function formatAhead(m: number): string {
  if (m < 160) return `${Math.max(50, Math.round((m * 3.28084) / 50) * 50)} ft`;
  return `${(m / 1609.34).toFixed(1)} mi`;
}

function spokenAhead(m: number): string {
  if (m < 160) return `${Math.max(50, Math.round((m * 3.28084) / 50) * 50)} feet`;
  return `${(m / 1609.34).toFixed(1)} miles`;
}

function speak(text: string) {
  try {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  } catch {
    // speech not available; cues still show on screen
  }
}

type FollowState = {
  routeId?: string | null;
  recommendationId?: string;
  name: string;
  path: [number, number][];
  format?: RunFormat;
  repeatCount?: number;
  surface?: string | null;
  approachPath?: [number, number][];   // home -> start, from the card (shown until GPS is ready)
  runFromHere?: boolean;               // false = they drive to the trailhead: the run starts there
  plan?: PlanInput;                    // "Out 0.5 mi → loop ×2 → back 0.5 mi"
  totalKm?: number;                    // the whole run, as on the card (laps, run there and back)
};

type GetThere = { path: [number, number][]; distance_m: number; cues: Cue[] };
const AT_START_M = 60;            // closer than this to the start = no "getting there" directions
const DRIVE_NEAR_M = 500;         // driving there: your dot shows once you're this close to the start
const REROUTE_M = 400;            // re-plan the way to the start after moving this far

const OFF_ROUTE_M = 60;          // farther than this from the line = off route
const MAX_ACCURACY_M = 50;       // ignore fixes worse than this for progress
const RESYNC_MATCH_M = 30;       // how close a far-ahead fix must be to jump there
const FINISH_M = 40;             // within this of the end = finished
const SIM_SPEED_MPS = 3.2;       // simulated running pace (~8:20/mi)
const MI = 1609.34;

function MapGrab({ onMap }: { onMap: (m: L.Map) => void }) {
  const map = useMap();
  useEffect(() => {
    onMap(map);   // braces: an effect must not return anything but a cleanup function
  }, [map, onMap]);
  return null;
}

function FitTo({ points, trigger }: { points: [number, number][]; trigger: number }) {
  const map = useMap();
  useEffect(() => {
    if (points.length > 1) {
      const wide = window.innerWidth >= 900;
      map.fitBounds(L.latLngBounds(points), {
        paddingTopLeft: wide ? [440, 40] : [30, 190],
        paddingBottomRight: wide ? [90, 40] : [30, 260],
      });
    } else if (points.length === 1) {
      map.setView(points[0], 17);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trigger]);
  return null;
}

function FollowPage() {
  const navigate = useNavigate();
  const state = useLocation().state as FollowState | null;

  const route = useMemo(() => (state ? runPath(state.path, state.format) : []), [state]);
  const cum = useMemo(() => cumulativeMeters(route), [route]);
  const total = cum[cum.length - 1] ?? 0;

  const [me, setMe] = useState<{ pos: [number, number]; accuracy: number } | null>(null);
  const [geoError, setGeoError] = useState<string | null>(null);
  const [progressIdx, setProgressIdx] = useState(0);
  const [offRoute, setOffRoute] = useState<number | null>(null);
  const [fitTrigger, setFitTrigger] = useState(0);
  const [focus, setFocus] = useState<[number, number][]>(route);
  const lastIdx = useRef(0);
  const mapRef = useRef<L.Map | null>(null);
  const grabMap = useCallback((m: L.Map) => {
    mapRef.current = m;
  }, []);
  const [cues, setCues] = useState<PlacedCue[] | null>(null);
  const [cueStatus, setCueStatus] = useState<"loading" | "ready" | "unavailable">("loading");
  const [showTurns, setShowTurns] = useState(false);
  const [voiceOn, setVoiceOn] = useState(() => {
    try {
      return localStorage.getItem("pathos_voice") === "on";
    } catch {
      return false;
    }
  });
  const announced = useRef<Set<string>>(new Set());
  const [getThere, setGetThere] = useState<GetThere | null>(null);
  const [showGetThere, setShowGetThere] = useState(true);
  const getThereFrom = useRef<[number, number] | null>(null);

  // fetch turn cues once, then pin each one to a distance along the route
  useEffect(() => {
    if (route.length < 2) return;
    fetch(`${API_URL}/directions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: route }),
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: { cues: Cue[] } | null) => {
        if (!data || !data.cues?.length) {
          setCueStatus("unavailable");
          return;
        }
        let from = 0;
        const placed: PlacedCue[] = data.cues.map((c) => {
          // search forward so a cue on the way back isn't pinned to the way out
          let best = from;
          let bestD = Infinity;
          for (let i = from; i < route.length; i++) {
            const d = metersBetween(route[i], [c.lat, c.lon]);
            if (d < bestD) {
              bestD = d;
              best = i;
            }
            if (bestD < 10 && d > 200) break;
          }
          from = best;
          return { ...c, at: cum[best] ?? 0 };
        });
        setCues(placed);
        setCueStatus("ready");
      })
      .catch(() => setCueStatus("unavailable"));
  }, [route, cum]);

  function toggleVoice() {
    const next = !voiceOn;
    setVoiceOn(next);
    try {
      localStorage.setItem("pathos_voice", next ? "on" : "off");
    } catch {
      // fine
    }
    if (next) speak("Voice cues on.");
  }

  // --- run state: start time, finish, simulation, wake lock ---------------
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [finished, setFinished] = useState<{ meters: number; seconds: number } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [weakSignal, setWeakSignal] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [simSpeed, setSimSpeed] = useState(10);
  const [awake, setAwake] = useState(false);
  const [lastAt, setLastAt] = useState(0);
  const pendingJump = useRef<number | null>(null);
  const startedAtRef = useRef<number | null>(null);
  const finishedRef = useRef(false);
  const simRef = useRef(false);

  // one place that turns a position fix into progress (real GPS or simulated)
  function handlePosition(pos: [number, number], accuracy: number, at: number) {
    setMe({ pos, accuracy });
    setLastAt(at);
    setGeoError(null);
    if (finishedRef.current) return;

    // a fuzzy fix can make you jump ahead or "finish" early, so skip it
    if (accuracy > MAX_ACCURACY_M) {
      setWeakSignal(true);
      return;
    }
    setWeakSignal(false);

    // 1. look just behind and ahead of the last match (keeps the way back on
    //    an out-and-back separate from the way out)
    let best = -1;
    let bestD = Infinity;
    const from = Math.max(0, lastIdx.current - 5);
    const to = Math.min(route.length, lastIdx.current + 400);
    for (let i = from; i < to; i++) {
      const d = metersBetween(route[i], pos);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }

    // 2. not near the expected stretch: maybe they joined late or skipped
    //    ahead. Search the rest of the route, but only jump once two fixes
    //    in a row agree, so one bad reading can't teleport you.
    if (bestD > OFF_ROUTE_M) {
      let far = -1;
      let farD = Infinity;
      for (let i = to; i < route.length; i++) {
        const d = metersBetween(route[i], pos);
        if (d < farD) {
          farD = d;
          far = i;
        }
      }
      if (far >= 0 && farD <= RESYNC_MATCH_M) {
        const prev = pendingJump.current;
        if (prev != null && Math.abs((cum[prev] ?? 0) - (cum[far] ?? 0)) < 150) {
          best = far;
          bestD = farD;
          pendingJump.current = null;
        } else {
          pendingJump.current = far;
        }
      } else {
        pendingJump.current = null;
      }
    } else {
      pendingJump.current = null;
    }

    if (best < 0 || bestD > OFF_ROUTE_M) {
      setOffRoute(Math.round(Math.min(bestD, 99999)));
      return;
    }
    setOffRoute(null);
    lastIdx.current = best;
    setProgressIdx(best);

    if (best > 0 && startedAtRef.current == null) {
      startedAtRef.current = at;
      setStartedAt(at);
    }

    // finished: near the end and most of the route covered
    const doneM = cum[best] ?? 0;
    if (total - doneM <= FINISH_M && doneM >= total * 0.8 && startedAtRef.current != null) {
      finishedRef.current = true;
      setFinished({ meters: total, seconds: Math.round((at - startedAtRef.current) / 1000) });
      try {
        navigator.vibrate?.([200, 100, 200, 100, 300]);
      } catch {
        // no vibration
      }
      if (voiceOn) speak(`Run complete. Nice work.`);
    }
  }
  const handleRef = useRef(handlePosition);
  handleRef.current = handlePosition;

  // real GPS
  useEffect(() => {
    if (!navigator.geolocation) {
      setGeoError("Location isn't available in this browser.");
      return;
    }
    const id = navigator.geolocation.watchPosition(
      (p) => {
        if (simRef.current) return;   // simulation is driving the dot
        handleRef.current([p.coords.latitude, p.coords.longitude], p.coords.accuracy, p.timestamp || Date.now());
      },
      (err) => {
        if (simRef.current) return;
        setGeoError(
          err.code === err.PERMISSION_DENIED
            ? "Allow location access to see where you are on the route."
            : "Can't get your location right now."
        );
      },
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 15000 }
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [route]);

  // keep the screen on while following (otherwise phones pause GPS)
  useEffect(() => {
    type WakeLock = { release: () => Promise<void> };
    const nav = navigator as Navigator & { wakeLock?: { request: (t: "screen") => Promise<WakeLock> } };
    if (!nav.wakeLock) return;
    let lock: WakeLock | null = null;
    let cancelled = false;
    async function acquire() {
      try {
        lock = await nav.wakeLock!.request("screen");
        if (!cancelled) setAwake(true);
      } catch {
        setAwake(false);
      }
    }
    function onVisible() {
      if (document.visibilityState === "visible") acquire();
    }
    acquire();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
      lock?.release().catch(() => {});
    };
  }, []);

  // clock for the elapsed time
  useEffect(() => {
    if (startedAt == null || finished) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [startedAt, finished]);

  // simulated run: walk the route at running pace (sped up), with GPS-like jitter
  useEffect(() => {
    simRef.current = simulating;
    if (!simulating) return;
    let dist = cum[lastIdx.current] ?? 0;
    let j = 0;
    let clock = Date.now();
    const tickMs = 500;
    const id = setInterval(() => {
      dist += SIM_SPEED_MPS * simSpeed * (tickMs / 1000);
      clock += tickMs * simSpeed;      // simulated clock runs fast too
      if (dist >= total) dist = total;
      while (j < cum.length - 2 && cum[j + 1] < dist) j++;
      const seg = (cum[j + 1] ?? cum[j]) - cum[j] || 1;
      const t = Math.min(1, Math.max(0, (dist - cum[j]) / seg));
      const a = route[j];
      const b = route[Math.min(j + 1, route.length - 1)];
      const jitter = () => (Math.random() - 0.5) * 0.00006;   // ~±3 m
      const pos: [number, number] = [a[0] + (b[0] - a[0]) * t + jitter(), a[1] + (b[1] - a[1]) * t + jitter()];
      handleRef.current(pos, 6, clock);
      if (dist >= total) setSimulating(false);
    }, tickMs);
    return () => clearInterval(id);
  }, [simulating, simSpeed, route, cum, total]);

  // back to the start line, everything cleared, not moving
  function resetSimulation() {
    setSimulating(false);
    setOffRoute(null);
    setWeakSignal(false);
    pendingJump.current = null;
    lastIdx.current = 0;
    setProgressIdx(0);
    startedAtRef.current = null;
    setStartedAt(null);
    finishedRef.current = false;
    setFinished(null);
    announced.current = new Set();
    handleRef.current(route[0], 6, Date.now());
  }

  function startSimulation() {
    resetSimulation();
    // start on the next tick so the reset has settled first
    setTimeout(() => setSimulating(true), 0);
  }

  const [locating, setLocating] = useState(false);

  // move the map to you; if no fix has come in yet, ask for one right now
  function centerOnMe() {
    const go = (pos: [number, number]) => {
      const map = mapRef.current;
      if (!map) return;
      map.flyTo(pos, Math.max(map.getZoom(), 16), { duration: 0.6 });
    };
    if (me) {
      go(me.pos);
      return;
    }
    if (!navigator.geolocation) {
      setGeoError("Location isn't available in this browser.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setLocating(false);
        const pos: [number, number] = [p.coords.latitude, p.coords.longitude];
        if (!simRef.current) handleRef.current(pos, p.coords.accuracy, p.timestamp || Date.now());
        go(pos);
      },
      (err) => {
        setLocating(false);
        setGeoError(
          err.code === err.PERMISSION_DENIED
            ? "Location is blocked. Allow it for this site in your browser's address bar, then try again."
            : "Couldn't find your location. Try again in a moment."
        );
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 10000 }
    );
  }

  function logThisRun() {
    if (!finished) return;
    const miles = finished.meters / 1609.34;
    navigate("/log-run", {
      state: {
        routeId: state?.routeId ?? undefined,
        routeName: state?.name,
        recommendationId: state?.recommendationId,
        prefill: {
          miles: miles.toFixed(2),
          minutes: String(Math.floor(finished.seconds / 60)),
          seconds: String(finished.seconds % 60),
          source: "follow",
        },
      },
    });
  }

  // vibrate and (optionally) speak as each turn comes up
  useEffect(() => {
    if (!cues || progressIdx === 0) return;
    const doneM = cum[progressIdx] ?? 0;
    const upcoming = cues.find((c) => c.at > doneM + 8);
    if (!upcoming) return;
    const ahead = upcoming.at - doneM;
    const key = `${upcoming.at}`;
    if (ahead <= 120 && !announced.current.has(key + "-pre")) {
      announced.current.add(key + "-pre");
      if (voiceOn) speak(`In ${spokenAhead(ahead)}, ${upcoming.text}`);
    }
    if (ahead <= 25 && !announced.current.has(key + "-now")) {
      announced.current.add(key + "-now");
      try {
        navigator.vibrate?.([120, 80, 120]);
      } catch {
        // no vibration support
      }
      if (voiceOn) speak(upcoming.text);
    }
  }, [progressIdx, cues, cum, voiceOn]);

  // directions from where the runner is to the start of the route (re-planned if they move a lot)
  useEffect(() => {
    if (!me || route.length < 2 || progressIdx > 0) return;
    if (state?.runFromHere === false) return;      // driving there: no running directions to the start
    const startPt = route[0];
    if (metersBetween(me.pos, startPt) < AT_START_M) {
      setGetThere(null);
      return;
    }
    if (getThereFrom.current && metersBetween(getThereFrom.current, me.pos) < REROUTE_M) return;
    getThereFrom.current = me.pos;
    fetch(`${API_URL}/directions/to-start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ origin: me.pos, start: startPt }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d: GetThere | null) => {
        if (d && d.path?.length > 1) {
          setGetThere(d);
          setFocus([...d.path, ...route]);
          setFitTrigger((t) => t + 1);
        }
      })
      .catch(() => {});
  }, [me, route, progressIdx, state?.runFromHere]);

  if (!state || route.length < 2) {
    return (
      <div className="follow-empty">
        <p>No route to follow. Pick one from your recommendations or favorites.</p>
        <button onClick={() => navigate("/recommendations")}>Back to routes</button>
      </div>
    );
  }

  const start = route[0];
  const driving = state.runFromHere === false;
  const wayRaw = driving ? [] : getThere?.path ?? state.approachPath ?? [];
  const wayThere: [number, number][] = wayRaw.length > 1
    ? [...(me ? [me.pos] : []), ...wayRaw, start]
    : [];
  const turnaround = state.format === "out_and_back" ? state.path[state.path.length - 1] : null;
  const done = cum[progressIdx] ?? 0;
  // the whole run (same number as the card), and what's left beyond this pass of the
  // drawn route: more laps, and the run home if they ran here
  const approachM = state.runFromHere ? (state.plan?.approachKm ?? 0) * 1000 : 0;
  const runTotal = state.totalKm ? state.totalKm * 1000 : total;
  const extraAfter = Math.max(0, runTotal - approachM - total);
  const partLabel = state.format === "repeat" && (state.repeatCount ?? 1) > 1 ? "One lap"
    : state.format === "out_and_back" ? "Out & back" : "Route";
  const started = progressIdx > 0;
  const toStart = me ? metersBetween(me.pos, start) : null;
  const elapsedS = finished
    ? finished.seconds
    : startedAt != null
      ? Math.max(0, Math.round((Math.max(now, lastAt) - startedAt) / 1000))
      : 0;
  const clockText = (sec: number) => {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const ss = String(sec % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
  };
  const nextCue = cues?.find((c) => (started ? c.at > done + 8 : true)) ?? null;
  const nextIn = nextCue ? Math.max(0, nextCue.at - done) : null;
  const note = formatNote(state.format, state.repeatCount, state.plan);

  const icons = {
    voiceOn: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M11 5L6 9H3v6h3l5 4V5z" /><path d="M15.5 8.5a5 5 0 010 7M18.5 5.5a9 9 0 010 13" />
      </svg>
    ),
    voiceOff: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M11 5L6 9H3v6h3l5 4V5z" /><path d="M22 9l-6 6M16 9l6 6" />
      </svg>
    ),
    fit: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
      </svg>
    ),
    locate: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="4" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
      </svg>
    ),
  };

  return (
    <div className="follow-page">
      <MapContainer center={start} zoom={15} zoomControl={false} className="follow-map">
        <FitTo points={focus} trigger={fitTrigger} />
        <MapGrab onMap={grabMap} />
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' />
        {!started && wayThere.length > 1 && (
          <>
            {/* same style as the route, joined exactly to you and to the start: one continuous line */}
            <Polyline positions={wayThere} pathOptions={{ color: "#FFFFFF", weight: 11, opacity: 0.95, lineJoin: "round", lineCap: "round" }} />
            <Polyline positions={wayThere} pathOptions={{ color: "#93C5FD", weight: 6, opacity: 1, lineJoin: "round", lineCap: "round" }} />
          </>
        )}
        <Polyline positions={route} pathOptions={{ color: "#FFFFFF", weight: 11, opacity: 0.95 }} />
        <Polyline positions={route} pathOptions={{ color: "#93C5FD", weight: 6, opacity: 1 }} />
        {started && (
          <Polyline positions={route.slice(0, progressIdx + 1)} pathOptions={{ color: "#1D4ED8", weight: 6, opacity: 1 }} />
        )}
        {nextCue && started && (
          <CircleMarker center={[nextCue.lat, nextCue.lon]} radius={7} pathOptions={{ color: "#1D4ED8", weight: 3, fillColor: "#FFFFFF", fillOpacity: 1 }} />
        )}
        {turnaround && (
          <CircleMarker center={turnaround} radius={8} pathOptions={{ color: "#1D4ED8", weight: 3, fillColor: "#FFFFFF", fillOpacity: 1 }} />
        )}
        {/* one dot: while there's a way to the start, the line begins at you (or home), so
            the route's own start dot is hidden until you get there */}
        {(started || wayThere.length < 2) && (
          <CircleMarker center={start} radius={10} pathOptions={{ color: "#FFFFFF", weight: 4, fillColor: "#1D4ED8", fillOpacity: 1 }} />
        )}
        {!started && wayThere.length > 1 && !me && (
          <CircleMarker center={wayThere[0]} radius={10} pathOptions={{ color: "#FFFFFF", weight: 4, fillColor: "#1D4ED8", fillOpacity: 1 }} />
        )}
        {/* driving to the trailhead: show where you are only once you're there */}
        {me && (!driving || started || (toStart != null && toStart < DRIVE_NEAR_M)) && (
          <>
            <Circle center={me.pos} radius={me.accuracy} pathOptions={{ color: "#2563EB", weight: 1, fillOpacity: 0.12 }} />
            <CircleMarker center={me.pos} radius={8} pathOptions={{ color: "#FFFFFF", weight: 3, fillColor: "#2563EB", fillOpacity: 1 }} />
          </>
        )}
      </MapContainer>

      <div className="follow-side">
        {/* top: title + next turn */}
        <div className="follow-card follow-head">
          <div className="follow-title-row">
            <button className="follow-back" onClick={() => navigate(-1)} aria-label="Back">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M15 18l-6-6 6-6" />
              </svg>
            </button>
            <div className="follow-title">
              <span className="follow-eyebrow">
                {simulating ? "Simulating run" : "Following"}
                {awake && !simulating && <span className="follow-awake"> · screen stays on</span>}
              </span>
              <h1>{state.name}</h1>
            </div>
          </div>

          {nextCue && (
            <div className="follow-next" aria-live="polite">
              <span className="follow-next-icon">
                <TurnIcon icon={nextCue.icon} size={30} />
              </span>
              <div className="follow-next-text">
                <span className="follow-next-dist">
                  {!started ? "First direction" : nextIn != null && nextIn < 25 ? "Now" : `In ${formatAhead(nextIn ?? 0)}`}
                </span>
                <strong>{nextCue.text}</strong>
              </div>
            </div>
          )}
        </div>

        {/* bottom: stats, actions, turn list */}
        <div className="follow-card follow-sheet">
          {started && (
            <div className="follow-progress">
              <span style={{ width: `${Math.min(100, (done / total) * 100)}%` }} />
            </div>
          )}
          <div className={`follow-stats ${started ? "three" : ""}`}>
            {!started ? (
              <>
                <div>
                  <span className="follow-num">{(runTotal / MI).toFixed(1)}<small>mi</small></span>
                  <span className="follow-label">Total run</span>
                </div>
                {Math.abs(runTotal - total) > 0.05 * MI && (
                  <div>
                    <span className="follow-num">{(total / MI).toFixed(1)}<small>mi</small></span>
                    <span className="follow-label">{partLabel}</span>
                  </div>
                )}
              </>
            ) : (
              <>
                <div>
                  <span className="follow-num">{((done + approachM) / MI).toFixed(2)}<small>mi</small></span>
                  <span className="follow-label">Done</span>
                </div>
                <div>
                  <span className="follow-num">{(Math.max(0, total - done + extraAfter) / MI).toFixed(2)}<small>mi</small></span>
                  <span className="follow-label">To go</span>
                </div>
                <div>
                  <span className="follow-num">{clockText(elapsedS)}</span>
                  <span className="follow-label">Time</span>
                </div>
              </>
            )}
          </div>

          {(note || !started) && (
            <p className="follow-hint">
              {!started &&
                (toStart != null && toStart <= OFF_ROUTE_M
                  ? "You're at the start. Head off along the route and your progress fills in."
                  : "Head to the dark blue dot to start.")}
              {note && ` ${note}`}
            </p>
          )}

          {offRoute != null && started && (
            <p className="follow-warn">You're about {Math.round(offRoute * 3.28084)} ft off the route.</p>
          )}
          {geoError && <p className="follow-warn">{geoError}</p>}
          {weakSignal && !geoError && (
            <p className="follow-warn">Weak GPS signal. Progress will resume when it sharpens.</p>
          )}

          {!started && driving && (toStart == null || toStart >= DRIVE_NEAR_M) && (
            <a className="follow-drive-link" target="_blank" rel="noreferrer"
               href={`https://www.google.com/maps/dir/?api=1&destination=${start[0]},${start[1]}&travelmode=driving`}>
              Drive to the start
            </a>
          )}

          {!started && getThere && toStart != null && toStart >= AT_START_M && (
            <div className="follow-turns-wrap follow-getthere">
              <button className="follow-turns-toggle" onClick={() => setShowGetThere(!showGetThere)} aria-expanded={showGetThere}>
                <span>Getting to the start</span>
                <span className="follow-turns-count">
                  {(getThere.distance_m / 1609.34).toFixed(1)} mi
                </span>
                <span className={`chevron ${showGetThere ? "open" : ""}`}>▾</span>
              </button>
              {showGetThere && (
                <ol className="follow-turns">
                  {getThere.cues.map((c, i) => (
                    <li key={i}>
                      <span className="follow-turn-icon"><TurnIcon icon={c.icon} size={16} /></span>
                      <span className="follow-turn-text">{c.text}</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}

          {cueStatus === "ready" && cues && (
            <div className="follow-turns-wrap">
              <button className="follow-turns-toggle" onClick={() => setShowTurns(!showTurns)} aria-expanded={showTurns}>
                <span>Turn-by-turn</span>
                <span className="follow-turns-count">{cues.length} turns</span>
                <span className={`chevron ${showTurns ? "open" : ""}`}>▾</span>
              </button>
              {showTurns && (
                <ol className="follow-turns">
                  {cues.map((c, i) => (
                    <li key={i} className={started && c.at <= done ? "passed" : c === nextCue ? "next" : ""}>
                      <span className="follow-turn-icon">
                        <TurnIcon icon={c.icon} size={16} />
                      </span>
                      <span className="follow-turn-text">{c.text}</span>
                      <span className="follow-turn-at">{(c.at / 1609.34).toFixed(1)} mi</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
          {cueStatus === "unavailable" && (
            <p className="follow-hint follow-muted">Turn-by-turn cues aren't available right now. Follow the line on the map.</p>
          )}
        </div>
      </div>

      {import.meta.env.DEV && !finished && (
        <div className="follow-sim">
          {simulating || started ? (
            <>
              <select value={simSpeed} onChange={(e) => setSimSpeed(Number(e.target.value))} aria-label="Simulation speed">
                <option value={1}>1×</option>
                <option value={5}>5×</option>
                <option value={10}>10×</option>
                <option value={30}>30×</option>
              </select>
              {simulating ? (
                <button onClick={() => setSimulating(false)}>❚❚ Pause</button>
              ) : (
                <button onClick={() => setSimulating(true)}>▶ Resume</button>
              )}
              <button onClick={resetSimulation} title="Go back to the start and stop">↺ Restart</button>
            </>
          ) : (
            <button onClick={startSimulation} title="Development only: replay the route at running pace">
              ▶ Simulate run
            </button>
          )}
        </div>
      )}

      {finished && (
        <div className="follow-finish-backdrop">
          <div className="follow-finish">
            <div className="logged-check" aria-hidden="true">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
                <path className="logged-check-path" d="M5 12.5l4.5 4.5L19 7.5" />
              </svg>
            </div>
            <h2>Run complete</h2>
            <p className="follow-finish-route">{state.name}</p>
            <div className="logged-stats">
              <div className="logged-stat">
                <span className="logged-stat-value">{(finished.meters / MI).toFixed(1)}</span>
                <span className="logged-stat-label">miles</span>
              </div>
              <div className="logged-stat">
                <span className="logged-stat-value">{clockText(finished.seconds)}</span>
                <span className="logged-stat-label">time</span>
              </div>
              <div className="logged-stat">
                <span className="logged-stat-value">
                  {clockText(Math.round(finished.seconds / (finished.meters / MI)))}
                </span>
                <span className="logged-stat-label">pace /mi</span>
              </div>
            </div>
            <div className="logged-actions">
              <button className="logged-primary" onClick={logThisRun}>Log this run</button>
              <button className="logged-secondary" onClick={() => navigate("/recommendations")}>Done</button>
            </div>
            {import.meta.env.DEV && (
              <button className="follow-rerun" onClick={resetSimulation}>↺ Reset the simulation</button>
            )}
            <p className="follow-finish-note">Logging adds how it felt, which shapes tomorrow's picks.</p>
          </div>
        </div>
      )}

      <div className="follow-controls">
        <div className="follow-zoom">
          <button onClick={() => mapRef.current?.zoomIn()} aria-label="Zoom in" title="Zoom in">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
          <button onClick={() => mapRef.current?.zoomOut()} aria-label="Zoom out" title="Zoom out">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
              <path d="M5 12h14" />
            </svg>
          </button>
        </div>
        <button onClick={toggleVoice} aria-pressed={voiceOn} aria-label="Voice cues" title={voiceOn ? "Voice cues on" : "Voice cues off"} className={voiceOn ? "on" : ""}>
          {voiceOn ? icons.voiceOn : icons.voiceOff}
        </button>
        <button
          onClick={() => {
            setFocus(route);
            setFitTrigger((t) => t + 1);
          }}
          aria-label="Show whole route"
          title="Show whole route"
        >
          {icons.fit}
        </button>
        <button
          onClick={centerOnMe}
          className={locating ? "busy" : ""}
          aria-label="Center on me"
          title="Center on me"
        >
          {icons.locate}
        </button>
      </div>
    </div>
  );
}

export default FollowPage;
