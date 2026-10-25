import type React from "react";
import { Fragment, useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { MapContainer, TileLayer, Polyline, CircleMarker, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useRouteActions } from "../components/RouteExportButtons";
import { runPlan, type PlanInput } from "../utils/routeExport";
import { type GroupMatch, formatMeetTime, sessionTitle } from "./GroupsPage";
import { API_URL } from "../utils/format";

// The phone/browser location, or null if it's not allowed or takes too long (then home is used).
function currentPosition(): Promise<[number, number] | null> {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    const timer = setTimeout(() => resolve(null), 6000);
    navigator.geolocation.getCurrentPosition(
      (p) => { clearTimeout(timer); resolve([p.coords.latitude, p.coords.longitude]); },
      () => { clearTimeout(timer); resolve(null); },
      { enableHighAccuracy: false, maximumAge: 5 * 60 * 1000, timeout: 6000 }
    );
  });
}

// The whole thing as one line: origin -> (streets) -> route start -> route. The
// street path is pinned to the exact origin and start so there's never a gap or jump.
function fullLine(rec: Recommendation): [number, number][] {
  const way = rec.approach_path ?? [];
  // only when the route starts close by and is run from where they are; otherwise just the route
  if ((rec.approach_km ?? 0) <= 0 || way.length < 2 || !rec.home) return rec.path;
  return [rec.home, ...way, rec.path[0], ...rec.path];
}

