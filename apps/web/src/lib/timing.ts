/**
 * Written score position <-> performance time for a rendered arrangement.
 *
 * Mirrors ScoreIR.tick_to_seconds in the backend: swing moves written off-beat
 * eighths to their played position, then `performance_beats` (seconds of each
 * score beat in the rendered audio) maps beats to time piecewise-linearly.
 * Scores without `performance_beats` (older arrangements) play at a steady
 * `tempo_bpm`.
 */

export interface TimingSource {
  tpq: number;
  tempo_bpm: number;
  performance_beats?: number[];
  swing?: number;
}

export interface TimeMap {
  tickToSec(tick: number): number;
  secToTick(sec: number): number;
}

const STRAIGHT = 0.5;

export function swingMap(frac: number, swing: number): number {
  return frac < 0.5 ? frac * 2 * swing : swing + (frac - 0.5) * 2 * (1 - swing);
}

export function unswing(frac: number, swing: number): number {
  return frac < swing ? frac / (2 * swing) : 0.5 + (frac - swing) / (2 * (1 - swing));
}

export function timeMap(score: TimingSource): TimeMap {
  const tpq = score.tpq;
  const swing = score.swing ?? STRAIGHT;
  const secPerBeat = 60 / score.tempo_bpm;
  const pb = score.performance_beats && score.performance_beats.length >= 2 ? score.performance_beats : null;

  const beatToSec = (beat: number): number => {
    if (!pb) return beat * secPerBeat;
    const last = pb.length - 1;
    if (beat <= 0) return beat * (pb[1] - pb[0]);
    if (beat >= last) return pb[last] + (beat - last) * (pb[last] - pb[last - 1]);
    const i = Math.floor(beat);
    return pb[i] + (beat - i) * (pb[i + 1] - pb[i]);
  };

  const secToBeat = (sec: number): number => {
    if (!pb) return sec / secPerBeat;
    const last = pb.length - 1;
    if (sec <= pb[0]) return (sec - pb[0]) / (pb[1] - pb[0]);
    if (sec >= pb[last]) return last + (sec - pb[last]) / (pb[last] - pb[last - 1]);
    let lo = 0;
    let hi = last;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (pb[mid] <= sec) lo = mid;
      else hi = mid;
    }
    return lo + (sec - pb[lo]) / (pb[lo + 1] - pb[lo]);
  };

  return {
    tickToSec(tick) {
      const beat = tick / tpq;
      if (swing === STRAIGHT) return beatToSec(beat);
      const whole = Math.floor(beat);
      return beatToSec(whole + swingMap(beat - whole, swing));
    },
    secToTick(sec) {
      const played = secToBeat(sec);
      if (swing === STRAIGHT) return played * tpq;
      const whole = Math.floor(played);
      return (whole + unswing(played - whole, swing)) * tpq;
    },
  };
}
