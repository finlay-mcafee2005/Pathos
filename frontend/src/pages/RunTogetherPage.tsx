import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { MapContainer, TileLayer, Polyline, CircleMarker, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { API_URL, kmToMiles, metersToFeet, SURFACE_LABELS } from "../utils/format";
import { useRouteActions } from "../components/RouteExportButtons";

type GroupMember = { user_id: string; name: string; checked_in_today: boolean; is_owner: boolean };
type RunGroup = { id: string; name: string; join_code: string; meet_label: string | null; members: GroupMember[] };
type MemberFit = { name: string; fit: "Great" | "Good" | "Okay"; reason: string | null; extra_laps: number; start_mi: number };
type GroupPick = {
  route_id: string;
  route_name: string;
  distance_km: number;
  effective_distance_km: number;
  run_format: string;
  repeat_count: number;
  elevation_gain_m: number;
  surface_type: string;
  difficulty: string;
  minutes_range: [number, number];
  members: MemberFit[];
  path: [number, number][];
};
type Picks = { shared_distance_mi: number; waiting_on: string[]; picks: GroupPick[] };

function FitRoute({ path }: { path: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    // the card may still be laying out when the map mounts: re-measure a few
    // times and whenever the box changes size, so the street tiles load
    const fit = () => {
      map.invalidateSize();
      map.fitBounds(L.latLngBounds(path), { padding: [24, 24] });
    };
    const timers = [50, 300, 800].map((ms) => setTimeout(fit, ms));
    const ro = new ResizeObserver(fit);
    ro.observe(map.getContainer());
    return () => {
      timers.forEach(clearTimeout);
      ro.disconnect();
    };
  }, [map, path]);
  return null;
}

async function post(url: string, body: unknown, method = "POST") {
  const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.detail ?? `Server responded with ${res.status}`);
  return data;
}

function PickCard({ pick, rank }: { pick: GroupPick; rank: number }) {
  const { busy, handleFollow, handleMaps } = useRouteActions({
    routeId: pick.route_id,
    name: pick.route_name,
    loadPath: () => pick.path,
    surface: pick.surface_type,
  });
  const miles = kmToMiles(pick.effective_distance_km);
  const [lo, hi] = pick.minutes_range;
  const addOns = pick.members.filter((m) => m.extra_laps > 0);
  const format = pick.run_format === "repeat" ? `${pick.repeat_count} laps`
    : pick.run_format === "out_and_back" ? "Out & back" : "Loop";
  return (
    <article className={`rt-pick ${rank === 1 ? "top" : ""}`}>
      <div className="rt-map">
        {pick.path.length > 1 && (
          <MapContainer center={pick.path[0]} zoom={14} className="rt-map-inner" zoomControl={false}
            attributionControl={false} dragging={false} scrollWheelZoom={false} doubleClickZoom={false}
            touchZoom={false} keyboard={false} boxZoom={false}>
            <FitRoute path={pick.path} />
            <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            <Polyline positions={pick.path} pathOptions={{ color: "#FFFFFF", weight: 8, opacity: 0.95 }} />
            <Polyline positions={pick.path} pathOptions={{ color: "#2563EB", weight: 4, opacity: 1 }} />
            <CircleMarker center={pick.path[0]} radius={6}
              pathOptions={{ color: "#FFFFFF", weight: 3, fillColor: "#1D4ED8", fillOpacity: 1 }} />
          </MapContainer>
        )}
        <span className="rt-rank">{String(rank).padStart(2, "0")}</span>
        {rank === 1 && <span className="rt-best">Best for the group</span>}
      </div>

      <div className="rt-body">
        <h3>{pick.route_name}</h3>
        <div className="rt-stats">
          <div><b>{miles.toFixed(1)}</b><small>mi</small><span>{format}</span></div>
          <div><b>{Math.round(metersToFeet(pick.elevation_gain_m))}</b><small>ft</small><span>Climb</span></div>
          <div><b>{lo === hi ? lo : `${lo}–${hi}`}</b><small>min</small><span>Time</span></div>
          <div><b className="rt-surface">{SURFACE_LABELS[pick.surface_type] ?? pick.surface_type}</b><span>Surface</span></div>
        </div>

        <div className="rt-fits">
          {pick.members.map((m) => (
            <div key={m.name} className={`rt-fit fit-${m.fit.toLowerCase()}`} title={m.reason ?? undefined}>
              <span className="rt-fit-avatar">{m.name.charAt(0).toUpperCase()}</span>
              <span className="rt-fit-text">
                <span className="rt-fit-top"><b>{m.name}</b><em>{m.fit}</em></span>
                <span className="rt-fit-why">{m.reason ?? "Solid all-round fit"} · {m.start_mi} mi away</span>
              </span>
            </div>
          ))}
        </div>

        {addOns.length > 0 && pick.run_format !== "out_and_back" && (
          <p className="rt-addon">
            <span aria-hidden="true">+</span>
            {addOns.map((m) => `${m.name} can add ${m.extra_laps} lap${m.extra_laps > 1 ? "s" : ""}`).join(" · ")}
            <small>{kmToMiles(pick.distance_km).toFixed(1)} mi per lap</small>
          </p>
        )}

        <div className="rt-actions">
          <button className="rec-btn primary" onClick={handleFollow} disabled={busy !== null}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M8 5.5v13a1 1 0 001.5.86l10.5-6.5a1 1 0 000-1.72L9.5 4.64A1 1 0 008 5.5z" />
            </svg>
            {busy === "follow" ? "Loading..." : "Start route"}
          </button>
          <button className="rec-btn secondary" onClick={handleMaps} disabled={busy !== null}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
                 strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 11l18-8-8 18-2-8-8-2z" /></svg>
            Directions to start
          </button>
        </div>
      </div>
    </article>
  );
}