function MapResizer({ path, extra = [] }: { path: [number, number][]; extra?: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (path.length < 2) return;
    const fit = () => {
      map.invalidateSize();
      const bounds = [...path, ...extra].reduce(
        (b, [lat, lon]) => b.extend([lat, lon]),
        L.latLngBounds([path[0]])
      );
      // room on the left for the rank badge, and at the bottom for the fade into the card;
      // otherwise fill the map (fractional zoom, so a tall route isn't zoomed a whole level too far out)
      map.fitBounds(bounds, { paddingTopLeft: [64, 18], paddingBottomRight: [22, 34], animate: false });
    };
    const t = setTimeout(fit, 60);
    // refit whenever the card changes size (images/fonts loading, rotating the phone)
    const ro = new ResizeObserver(() => fit());
    ro.observe(map.getContainer());
    return () => { clearTimeout(t); ro.disconnect(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, JSON.stringify(path[0]), JSON.stringify(path[path.length - 1]), path.length, extra.length]);
  return null;
}

type Recommendation = {
  recommendation_id?: string;
  rank?: number;
  route_id: string | null;
  route_name: string;
  score: number;
  reasons: string[];
  notice?: string | null;
  needs_drive?: boolean;                // starts beyond their travel limit (shown anyway, and said so)
  difficulty_label?: string;
  approach_km?: number;                 // each way, home -> start (0 = travel there instead)
  approach_path?: [number, number][];   // the streets from home to the start
  home?: [number, number];
  travel_km?: number | null;
  origin_source?: "current" | "home";   // planned from the phone's location, or the signup address            // home -> start, when it's farther than a run-there   // e.g. "Long, gentle" for a flat run that's Hard only by length   // e.g. a gentler route a little beyond the travel limit
  distance_km: number;
  elevation_gain_m: number;
  difficulty: string;
  surface_type?: string;
  estimated_minutes?: number;
  score_breakdown?: Record<string, number>;
  effective_distance_km?: number;
  run_format?: string;
  repeat_count?: number;
  path: [number, number][];
  perfect_points?: number;            // match % = (score - 100) / this
  // facts shown in "Why this route"
  target_km?: number | null;
  shade_pct?: number | null;
  scenic_pct?: number | null;
  busy_pct?: number | null;
  freeway_crossings?: number | null;
  downtown_pct?: number | null;
  turns_per_km?: number | null;
  stem_km?: number | null;
  turnaround_km?: number | null;
  days_since_run?: number | null;
  your_rating?: number | null;
  feels_like_f?: number | null;
};

// Plain-language explanation for each scoring factor.
// [when it raised the score, when it lowered the score]
// Raw scores start at 100 and add or lose points per factor; in practice a
// weak route lands around 80 and an excellent one around 170. Show that span
// as a 0-100% match so it reads like every other rating.
const BASE_SCORE = 100;          // every route's starting score in the engine
const PERFECT_POINTS = 85;       // points a route that fits everything earns
// Match % is simply points earned out of a perfect +85, so the number on the
// card is exactly the total in "Why this route" divided by 85. (85 leaves room
// at the top: in a 192-pick audit the best routes scored +75 to +78, so strong
// picks read in the 80s-90s instead of piling up at 100%.)
// perfect = what a route that fits everything could earn for THIS check-in (sent by the
// server; it grows with each extra thing asked for). Capped at 99%: nothing is perfect.
function matchPct(score: number, perfect: number = PERFECT_POINTS): number {
  return Math.round(Math.max(0, Math.min(0.99, (score - BASE_SCORE) / perfect)) * 100);
}

// The card shows a plain label instead of the raw %: the % is points out of a
// "fits everything" route, so 45% reads like a failing grade when it's really
// "decent, with one thing off". The exact % is in the label's tooltip.
function matchLabel(score: number, perfect?: number): { text: string; tone: "great" | "good" | "look" } {
  const pct = matchPct(score, perfect);
  if (pct >= 70) return { text: "Great match", tone: "great" };
  if (pct >= 50) return { text: "Good match", tone: "good" };
  return { text: "Worth a look", tone: "look" };
}


type Conditions = {
  run_time: string;
  temp_f: number | null;
  feels_like_f: number | null;
  uv_index: number | null;
  wind_mph: number | null;
  us_aqi: number | null;
  rain_last_48h_mm: number;
  sunset: string | null;
  minutes_until_sunset: number | null;
  is_tomorrow?: boolean;
  now_temp_f?: number | null;
  now_feels_like_f?: number | null;
  heat_cut_pct?: number | null;
  cooler_option?: { run_time: string; label: string; clock: string; feels_like_f: number; cooler_by_f: number } | null;
};

function aqiLabel(aqi: number): string {
  if (aqi <= 50) return "Good";
  if (aqi <= 100) return "Moderate";
  if (aqi <= 150) return "Unhealthy for some";
  if (aqi <= 200) return "Unhealthy";
  return "Very unhealthy";
}

function formatClockTime(iso: string): string {
  const [, time] = iso.split("T");
  const [h, m] = time.split(":").map(Number);
  const hour12 = ((h + 11) % 12) + 1;
  return `${hour12}:${String(m).padStart(2, "0")} ${h < 12 ? "am" : "pm"}`;
}

// Conditions card: stat tiles in the app's blue, turning orange / red when a value
// is worth watching (heat, bad air, strong wind, lots of rain, little daylight left).
const COND_ICONS: Record<string, string[]> = {
  temp: ["M14 14.8V4a2 2 0 0 0-4 0v10.8a4 4 0 1 0 4 0z"],
  air: ["M3 8h11a3 3 0 1 0-3-3", "M3 12h15a3 3 0 1 1-3 3", "M3 16h7"],
  uv: ["M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"],
  wind: ["M3 8h11a3 3 0 1 0-3-3", "M3 12h15a3 3 0 1 1-3 3"],
  rain: ["M7 15a4 4 0 0 1 .5-8 5.5 5.5 0 0 1 10.5 2 3.5 3.5 0 0 1 0 6", "M9 18l-1 2M13 18l-1 2M17 18l-1 2"],
  sunset: ["M17 18a5 5 0 0 0-10 0", "M12 9V3M4.2 10.2l1.4 1.4M1 18h2M21 18h2M18.4 11.6l1.4-1.4M23 22H1", "M16 6l-4 3-4-3"],
};

// The app's blue by default; orange / red only when a value is worth watching.
const TONE = "var(--accent)";
const WARM = "#EA580C";
const BAD = "#DC2626";
function tempTone(f: number) { return f < 85 ? TONE : f < 95 ? WARM : BAD; }
function aqiTone(a: number) { return a <= 100 ? TONE : a <= 150 ? WARM : BAD; }

function condStats(c: Conditions) {
  const out: { label: string; value: string; unit?: string; tone: string; icon: string }[] = [];
  const feels = c.feels_like_f ?? c.temp_f;
  if (feels != null) out.push({ label: "Feels like", value: String(Math.round(feels)), unit: "°F", tone: tempTone(feels), icon: "temp" });
  if (c.us_aqi != null) out.push({ label: `Air · ${aqiLabel(c.us_aqi)}`, value: String(Math.round(c.us_aqi)), tone: aqiTone(c.us_aqi), icon: "air" });
  if (c.uv_index != null && c.uv_index >= 6)
    out.push({ label: `UV · ${c.uv_index >= 8 ? "Very high" : "High"}`, value: String(Math.round(c.uv_index)), tone: c.uv_index >= 8 ? WARM : TONE, icon: "uv" });
  if (c.wind_mph != null && c.wind_mph >= 12)
    out.push({ label: "Wind", value: String(Math.round(c.wind_mph)), unit: "mph", tone: c.wind_mph >= 20 ? WARM : TONE, icon: "wind" });
  if (c.rain_last_48h_mm >= 1)
    out.push({ label: "Rain, last 48h", value: String(c.rain_last_48h_mm), unit: "mm", tone: c.rain_last_48h_mm >= 5 ? WARM : TONE, icon: "rain" });
  if (c.sunset) {
    const t = formatClockTime(c.sunset);
    out.push({ label: "Sunset", value: t.slice(0, -3), unit: t.slice(-2), tone: c.minutes_until_sunset != null && c.minutes_until_sunset < 75 ? WARM : TONE, icon: "sunset" });
  }
  return out;
}

// one short sentence about how conditions are shaping today's picks
function conditionsVerdict(c: Conditions): string {
  const feels = c.feels_like_f ?? c.temp_f;
  const notes: string[] = [];
  if (feels != null && feels >= 95) notes.push("it's dangerously hot");
  else if (feels != null && feels >= 85) notes.push("it's hot");
  else if (c.heat_cut_pct) notes.push("it's warm");
  if (c.us_aqi != null && c.us_aqi > 100) notes.push("the air is hazy");
  if (c.rain_last_48h_mm >= 5) notes.push("trails may be muddy");
  if (c.minutes_until_sunset != null && c.minutes_until_sunset < 75) notes.push("daylight is running short");
  if (c.wind_mph != null && c.wind_mph >= 20) notes.push("it's windy");
  if (notes.length === 0) return "Good running conditions. Nothing to work around today.";
  const list = notes.length > 1 ? `${notes.slice(0, -1).join(", ")} and ${notes[notes.length - 1]}` : notes[0];
  return `${list.charAt(0).toUpperCase() + list.slice(1)}, so your picks are adjusted for it.`;
}

// Clause for each factor, used to build a one-line headline from a route's top strengths
const HEADLINE_CLAUSES: Record<string, string> = {
  appeal: "it runs through parks, trees or along water",
  novelty: "you haven't run it in a while",
  proximity: "it starts right near home",
  terrain: "the climbing suits your energy today",
  distance: "it lands right on the distance you want",
  scenic: "it has the views you asked for",
  surface_pref: "it's on the surface you wanted",
  surface_relief: "the softer surface spares your sore muscles",
  adventure: "it's somewhere new, like you wanted",
  rating: "you've loved it before",
  taste_surface: "it's on your favorite kind of surface",
  taste_scenic: "it's scenic, and you love scenic runs",
  taste_loop: "it's a loop, your favorite format",
  goal: "it fits your training goal",
  rhythm: "it's gentle enough for a recovery day",
  soreness_history: "you usually bounce back well from runs like this",
  overload: "it keeps your weekly mileage in check",
  mood: "it suits how you're feeling today",
  intent: "it fits the kind of run you wanted",
  shape: "it's the route shape you asked for",
  feel: "it's the right kind of run for how you feel",
  quiet: "it stays on quiet streets and paths",
  turns: "it has few turns, so it's easy to follow",
};

function buildHeadline(breakdown: Record<string, number> | undefined, fallback?: string): string | null {
  const top = Object.entries(breakdown ?? {})
    .filter(([key, pts]) => pts >= 2 && HEADLINE_CLAUSES[key])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2)
    .map(([key]) => HEADLINE_CLAUSES[key]);
  if (top.length === 0) return fallback ?? null;
  const sentence = top.length === 2 ? `${top[0]}, and ${top[1]}` : top[0];
  return sentence.charAt(0).toUpperCase() + sentence.slice(1) + ".";
}


