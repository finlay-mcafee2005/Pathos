import { useRef, useState } from "react";
import { PRIORITIES } from "../utils/priorities";

// Drag to rank (mouse or touch, by the ≡ handle), or use the arrows. Most important on top.
type Props = { order: string[]; onChange: (order: string[]) => void };

function PriorityRanker({ order, onChange }: Props) {
  const listRef = useRef<HTMLOListElement>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const info = Object.fromEntries(PRIORITIES.map((p) => [p.key, p]));

  function move(from: number, to: number) {
    if (to < 0 || to >= order.length || from === to) return;
    const next = [...order];
    const [k] = next.splice(from, 1);
    next.splice(to, 0, k);
    onChange(next);
  }

  function startDrag(e: React.PointerEvent, key: string) {
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    setDragging(key);
  }

  function onDrag(e: React.PointerEvent) {
    if (!dragging || !listRef.current) return;
    const items = Array.from(listRef.current.children) as HTMLElement[];
    const from = order.indexOf(dragging);
    const mid = (el: HTMLElement) => { const r = el.getBoundingClientRect(); return r.top + r.height / 2; };
    // one slot at a time: past the middle of the item above or below, swap with it
    if (from > 0 && e.clientY < mid(items[from - 1])) move(from, from - 1);
    else if (from < items.length - 1 && e.clientY > mid(items[from + 1])) move(from, from + 1);
  }

  return (
    <ol className={`pr-list ${dragging ? "is-dragging" : ""}`} ref={listRef}>
      {order.map((key, i) => {
        const p = info[key];
        if (!p) return null;
        return (
          <li key={key} className={`pr-item ${dragging === key ? "dragging" : ""}`}>
            <span
              className="pr-handle"
              aria-hidden="true"
              onPointerDown={(e) => startDrag(e, key)}
              onPointerMove={onDrag}
              onPointerUp={() => setDragging(null)}
              onPointerCancel={() => setDragging(null)}
            >≡</span>
            <span className="pr-rank">{i + 1}</span>
            <span className="pr-icon" aria-hidden="true">{p.icon}</span>
            <span className="pr-text">
              <strong>{p.title}</strong>
              <small>{p.sub}</small>
            </span>
            <span className="pr-arrows">
              <button type="button" aria-label={`Move ${p.title} up`} disabled={i === 0} onClick={() => move(i, i - 1)}>▲</button>
              <button type="button" aria-label={`Move ${p.title} down`} disabled={i === order.length - 1} onClick={() => move(i, i + 1)}>▼</button>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export default PriorityRanker;
