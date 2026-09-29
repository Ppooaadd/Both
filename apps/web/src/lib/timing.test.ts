import { describe, expect, it } from "vitest";

import { swingMap, timeMap, unswing } from "./timing";

describe("timeMap", () => {
  it("falls back to a steady tempo without performance beats", () => {
    const m = timeMap({ tpq: 480, tempo_bpm: 120 });
    expect(m.tickToSec(960)).toBeCloseTo(1.0);
    expect(m.secToTick(1.5)).toBeCloseTo(1440);
  });

  it("follows the recording's beat map, including tempo changes", () => {
    // Beats 0.5 s apart, then 0.4 s apart (120 -> 150 BPM).
    const m = timeMap({ tpq: 480, tempo_bpm: 130, performance_beats: [0, 0.5, 1.0, 1.4, 1.8] });
    expect(m.tickToSec(480 * 2)).toBeCloseTo(1.0);
    expect(m.tickToSec(480 * 3.5)).toBeCloseTo(1.6);
    expect(m.tickToSec(480 * 5)).toBeCloseTo(2.2); // extrapolated with the last beat
    for (const t of [0, 240, 700, 1500, 2000, 2600]) expect(m.secToTick(m.tickToSec(t))).toBeCloseTo(t);
  });

  it("plays written off-beat eighths at the swing position", () => {
    const m = timeMap({ tpq: 480, tempo_bpm: 60, performance_beats: [0, 1, 2, 3], swing: 2 / 3 });
    expect(m.tickToSec(240)).toBeCloseTo(2 / 3);
    expect(m.tickToSec(480 + 240)).toBeCloseTo(1 + 2 / 3);
    expect(m.secToTick(2 / 3)).toBeCloseTo(240);
  });

  it("swing maps are inverses", () => {
    for (const f of [0, 0.2, 0.5, 0.7, 0.99]) expect(unswing(swingMap(f, 0.62), 0.62)).toBeCloseTo(f);
  });
});