// "Why this route": the score factors grouped into plain categories, each
// rated out of 5 with the one or two things that mattered most. No points or
// math - the card's label (Great / Good / Worth a look) is the overall answer.
const WHY_GROUPS: { title: string; keys: string[]; full: number }[] = [
  { title: "Distance", full: 25, keys: ["distance", "format"] },
  { title: "Climbing", full: 20, keys: ["terrain", "hills", "feel"] },
  { title: "Soreness", full: 4, keys: ["soreness", "injury", "surface_relief", "soreness_history"] },
  { title: "Energy & sleep", full: 4, keys: ["energy", "footing", "rhythm", "overload"] },
  { title: "Surface", full: 15, keys: ["surface_pref", "taste_surface"] },
  { title: "Scenery", full: 8, keys: ["appeal", "scenic", "taste_scenic"] },
  { title: "Roads & turns", full: 6, keys: ["traffic", "quiet", "freeway", "downtown", "turns"] },
  { title: "Location", full: 12, keys: ["proximity", "approach"] },
  { title: "Something new", full: 8, keys: ["novelty", "adventure", "variety"] },
  { title: "Your ratings", full: 8, keys: ["rating", "taste_loop"] },
  { title: "Run type & mood", full: 6, keys: ["intent", "goal", "mood", "shape"] },
  { title: "Weather", full: 6, keys: ["heat", "shade", "air", "wind", "mud", "wet", "daylight"] },
];

