import { describe, expect, it } from "vitest";

import type { ScoreNote } from "@/lib/api/schemas";
import {
  HEADER_HEIGHT,
  KEYBOARD_WIDTH,
  clampScroll,
  followScroll,
  hitTest,
  pitchRange,
  pitchToY,
  tickToX,
  xToTick,
  yToPitch,
  type Viewport,
} from "./geometry";

const vp: Viewport = { width: 1044, height: 334, scrollX: 0, pxPerBeat: 50 };
const note = (pitch: number, start: number, dur: number, hand: "rh" | "lh" = "rh"): ScoreNote => ({
  hand, pitch, start, dur, velocity: 80, role: "melody", finger: null,
});

describe("piano roll geometry", () => {
  it("maps ticks and x both ways", () => {
    expect(tickToX(0, vp, 480)).toBe(KEYBOARD_WIDTH);
    expect(tickToX(480, vp, 480)).toBe(KEYBOARD_WIDTH + 50);
    const scrolled = { ...vp, scrollX: 100 };
    expect(xToTick(tickToX(960, scrolled, 480), scrolled, 480)).toBeCloseTo(960);
  });

  it("maps pitches to rows inside the grid", () => {
    const range = { low: 60, high: 69 }; // 10 rows over 300 px -> 30 px each
    expect(pitchToY(69, vp, range)).toBe(HEADER_HEIGHT);
    expect(pitchToY(60, vp, range)).toBe(HEADER_HEIGHT + 270);
    expect(yToPitch(HEADER_HEIGHT + 31, vp, range)).toBe(68);
    expect(yToPitch(5, vp, range)).toBeNull();
  });

  it("pads and clamps the pitch range", () => {
    expect(pitchRange([note(22, 0, 1), note(107, 0, 1)])).toEqual({ low: 21, high: 108 });
    expect(pitchRange([])).toEqual({ low: 48, high: 84 });
  });

  it("hit-tests notes by pitch and time", () => {
    const range = { low: 60, high: 69 };
    const notes = [note(64, 0, 480), note(64, 480, 480, "lh")];
    const y = pitchToY(64, vp, range) + 5;
    expect(hitTest(notes, tickToX(100, vp, 480), y, vp, 480, range)).toBe(notes[0]);
    expect(hitTest(notes, tickToX(700, vp, 480), y, vp, 480, range)).toBe(notes[1]);
    expect(hitTest(notes, tickToX(1000, vp, 480), y, vp, 480, range)).toBeNull();
  });

  it("follows the playhead page by page and clamps scroll", () => {
    const score = { measures: 8, time_signature: [4, 4] as [number, number], tpq: 480 };
    expect(followScroll(480, vp, 480)).toBe(0); // inside the view: no scroll
    const far = followScroll(480 * 20, vp, 480);
    expect(far).toBeGreaterThan(0);
    expect(tickToX(480 * 20, { ...vp, scrollX: far }, 480)).toBeLessThan(vp.width * 0.5);
    expect(clampScroll(10_000, score, vp)).toBe(8 * 4 * 50 - (vp.width - KEYBOARD_WIDTH) + 24);
    expect(clampScroll(-5, score, vp)).toBe(0);
  });
});