function RunTogetherPage() {
  const userId = localStorage.getItem("user_id");
  const [groups, setGroups] = useState<RunGroup[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [code, setCode] = useState("");
  const [spot, setSpot] = useState("");
  const [editingSpot, setEditingSpot] = useState(false);
  const [picks, setPicks] = useState<Picks | null>(null);
  const [picking, setPicking] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showSetup, setShowSetup] = useState<"" | "create" | "join">("");

  const group = groups.find((g) => g.id === activeId) ?? null;
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const wantGroup = searchParams.get("group");
  const autoRun = useRef(searchParams.get("auto") === "1");
  const me = group?.members.find((m) => m.user_id === userId);

  function load(selectId?: string) {
    fetch(`${API_URL}/run-groups/mine/${userId}`)
      .then((r) => r.json())
      .then((gs: RunGroup[]) => {
        setGroups(gs);
        setActiveId((cur) => selectId
          ?? (cur && gs.some((g) => g.id === cur) ? cur
            : wantGroup && gs.some((g) => g.id === wantGroup) ? wantGroup : gs[0]?.id ?? null));
      })
      .catch(() => setError("Couldn't load your groups."))
      .finally(() => setLoading(false));
  }
  useEffect(load, [userId]);
  useEffect(() => setPicks(null), [activeId]);

  async function act(fn: () => Promise<RunGroup | void>) {
    setError(null);
    try {
      const g = await fn();
      load(g && "id" in g ? g.id : undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    }
  }

  async function getPicks() {
    if (!group) return;
    setPicking(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/run-groups/${group.id}/recommendations?user_id=${userId}`);
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail ?? `Server responded with ${res.status}`);
      setPicks(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setPicking(false);
    }
  }

  const checkedIn = group?.members.filter((m) => m.checked_in_today).length ?? 0;

  // arriving straight from check-in: find the group's route right away
  useEffect(() => {
    if (autoRun.current && group && group.id === wantGroup && me?.checked_in_today) {
      autoRun.current = false;
      getPicks();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group, me?.checked_in_today]);

  const createForm = (
    <form className="rt-setup-card" onSubmit={(e) => {
      e.preventDefault();
      act(() => post(`${API_URL}/run-groups`, { user_id: userId, name: newName }));
      setNewName(""); setShowSetup("");
    }}>
      <span className="rt-setup-icon" aria-hidden="true">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
      </span>
      <span className="rt-setup-title">Start a group</span>
      <span className="rt-setup-sub">Name it, then share the code with your running friends.</span>
      <div className="rt-inline">
        <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Oxy track crew" aria-label="Group name" />
        <button type="submit" className="rec-btn primary">Create</button>
      </div>
    </form>
  );
  const joinForm = (
    <form className="rt-setup-card" onSubmit={(e) => {
      e.preventDefault();
      if (code.trim()) act(() => post(`${API_URL}/run-groups/join`, { user_id: userId, code }));
      setCode(""); setShowSetup("");
    }}>
      <span className="rt-setup-icon" aria-hidden="true">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4M10 17l5-5-5-5M15 12H3" /></svg>
      </span>
      <span className="rt-setup-title">Join a group</span>
      <span className="rt-setup-sub">Got a 6-letter code from a friend? Enter it here.</span>
      <div className="rt-inline">
        <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="ABC123" maxLength={6} aria-label="Group code" className="rt-code-input" />
        <button type="submit" className="rec-btn secondary">Join</button>
      </div>
    </form>
  );
  const pct = group ? Math.round((checkedIn / Math.max(1, group.members.length)) * 100) : 0;

  return (
    <div className="app rt-page">
      <header className="ci-intro rt-intro">
        <div>
          <span className="ci-eyebrow">Run together</span>
          <h1>One route that works for everyone.</h1>
          <p>Everyone checks in on their own phone. Pathos finds a route that fits the whole group and goes easy on anyone who's sore or tired.</p>
        </div>
        {groups.length > 0 && (
          <div className="rt-intro-actions">
            <button className={`rt-chip ${showSetup === "create" ? "on" : ""}`} onClick={() => setShowSetup(showSetup === "create" ? "" : "create")}>+ New group</button>
            <button className={`rt-chip ${showSetup === "join" ? "on" : ""}`} onClick={() => setShowSetup(showSetup === "join" ? "" : "join")}>Join with code</button>
          </div>
        )}
      </header>

      {error && <p className="error">{error}</p>}
      {loading && <p className="empty-state">Loading...</p>}

      {!loading && groups.length === 0 && (
        <>
          <ol className="rt-how">
            <li><b>1</b><span><strong>Make a group</strong>Share its code with the friends you run with.</span></li>
            <li><b>2</b><span><strong>Everyone checks in</strong>Each runner says how they feel, on their own phone.</span></li>
            <li><b>3</b><span><strong>Get one route</strong>Pathos picks a run that suits the whole group.</span></li>
          </ol>
          <section className="rt-setup">{createForm}{joinForm}</section>
        </>
      )}
      {groups.length > 0 && showSetup && (
        <section className="rt-setup single">{showSetup === "create" ? createForm : joinForm}</section>
      )}

      {groups.length > 1 && (
        <div className="rt-tabs">
          {groups.map((g) => (
            <button key={g.id} className={g.id === activeId ? "on" : ""} onClick={() => setActiveId(g.id)}>{g.name}</button>
          ))}
        </div>
      )}

      {group && (
        <section className="rt-group">
          <div className="rt-band">
            <div className="rt-band-main">
              <h2>{group.name}</h2>
              <div className="rt-avatars">
                {group.members.map((m) => (
                  <span key={m.user_id} className={`rt-av ${m.checked_in_today ? "in" : ""}`} title={`${m.name}: ${m.checked_in_today ? "checked in" : "not checked in yet"}`}>
                    {m.name.charAt(0).toUpperCase()}
                  </span>
                ))}
                <span className="rt-band-sub">{checkedIn} of {group.members.length} checked in today</span>
              </div>
            </div>
            <div className="rt-ring" style={{ ["--pct" as string]: `${pct}%` }} aria-label={`${pct}% checked in`}>
              <span>{checkedIn}/{group.members.length}</span>
            </div>
            <button
              className="rt-code"
              onClick={() => { navigator.clipboard?.writeText(group.join_code); setCopied(true); setTimeout(() => setCopied(false), 1500); }}
              title="Copy the code to share"
            >
              <span>Invite code</span><b>{group.join_code}</b><small>{copied ? "Copied!" : "Tap to copy"}</small>
            </button>
          </div>

          <div className="rt-panel">
            <ul className="rt-members">
              {group.members.map((m) => (
                <li key={m.user_id} className={m.checked_in_today ? "in" : ""}>
                  <span className="rt-avatar">{m.name.charAt(0).toUpperCase()}</span>
                  <span className="rt-member-name">{m.name}{m.user_id === userId ? " (you)" : ""}{m.is_owner && <small>Organizer</small>}</span>
                  <span className="rt-status">{m.checked_in_today ? "✓ Ready" : "Waiting"}</span>
                </li>
              ))}
            </ul>

            {me && !me.checked_in_today && (
              <div className="rt-checkin-nudge">
                <span><b>You haven't checked in yet.</b> Your check-in is what makes the route fit you too.</span>
                <button className="rec-btn primary" onClick={() => navigate(`/checkin?group=${group.id}`)}>Check in for this run</button>
              </div>
            )}

            <div className="rt-start">
              <span className="rt-label">Start from</span>
              <div className="rt-seg">
                <button className={!group.meet_label && !editingSpot ? "on" : ""}
                  onClick={() => {
                    setEditingSpot(false);
                    if (group.meet_label) act(() => post(`${API_URL}/run-groups/${group.id}/meeting-spot`, { user_id: userId, address: null }, "PUT"));
                  }}>
                  Near everyone
                </button>
                <button className={group.meet_label || editingSpot ? "on" : ""} onClick={() => { setEditingSpot(true); setSpot(""); }}>
                  Meeting spot
                </button>
              </div>
              {editingSpot ? (
                <form className="rt-inline rt-spot-form" onSubmit={(e) => { e.preventDefault(); act(async () => { const g = await post(`${API_URL}/run-groups/${group.id}/meeting-spot`, { user_id: userId, address: spot }, "PUT"); setEditingSpot(false); return g; }); }}>
                  <input value={spot} onChange={(e) => setSpot(e.target.value)} placeholder="e.g. Occidental College track" autoFocus aria-label="Meeting spot" />
                  <button type="submit" className="rec-btn primary">Save</button>
                  <button type="button" className="rt-link" onClick={() => setEditingSpot(false)}>Cancel</button>
                </form>
              ) : (
                <span className="rt-start-value">
                  {group.meet_label ? <>📍 {group.meet_label}</> : "Routes start within everyone's travel limit from home"}
                </span>
              )}
            </div>

            <button className="rt-go-btn" onClick={getPicks} disabled={picking || checkedIn === 0}>
              {picking ? "Finding your route..." : checkedIn === 0 ? "Waiting for check-ins" : "Find our route"}
              {!picking && checkedIn > 0 && <span aria-hidden="true">→</span>}
            </button>
            <button className="rt-leave" onClick={() => act(() => post(`${API_URL}/run-groups/${group.id}/leave`, { user_id: userId }))}>Leave this group</button>
          </div>
        </section>
      )}

      {picks && (
        <section className="rt-results">
          <div className="rt-summary">
            <div>
              <span className="rt-label light">Today's shared run</span>
              <strong><b>{picks.shared_distance_mi}</b> mi</strong>
              <p>Set by whoever needs the easiest day. Fresher runners get add-on laps where they fit.</p>
            </div>
            {picks.waiting_on.length > 0 && (
              <span className="rt-waiting">Not counted yet: {picks.waiting_on.join(", ")}</span>
            )}
          </div>
          {picks.picks.map((p, i) => <PickCard key={p.route_id} pick={p} rank={i + 1} />)}
        </section>
      )}
    </div>
  );
}

export default RunTogetherPage;