// [when it helped, when it hurt]
const WHY_PHRASES: Record<string, [string, string]> = {
  distance: ["Right around the distance you wanted", "Off from the distance you wanted"],
  format: ["Simple to follow", "Takes laps or doubling back to reach your distance"],
  intent: ["Fits the kind of run you wanted", "Not quite the kind of run you wanted"],
  goal: ["Fits your training goal", "Doesn't help your training goal much"],
  surface_pref: ["On the surface you picked", "Not the surface you picked"],
  scenic: ["Has the views you asked for", "Not very scenic"],
  adventure: ["Somewhere new, like you asked", "You've run it recently"],
  hills: ["The amount of climbing you asked for", "Not the amount of climbing you asked for"],
  terrain: ["The climbing suits your energy today", "The climbing doesn't suit how you feel today"],
  feel: ["The right kind of run for how you feel", "Not the kind of run you need today"],
  soreness: ["Easy on your sore legs", "Harder on your sore legs"],
  injury: ["Easy on your injury", "Puts strain on your injury"],
  surface_relief: ["Softer ground for your sore legs", "Firmer ground for your sore legs"],
  soreness_history: ["You usually recover well from runs like this", "You've been sorer after runs like this"],
  energy: ["Manageable for your energy", "Tough for a low-energy day"],
  footing: ["Even footing", "Uneven ground after a short night"],
  rhythm: ["Easy enough for a recovery day", "Hilly or long for a recovery day"],
  overload: ["Keeps your week in check", "Long for a week you've already run a lot"],
  mood: ["Suits your mood", "Doesn't suit your mood"],
  shape: ["The route shape you picked", "Not the route shape you picked"],
  proximity: ["Starts close to you", "Starts a way from you"],
  approach: ["Short run to the start", "Most of the run is getting to the route"],
  appeal: ["Parks, trees or water along the way", "Mostly plain streets"],
  traffic: ["Away from busy roads", "Runs along busy roads"],
  quiet: ["Quiet streets and paths", "Some busy roads"],
  freeway: ["No freeway crossings", "Crosses a freeway"],
  downtown: ["Stays out of downtown", "Goes through downtown"],
  turns: ["Few turns, easy to follow", "Lots of turns to keep track of"],
  novelty: ["Somewhere you haven't run lately", "You ran it recently"],
  rating: ["You've rated it well before", "You've rated it low before"],
  taste_surface: ["The kind of surface you like", "A surface you tend to rate low"],
  taste_scenic: ["The kind of scenery you like", "Not your kind of scenery"],
  taste_loop: ["A loop, which you like", "Not a loop"],
  variety: ["Different from the other picks", "Similar to another pick"],
  heat: ["Comfortable temperature", "It'll be hot"],
  shade: ["Shady for the heat", "Little shade"],
  air: ["Clean air", "Poor air quality"],
  wind: ["Calm", "Windy on exposed stretches"],
  mud: ["Dry trails", "Trails may be muddy"],
  wet: ["Dry roads", "The steep downhill may be slick"],
  daylight: ["Plenty of daylight", "You might finish after dark"],
};

// small line icons for each "Why this route" category (24x24, drawn with currentColor)
const WHY_ICONS: Record<string, string[]> = {
  "Distance": ["M8 19h7a3.5 3.5 0 0 0 0-7H9a3.5 3.5 0 0 1 0-7h7", "M6 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4z", "M18 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4z"],
  "Climbing": ["M3 20l6-10 4 6 3-4 5 8z"],
  "Soreness": ["M3 12h4l2.5-5 4 10 2.5-5H21"],
  "Energy & sleep": ["M13 2L4 14h7l-1 8 9-12h-7z"],
  "Surface": ["M12 3l9 5-9 5-9-5 9-5z", "M3 13l9 5 9-5"],
  "Scenery": ["M12 3l6 8h-3.5l4.5 6H5l4.5-6H6z", "M12 17v4"],
  "Roads & turns": ["M6 21V9a4 4 0 0 1 4-4h8", "M15 2l3 3-3 3", "M14 21v-6"],
  "Location": ["M12 21s-7-6.5-7-12a7 7 0 0 1 14 0c0 5.5-7 12-7 12z", "M12 11.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"],
  "Something new": ["M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6"],
  "Your ratings": ["M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3l-5.5 2.9 1-6.2L3 9.6l6.2-.9z"],
  "Run type & mood": ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M12 12.5a.5.5 0 1 0 0-1 .5.5 0 0 0 0 1z"],
  "Weather": ["M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"],
};

function WhyIcon({ title }: { title: string }) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
         strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {(WHY_ICONS[title] ?? []).map((d, n) => <path key={n} d={d} />)}
    </svg>
  );
}

const WHY_WORDS = ["", "Works against it", "A bit against it", "Okay", "Good", "Great"];

// One measurable fact per category, so two routes' breakdowns read differently
// even when their ratings match ("3.2 mi of 3", "410 ft up", "0.4 mi away").
function whyFact(title: string, rec: Recommendation): string | null {
  const mi = kmToMiles(rec.effective_distance_km ?? rec.distance_km);
  const ft = metersToFeet(rec.elevation_gain_m ?? 0);
  const pct = (x?: number | null) => (x == null ? null : Math.round(x * 100));
  const surface = rec.surface_type && rec.surface_type !== "unknown" ? SURFACE_LABELS[rec.surface_type] ?? rec.surface_type : null;
  switch (title) {
    case "Distance":
      return rec.target_km ? `${mi.toFixed(1)} of ${kmToMiles(rec.target_km).toFixed(1)} mi` : `${mi.toFixed(1)} mi`;
    case "Climbing":
      return `${Math.round(ft)} ft up · ${mi > 0 ? Math.round(ft / mi) : 0} ft/mi`;
    case "Soreness":
      return surface ? `${surface} surface` : null;
    case "Energy & sleep":
      return `${(rec.difficulty_label ?? rec.difficulty).replace(/^./, (c) => c.toUpperCase())} effort`;
    case "Surface":
      return surface;
    case "Scenery":
      return pct(rec.scenic_pct) != null ? `${pct(rec.scenic_pct)}% parks, trees or water` : null;
    case "Roads & turns": {
      const bits = [pct(rec.busy_pct) != null ? `${pct(rec.busy_pct)}% busy roads` : null,
                    rec.turns_per_km != null ? `${(rec.turns_per_km * 1.609).toFixed(1)} turns/mi` : null,
                    rec.freeway_crossings ? `${rec.freeway_crossings} freeway crossing${rec.freeway_crossings === 1 ? "" : "s"}` : null]
        .filter(Boolean);
      return bits.length ? bits.join(" · ") : null;
    }
    case "Location":
      if (rec.approach_km && rec.approach_km > 0) return `${kmToMiles(rec.approach_km).toFixed(1)} mi run to the start`;
      return rec.travel_km != null ? `${kmToMiles(rec.travel_km).toFixed(1)} mi away` : null;
    case "Something new":
      return rec.days_since_run == null ? "Never run" : rec.days_since_run === 0 ? "Ran it today"
        : `Last run ${rec.days_since_run} day${rec.days_since_run === 1 ? "" : "s"} ago`;
    case "Your ratings":
      return rec.your_rating != null ? `You rated it ${rec.your_rating.toFixed(1)}★` : null;
    case "Run type & mood":
      return rec.estimated_minutes ? `About ${rec.estimated_minutes} min` : null;
    case "Weather": {
      const bits = [rec.feels_like_f != null ? `Feels ${Math.round(rec.feels_like_f)}°F` : null,
                    pct(rec.shade_pct) != null ? `${pct(rec.shade_pct)}% shade` : null].filter(Boolean);
      return bits.length ? bits.join(" · ") : null;
    }
  }
  return null;
}

