import { useEffect, useMemo, useRef, useState } from "react";
import { API_URL } from "../utils/format";

// Places they usually run: search LA spots, add them as rows, and say how often they go.
export type Spot = { key: string; label: string; often: boolean };
type CatalogSpot = { key: string; label: string; kind: string; popular: boolean };

const KIND_ICON: Record<string, string> = { park: "🌳", trail: "⛰️", path: "🛤️", beach: "🌊", streets: "🏘️" };
let catalogCache: CatalogSpot[] | null = null;

type Props = { value: Spot[]; onChange: (spots: Spot[]) => void };

function UsualSpots({ value, onChange }: Props) {
  const [catalog, setCatalog] = useState<CatalogSpot[]>(catalogCache ?? []);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (catalogCache) return;
    fetch(`${API_URL}/spots`).then((r) => (r.ok ? r.json() : [])).then((list: CatalogSpot[]) => {
      catalogCache = list;
      setCatalog(list);
    }).catch(() => {});
  }, []);

  // close the dropdown when clicking elsewhere
  useEffect(() => {
    const onDown = (e: MouseEvent) => { if (!boxRef.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  const chosen = new Set(value.map((s) => s.key));
  const kindOf = Object.fromEntries(catalog.map((c) => [c.key, c.kind]));
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return catalog
      .filter((c) => !chosen.has(c.key) && c.label.toLowerCase().includes(q))
      .sort((a, b) => Number(!a.label.toLowerCase().startsWith(q)) - Number(!b.label.toLowerCase().startsWith(q)))
      .slice(0, 6);
  }, [query, catalog, value]);   // eslint-disable-line react-hooks/exhaustive-deps
  const popular = catalog.filter((c) => c.popular && !chosen.has(c.key));

  function add(c: CatalogSpot) {
    onChange([...value, { key: c.key, label: c.label, often: false }]);
    setQuery("");
    setActive(0);
  }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!matches.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, matches.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); add(matches[active]); }
    else if (e.key === "Escape") setOpen(false);
  }

  return (
    <div className="us-wrap">
      <div className="us-search" ref={boxRef}>
        <svg className="us-search-icon" viewBox="0 0 20 20" aria-hidden="true">
          <circle cx="9" cy="9" r="6" /><path d="M13.5 13.5L17 17" />
        </svg>
        <input
          value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(0); }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKey}
          placeholder="Search parks, trails, neighborhoods…"
          aria-label="Search places you run"
        />
        {open && query.trim() && (
          <ul className="us-results" role="listbox">
            {matches.length ? matches.map((c, i) => (
              <li key={c.key} role="option" aria-selected={i === active}
                  className={i === active ? "on" : ""}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={(e) => { e.preventDefault(); add(c); }}>
                <span aria-hidden="true">{KIND_ICON[c.kind] ?? "📍"}</span>
                {c.label}
                <small>{c.kind === "streets" ? "Neighborhood" : c.kind[0].toUpperCase() + c.kind.slice(1)}</small>
              </li>
            )) : <li className="us-empty">No match. Try a nearby park or neighborhood.</li>}
          </ul>
        )}
      </div>

      {popular.length > 0 && (
        <div className="us-popular">
          <span>Popular</span>
          {popular.map((c) => (
            <button key={c.key} type="button" onClick={() => add(c)}>+ {c.label}</button>
          ))}
        </div>
      )}

      {value.length > 0 && (
        <ul className="us-chosen">
          {value.map((s) => (
            <li key={s.key}>
              <span className="us-icon" aria-hidden="true">{KIND_ICON[kindOf[s.key]] ?? "📍"}</span>
              <strong>{s.label}</strong>
              <span className="us-freq" role="group" aria-label={`How often you run ${s.label}`}>
                {[false, true].map((often) => (
                  <button key={String(often)} type="button" className={s.often === often ? "on" : ""}
                          onClick={() => onChange(value.map((v) => (v.key === s.key ? { ...v, often } : v)))}>
                    {often ? "All the time" : "Sometimes"}
                  </button>
                ))}
              </span>
              <button type="button" className="us-remove" aria-label={`Remove ${s.label}`}
                      onClick={() => onChange(value.filter((v) => v.key !== s.key))}>✕</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default UsualSpots;
