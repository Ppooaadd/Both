/**
 * Pure piano-roll geometry: tick <-> x, pitch <-> y, hit testing, visible range.
 * Kept free of DOM/canvas code so it is unit-testable.
 */
import type { Score, ScoreNote } from "@/lib/api/schemas";

export const KEYBOARD_WIDTH = 44;
export const HEADER_HEIGHT = 34; // chord + section lane above the grid
export const MIN_PX_PER_BEAT = 12;
export const MAX_PX_PER_BEAT = 240;

export type Viewport = {
  width: number; // css px of the canvas
  height: number;
  scrollX: number; // css px scrolled from tick 0
  pxPerBeat: number;
};

export type PitchRange = { low: number; high: number };

export function pitchRange(notes: ScoreNote[], padding = 2): PitchRange {
  if (notes.length === 0) return { low: 48, high: 84 };
  let low = 127;
  let high = 0;
  for (const n of notes) {
    low = Math.min(low, n.pitch);
    high = Math.max(high, n.pitch);
  }
  return { low: Math.max(21, low - padding), high: Math.min(108, high + padding) };
}

export function rowHeight(vp: Viewport, range: PitchRange): number {
  const rows = range.high - range.low + 1;
  return Math.max(3, (vp.height - HEADER_HEIGHT) / rows);
}

export const pxPerTick = (vp: Viewport, tpq: number): number => vp.pxPerBeat / tpq;

export function tickToX(tick: number, vp: Viewport, tpq: number): number {
  return KEYBOARD_WIDTH + tick * pxPerTick(vp, tpq) - vp.scrollX;
}

export function xToTick(x: number, vp: Viewport, tpq: number): number {
  return Math.max(0, (x - KEYBOARD_WIDTH + vp.scrollX) / pxPerTick(vp, tpq));
}

export function pitchToY(pitch: number, vp: Viewport, range: PitchRange): number {
  return HEADER_HEIGHT + (range.high - pitch) * rowHeight(vp, range);
}

export function yToPitch(y: number, vp: Viewport, range: PitchRange): number | null {
  if (y < HEADER_HEIGHT) return null;
  const p = range.high - Math.floor((y - HEADER_HEIGHT) / rowHeight(vp, range));
  return p >= range.low && p <= range.high ? p : null;
}

export function contentWidth(score: Pick<Score, "measures" | "time_signature" | "tpq">, vp: Viewport): number {
  const beats = score.measures * score.time_signature[0];
  return beats * vp.pxPerBeat;
}

export function clampScroll(scrollX: number, score: Pick<Score, "measures" | "time_signature" | "tpq">, vp: Viewport): number {
  const max = Math.max(0, contentWidth(score, vp) - (vp.width - KEYBOARD_WIDTH) + 24);
  return Math.min(Math.max(0, scrollX), max);
}

export function visibleTicks(vp: Viewport, tpq: number): [number, number] {
  return [xToTick(KEYBOARD_WIDTH, vp, tpq), xToTick(vp.width, vp, tpq)];
}

/** Note under a point, preferring the top-most drawn (right hand drawn last). */
export function hitTest(
  notes: ScoreNote[],
  x: number,
  y: number,
  vp: Viewport,
  tpq: number,
  range: PitchRange,
): ScoreNote | null {
  const pitch = yToPitch(y, vp, range);
  if (pitch === null) return null;
  const tick = xToTick(x, vp, tpq);
  for (let i = notes.length - 1; i >= 0; i--) {
    const n = notes[i];
    if (n.pitch === pitch && tick >= n.start && tick < n.start + n.dur) return n;
  }
  return null;
}

/** Scroll that keeps the playhead inside the middle band of the view (page-turn style). */
export function followScroll(tick: number, vp: Viewport, tpq: number): number {
  const x = tick * pxPerTick(vp, tpq);
  const visible = vp.width - KEYBOARD_WIDTH;
  if (x < vp.scrollX + visible * 0.1 || x > vp.scrollX + visible * 0.8) {
    return Math.max(0, x - visible * 0.2);
  }
  return vp.scrollX;
}