function whyGroups(breakdown: Record<string, number> | undefined) {
  const b = breakdown ?? {};
  return WHY_GROUPS.map((g) => {
    const items = g.keys.filter((k) => b[k] !== undefined && Math.abs(b[k]) >= 1).map((k) => [k, b[k]] as [string, number]);
    if (items.length === 0) return null;
    const sum = items.reduce((t, [, v]) => t + v, 0);
    const ratio = sum / g.full;
    const dots = sum <= -8 ? 1 : sum < 0 ? 2 : ratio < 0.25 ? 3 : ratio < 0.6 ? 4 : 5;
    // what mattered most, bad news first when the group came out negative
    const ordered = [...items].sort((x, y) => Math.abs(y[1]) - Math.abs(x[1]));
    const line = ordered.slice(0, 2)
      .filter(([, v], n) => n === 0 || Math.abs(v) >= 3)      // a second reason only if it mattered
      .map(([k, v]) => (WHY_PHRASES[k] ?? [k, k])[v >= 0 ? 0 : 1])
      .join(". ");
    return { title: g.title, dots, line: line + "." };
  }).filter((g): g is { title: string; dots: number; line: string } => g !== null);
}

const SURFACE_LABELS: Record<string, string> = {
  pavement: "Road",
  trail: "Trail",
  track: "Track",
  mixed: "Mixed",
};

function kmToMiles(km: number): number {
  return km * 0.621371;
}

function metersToFeet(m: number): number {
  return m * 3.28084;
}

function planInput(rec: Recommendation): PlanInput {
  return {
    format: rec.run_format, repeatCount: rec.repeat_count, routeKm: rec.distance_km,
    stemKm: rec.stem_km, approachKm: rec.approach_km, turnaroundKm: rec.turnaround_km,
  };
}

