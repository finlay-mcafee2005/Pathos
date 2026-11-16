// What a runner can rank at signup (and later in Settings), most important first.
// Keys match PRIORITY_PARTS in backend/app/scoring/engine.py.
export const PRIORITIES = [
  { key: "safety", icon: "🚦", title: "Safety", sub: "Lights and crosswalks, few busy crossings" },
  { key: "scenery", icon: "🌳", title: "Scenery", sub: "Parks, views, trees, water" },
  { key: "distance", icon: "📏", title: "Hitting my distance", sub: "Close to the miles I planned" },
  { key: "surface", icon: "👟", title: "Surface", sub: "Trail or road, the footing I like" },
  { key: "hills", icon: "⛰️", title: "Hills", sub: "The right amount of climbing" },
  { key: "shape", icon: "🔁", title: "Route shape", sub: "Clean loops, few turns and stops" },
  { key: "location", icon: "📍", title: "Close to home", sub: "Easy to get to, little or no driving" },
] as const;

export type PriorityKey = (typeof PRIORITIES)[number]["key"];
export const DEFAULT_ORDER: string[] = PRIORITIES.map((p) => p.key);

/** A saved ranking with any missing keys added at the end, in the default order. */
export function fullOrder(saved: string[] | null | undefined): string[] {
  const known = (saved ?? []).filter((k) => DEFAULT_ORDER.includes(k));
  return [...known, ...DEFAULT_ORDER.filter((k) => !known.includes(k))];
}
