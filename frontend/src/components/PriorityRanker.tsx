import { useRef, useState } from "react";
import { PRIORITIES } from "../utils/priorities";

// Drag any row up or down (mouse or touch) to rank it; the row follows the pointer and the
// others slide out of the way. Most important on top. Keyboard: focus a row, arrow keys move it.
type Props = { order: string[]; onChange: (order: string[]) => void };

type Drag = { key: string; pointerId: number; lastY: number; offset: number };

function PriorityRanker({ order, onChange }: Props) {
  const listRef = useRef<HTMLOListElement>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const info = Object.fromEntries(PRIORITIES.map((p) => [p.key, p]));

  function moved(from: number, to: number) {
    const next = [...order];
    const [k] = next.splice(from, 1);
    next.splice(to, 0, k);
    return next;
  }

  function onPointerDown(e: React.PointerEvent<HTMLLIElement>, key: string) {
    if (e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setDrag({ key, pointerId: e.pointerId, lastY: e.clientY, offset: 0 });
  }

  function onPointerMove(e: React.PointerEvent<HTMLLIElement>) {
    if (!drag || e.pointerId !== drag.pointerId || !listRef.current) return;
    e.preventDefault();
    let offset = drag.offset + (e.clientY - drag.lastY);
    const items = Array.from(listRef.current.children) as HTMLElement[];
    const from = order.indexOf(drag.key);
    const gap = 8;                                       // matches .pr-list gap
    let next = order;
    // passed half of the row above or below: swap, and keep the row under the pointer
    if (from > 0 && offset < -(items[from - 1].offsetHeight + gap) / 2) {
      offset += items[from - 1].offsetHeight + gap;
      next = moved(from, from - 1);
    } else if (from < order.length - 1 && offset > (items[from + 1].offsetHeight + gap) / 2) {
      offset -= items[from + 1].offsetHeight + gap;
      next = moved(from, from + 1);
    }
    setDrag({ ...drag, lastY: e.clientY, offset });
    if (next !== order) onChange(next);
  }

  function endDrag() {
    setDrag(null);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLLIElement>, i: number) {
    const to = e.key === "ArrowUp" ? i - 1 : e.key === "ArrowDown" ? i + 1 : null;
    if (to === null || to < 0 || to >= order.length) return;
    e.preventDefault();
    onChange(moved(i, to));
    // keep focus on the row that moved
    requestAnimationFrame(() => (listRef.current?.children[to] as HTMLElement | undefined)?.focus());
  }

  return (
    <ol className={`pr-list ${drag ? "is-dragging" : ""}`} ref={listRef}>
      {order.map((key, i) => {
        const p = info[key];
        if (!p) return null;
        const isDragged = drag?.key === key;
        return (
          <li
            key={key}
            className={`pr-item ${isDragged ? "dragging" : ""}`}
            style={isDragged ? { transform: `translateY(${drag.offset}px) scale(1.02)` } : undefined}
            tabIndex={0}
            aria-label={`${i + 1}. ${p.title}. Drag, or use the up and down arrow keys, to move it.`}
            onPointerDown={(e) => onPointerDown(e, key)}
            onPointerMove={onPointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onKeyDown={(e) => onKeyDown(e, i)}
          >
            <span className="pr-rank">{i + 1}</span>
            <span className="pr-icon" aria-hidden="true">{p.icon}</span>
            <span className="pr-text">
              <strong>{p.title}</strong>
              <small>{p.sub}</small>
            </span>
            <span className="pr-handle" aria-hidden="true">⠿</span>
          </li>
        );
      })}
    </ol>
  );
}

export default PriorityRanker;