// Card actions, grouped by purpose: run it / log it / save it, then take it with you
function RecActions({ rec, saved, onSave, onLog }: {
  rec: Recommendation;
  saved: boolean;
  onSave: () => void;
  onLog: () => void;
}) {
  const { busy, handleFollow, handleGpx } = useRouteActions({
    routeId: rec.route_id,
    recommendationId: rec.recommendation_id,
    name: rec.route_name,
    loadPath: () => rec.path,
    format: rec.run_format,
    repeatCount: rec.repeat_count,
    surface: rec.surface_type,
    approachPath: rec.approach_path,
    // "close to home" = run there from where you are; 15/30/45 min = drive to the trailhead
    runFromHere: (rec.approach_km ?? 0) > 0,
    plan: planInput(rec),
    totalKm: rec.effective_distance_km ?? rec.distance_km,
  });
  const hasPath = rec.path.length > 1;
  return (
    <div className="rec-actions-v2">
      <div className="rec-main-actions">
        {hasPath && (
          <button className="rec-btn primary" onClick={handleFollow} disabled={busy !== null}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M8 5.5v13a1 1 0 001.5.86l10.5-6.5a1 1 0 000-1.72L9.5 4.64A1 1 0 008 5.5z" />
            </svg>
            {busy === "follow" ? "Loading..." : "Start route"}
          </button>
        )}
        <button className="rec-btn secondary" onClick={onLog}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
          Log this run
        </button>
        {rec.route_id && (
          <button
            className={`rec-btn ghost ${saved ? "saved" : ""}`}
            aria-pressed={saved}
            onClick={onSave}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill={saved ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 20s-7-4.4-7-10a4 4 0 017-2.6A4 4 0 0119 10c0 5.6-7 10-7 10z" />
            </svg>
            {saved ? "Saved" : "Save"}
          </button>
        )}
      </div>

      {hasPath && (
        <div className="rec-take">
          <span className="rec-take-label">Take it with you</span>
          <div className="rec-take-tiles">
            <button className="rec-tile" onClick={handleGpx} disabled={busy !== null}>
              <span className="rec-tile-icon" aria-hidden="true">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />
                </svg>
              </span>
              <span className="rec-tile-text">
                <strong>{busy === "gpx" ? "Preparing..." : "GPX file"}</strong>
                <small>For your watch or running app</small>
              </span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function RecommendationsPage() {
  const navigate = useNavigate();
  const userId = localStorage.getItem("user_id");
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openReasoning, setOpenReasoning] = useState<Record<number, boolean>>({});
  const [favoriteIds, setFavoriteIds] = useState<Set<string>>(new Set());
  const [conditions, setConditions] = useState<Conditions | null>(null);
  const [groupToday, setGroupToday] = useState<GroupMatch | null>(null);

  // load saved routes so the Save buttons show the right state
  useEffect(() => {
    if (!userId) return;
    fetch(`${API_URL}/favorites/${userId}`)
      .then((res) => (res.ok ? res.json() : []))
      .then((favs: { route_id: string }[]) => setFavoriteIds(new Set(favs.map((f) => f.route_id))))
      .catch(() => {});
  }, [userId]);

  // fetch straight away, since you usually land here right after checking in
  useEffect(() => {
    fetchRecommendations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function toggleFavorite(routeId: string) {
    const isSaved = favoriteIds.has(routeId);
    const res = isSaved
      ? await fetch(`${API_URL}/favorites/${userId}/${routeId}`, { method: "DELETE" })
      : await fetch(API_URL + "/favorites", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_id: userId, route_id: routeId }),
        });
    if (!res.ok) return;
    setFavoriteIds((prev) => {
      const next = new Set(prev);
      if (isSaved) next.delete(routeId);
      else next.add(routeId);
      return next;
    });
  }

  function toggleReasoning(i: number) {
    setOpenReasoning((prev) => ({ ...prev, [i]: !prev[i] }));
  }

  async function fetchRecommendations() {
    if (!userId) {
      setError("No user found. Please log in again.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      // plan from where they are right now; if location isn't allowed, the server uses home
      const here = await currentPosition();
      const where = here ? `?lat=${here[0].toFixed(5)}&lon=${here[1].toFixed(5)}` : "";
      const response = await fetch(`${API_URL}/recommendations/${userId}${where}`);
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        if (response.status === 404 && body?.detail === "No checkin for today") {
          throw new Error("checkin");
        }
        throw new Error(body?.detail ?? `Server responded with ${response.status}`);
      }
      const data = await response.json();
      setRecommendations(data);
      fetch(`${API_URL}/conditions/${userId}`)
        .then((res) => (res.ok ? res.json() : null))
        .then(setConditions)
        .catch(() => setConditions(null));
      fetch(`${API_URL}/groups/${userId}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((g) => setGroupToday(g?.today ?? null))
        .catch(() => setGroupToday(null));
      setOpenReasoning({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  const today = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  const count = recommendations.length;

  return (
    <div className="app recs-page">
      <header className="recs-intro">
        <div>
          <span className="ci-eyebrow">Today's routes · {today}</span>
          <h1>
            {count > 0
              ? <>{count === 1 ? "One route" : `${["", "One", "Two", "Three", "Four", "Five"][count] ?? count} routes`} picked for how you feel.</>
              : "Your routes for today."}
          </h1>
          <p>Ranked by how well each one fits your check-in. Open "Why this route" to see the reasoning.</p>
        </div>
        <button className="recs-refresh" onClick={fetchRecommendations} disabled={loading}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className={loading ? "spin" : ""}>
            <path d="M20 11a8 8 0 10-2.3 5.7M20 4v7h-7" />
          </svg>
          {loading ? "Scoring..." : "Refresh"}
        </button>
      </header>

      {loading && count === 0 && (
        <div className="recs-loading">
          <span className="recs-loading-trail" />
          <p>Reading your check-in and scoring routes...</p>
        </div>
      )}

      {error === "checkin" && (
        <div className="recs-empty">
          <h2>Check in first</h2>
          <p>Pathos picks routes based on how you feel today, so start with a quick check-in.</p>
          <button className="logged-primary" onClick={() => navigate("/checkin")}>Start today's check-in</button>
        </div>
      )}
      {error && error !== "checkin" && <p className="error">Error: {error}</p>}

      {conditions && count > 0 && (() => {
        const rt = conditions.run_time.replace("tomorrow_", "");
        const base = { now: "Right now", morning: "morning", midday: "midday", evening: "evening" }[rt] ?? "today";
        const when = conditions.run_time === "now"
          ? "Right now"
          : conditions.is_tomorrow
            ? `Tomorrow ${base}`
            : `This ${base}`;
        const nowFeels = conditions.now_feels_like_f ?? conditions.now_temp_f;
        return (
          <section className="conditions">
            <div className="conditions-head">
              <span className="conditions-when">
                {when} near home
                {conditions.run_time !== "now" && nowFeels != null && (
                  <span className="conditions-now"> · {Math.round(nowFeels)}°F right now</span>
                )}
              </span>
              <p>{conditionsVerdict(conditions)}</p>
            </div>
            <div className="cond-stats">
              {condStats(conditions).map((st) => (
                <div className={`cond-stat ${st.tone === TONE ? "" : "alert"}`} key={st.label}
                     style={{ "--tone": st.tone } as React.CSSProperties}>
                  <span className="cond-stat-icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2"
                         strokeLinecap="round" strokeLinejoin="round">
                      {COND_ICONS[st.icon].map((d, n) => <path key={n} d={d} />)}
                    </svg>
                  </span>
                  <span className="cond-stat-text">
                    <span className="cond-stat-num">{st.value}{st.unit && <small>{st.unit}</small>}</span>
                    <span className="cond-stat-label">{st.label}</span>
                  </span>
                </div>
              ))}
            </div>
            {(conditions.heat_cut_pct || conditions.cooler_option) && (
              <ul className="cond-notes">
                {conditions.heat_cut_pct ? (
                  <li className="warm">
                    <span className="cond-note-icon" aria-hidden="true">
                      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 14.8V4a2 2 0 0 0-4 0v10.8a4 4 0 1 0 4 0z" /></svg>
                    </span>
                    <span>Picks run about <b>{conditions.heat_cut_pct}% shorter</b> than usual, and shady routes get a boost.</span>
                  </li>
                ) : null}
                {conditions.cooler_option && (
                  <li>
                    <span className="cond-note-icon" aria-hidden="true">
                      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
                    </span>
                    <span>
                      <b>{conditions.cooler_option.cooler_by_f}°F cooler {conditions.cooler_option.label}</b>
                      {conditions.cooler_option.clock && ` around ${conditions.cooler_option.clock}`}, feeling like {conditions.cooler_option.feels_like_f}°F.
                    </span>
                    <Link to="/checkin" className="cond-note-action">Change run time</Link>
                  </li>
                )}
              </ul>
            )}
            <span className="cond-credit">
              <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Weather: Open-Meteo</a>
              {" · "}
              <a href="https://registry.opendata.aws/dataforgood-fb-forestsv2" target="_blank" rel="noreferrer">Tree canopy: Meta &amp; WRI (CC BY 4.0)</a>
            </span>
          </section>
        );
      })()}

      <div className="recs-list">
        {recommendations.map((rec, i) => {
          const miles = kmToMiles(rec.effective_distance_km ?? rec.distance_km);
          const surface = rec.surface_type && rec.surface_type !== "unknown" ? SURFACE_LABELS[rec.surface_type] ?? rec.surface_type : null;
          const saved = rec.route_id ? favoriteIds.has(rec.route_id) : false;
          const headline = rec.notice ? `${rec.notice}.` : buildHeadline(rec.score_breakdown, rec.reasons[0]);
          return (
            <article key={i} className={`rec-card ${i === 0 ? "top" : ""}`}>
              <div className="rec-map-wrap">
                {rec.path.length > 1 && (
                  <MapContainer
 center={rec.path[Math.floor(rec.path.length / 2)]}
                    zoom={15}
                    zoomSnap={0.25}
                    scrollWheelZoom={false}
                    zoomControl={false}
                    
                    className="rec-map"
                  >
                    <MapResizer path={fullLine(rec)} />
                    <TileLayer
                      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                    />
                    {/* one continuous line: from you (or home) along the streets to the start, then the route */}
                    <Polyline positions={fullLine(rec)} pathOptions={{ color: "#FFFFFF", weight: 9, opacity: 0.9 }} />
                    <Polyline positions={fullLine(rec)} pathOptions={{ color: "#2563EB", weight: 4.5, opacity: 1 }} />
                    <CircleMarker
                      center={fullLine(rec)[0]}
                      radius={7}
                      pathOptions={{ color: "#FFFFFF", weight: 3, fillColor: "#1D4ED8", fillOpacity: 1 }}
                    />
                  </MapContainer>
                )}
                <span className="rec-rank">{String(i + 1).padStart(2, "0")}</span>
                {i === 0 && <span className="rec-best">Best match today</span>}
              </div>

              <div className="rec-body">
                <div className="rec-title-row">
                  <h2>{rec.route_name}</h2>
                  {rec.needs_drive && <span className="rec-drive-pill">Needs a drive</span>}
                  <span className={`rec-match-pill ${matchLabel(rec.score, rec.perfect_points).tone}`}
                        title={`${matchPct(rec.score, rec.perfect_points)}% match with your check-in`}>
                    {matchLabel(rec.score, rec.perfect_points).text}
                  </span>
                </div>

                {headline && <p className="rec-why">{headline}</p>}
                {(rec.score_breakdown?.mud ?? 0) <= -1 ? (
                  <p className="rec-alert">Recent rain: {rec.surface_type === "trail" ? "the trail" : "the dirt sections"} may be wet or muddy. Watch your footing on the downhills.</p>
                ) : (rec.score_breakdown?.wet ?? 0) <= -1 && (
                  <p className="rec-alert">Recent rain: the steep downhill may be slick. Shorten your stride and take it easy going down.</p>
                )}

                <div className="rec-splits">
                  <div>
                    <span className="rec-split-value">{miles.toFixed(1)}<small>mi</small></span>
                    <span className="rec-split-label">
                      {/* say how the distance is made up, so 3 laps of a 3.3 mi loop doesn't read as one 9.8 mi route */}
                      {rec.run_format === "repeat" && (rec.repeat_count ?? 1) > 1
                        ? `${rec.repeat_count} laps`
                        : rec.run_format === "out_and_back"
                          ? "Out & back"
                          : (rec.approach_km ?? 0) > 0
                            ? "From you"
                            : "Distance"}
                    </span>
                  </div>
                  {rec.estimated_minutes != null && (
                    <div>
                      <span className="rec-split-value">{rec.estimated_minutes}<small>min</small></span>
                      <span className="rec-split-label">Est. time</span>
                    </div>
                  )}
                  <div>
                    <span className="rec-split-value">{metersToFeet(rec.elevation_gain_m).toFixed(0)}<small>ft</small></span>
                    <span className="rec-split-label">Climb</span>
                  </div>
                  <div>
                    <span className={`rec-difficulty ${rec.difficulty_label === "Long, gentle" ? "moderate long" : rec.difficulty}`}>
                      <span className="rec-difficulty-bars" aria-hidden="true">
                        <i /><i /><i />
                      </span>
                      {rec.difficulty_label ?? rec.difficulty}
                    </span>
                    <span className="rec-split-label">{surface ?? "Effort"}</span>
                  </div>
                </div>

                {runPlan(planInput(rec)).length > 0 && (
                  <ol className="rec-plan" aria-label="How to run it">
                    {runPlan(planInput(rec)).map((step, i) => (
                      <Fragment key={i}>
                        {i > 0 && <li className="rec-plan-arrow" aria-hidden="true">→</li>}
                        <li>{step.charAt(0).toUpperCase() + step.slice(1)}</li>
                      </Fragment>
                    ))}
                  </ol>
                )}

                <RecActions
                  rec={rec}
                  saved={saved}
                  onSave={() => rec.route_id && toggleFavorite(rec.route_id)}
                  onLog={() => navigate("/log-run", { state: { routeId: rec.route_id, routeName: rec.route_name, recommendationId: rec.recommendation_id } })}
                />

                <button
                  className={`rec-why-row ${openReasoning[i] ? "open" : ""}`}
                  aria-expanded={!!openReasoning[i]}
                  onClick={() => toggleReasoning(i)}
                >
                  <span>Why this route</span>
                  <span className="rec-why-hint">{openReasoning[i] ? "Hide" : "See what went into the pick"}</span>
                  <span className={`chevron ${openReasoning[i] ? "open" : ""}`}>▾</span>
                </button>

                {openReasoning[i] && (() => {
                  const groups = whyGroups(rec.score_breakdown);
                  const good = groups.filter((g) => g.dots >= 3).sort((x, y) => y.dots - x.dots);
                  const watch = groups.filter((g) => g.dots <= 2).sort((x, y) => x.dots - y.dots);
                  const item = (g: { title: string; dots: number; line: string }) => (
                    <li className={`why-item ${g.dots <= 2 ? "watch" : "good"}`} key={g.title}>
                      <span className="why-icon"><WhyIcon title={g.title} /></span>
                      <span className="why-text">
                        <span className="why-head">
                          <span className="why-title">
                            {g.title}
                            {whyFact(g.title, rec) && <span className="why-fact">{whyFact(g.title, rec)}</span>}
                          </span>
                          <span className="why-dots" role="img" aria-label={`${WHY_WORDS[g.dots]} (${g.dots} of 5)`}>
                            {[1, 2, 3, 4, 5].map((n) => <span key={n} className={n <= g.dots ? "on" : ""} />)}
                          </span>
                        </span>
                        <span className="why-line">{g.line}</span>
                      </span>
                    </li>
                  );
                  return (
                    <div className="rec-reasoning why-panel">
                      {good.length > 0 && (
                        <section>
                          <h4 className="why-section">Working for it</h4>
                          <ul className="why-list">{good.map(item)}</ul>
                        </section>
                      )}
                      {watch.length > 0 && (
                        <section>
                          <h4 className="why-section">Worth knowing</h4>
                          <ul className="why-list">{watch.map(item)}</ul>
                        </section>
                      )}
                    </div>
                  );
                })()}
              </div>
            </article>
          );
        })}
      </div>

      {groupToday && count > 0 && (
        <Link to="/groups" className="group-suggest">
          <span className="group-suggest-icon" aria-hidden="true">👟</span>
          <span className="group-suggest-text">
            <span className="group-suggest-label">Rather run with a group?</span>
            <strong>
              {groupToday.club_name} · {formatMeetTime(groupToday.starts_at)} · {sessionTitle(groupToday)}
            </strong>
            <small>{groupToday.reasons[0]}</small>
          </span>
          <span className="group-suggest-fit">
            <b>{Math.round(groupToday.fit)}</b>fit
          </span>
        </Link>
      )}

    </div>
  );
}

export default RecommendationsPage;
