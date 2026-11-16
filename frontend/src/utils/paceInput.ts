// Easy-pace boxes (mm : ss): typing flows from minutes into seconds, so the runner never
// has to click the seconds box. A first digit of 4-9 is the whole minutes (9 -> 9:__);
// 1, 2 or 3 waits for the next digit (1 -> 10, 2 -> 20...), or for ":" to move on.
// Typing ":" "." or a space also jumps over, and pasting "9:30" fills both.
import type { RefObject } from "react";

export function paceMinChange(
  raw: string,
  setMin: (v: string) => void,
  setSec: (v: string) => void,
  secRef: RefObject<HTMLInputElement | null>,
) {
  const jump = () => setTimeout(() => { secRef.current?.focus(); secRef.current?.select(); }, 0);
  const split = raw.match(/^\s*(\d{0,2})\s*[:.\s]\s*(\d{0,2})/);
  if (split) {                                    // "9:30", "9." or "9 "
    setMin(split[1]);
    if (split[2]) setSec(clampSec(split[2]));
    if (split[1]) jump();
    return;
  }
  const digits = raw.replace(/\D/g, "");
  const minLen = /^[0-3]/.test(digits) ? 2 : 1;   // 1x/2x/3x are two digits, 4-9 is one
  const min = digits.slice(0, minLen);
  setMin(min);
  if (digits.length > minLen) setSec(clampSec(digits.slice(minLen, minLen + 2)));   // typed "930"
  if (min.length === minLen) jump();
}

export function paceSecChange(raw: string, setSec: (v: string) => void) {
  setSec(clampSec(raw.replace(/\D/g, "").slice(0, 2)));
}

/** Backspace in an empty seconds box goes back to the minutes. */
export function paceSecKeyDown(
  e: React.KeyboardEvent<HTMLInputElement>,
  minRef: RefObject<HTMLInputElement | null>,
) {
  if (e.key === "Backspace" && !e.currentTarget.value) {
    e.preventDefault();
    minRef.current?.focus();
  }
}

function clampSec(v: string) {
  return v && parseInt(v, 10) > 59 ? "59" : v;
}
