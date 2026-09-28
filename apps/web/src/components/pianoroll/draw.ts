/** Canvas painter for the piano roll. Stateless: everything comes in as arguments. */
import type { Score, ScoreNote } from "@/lib/api/schemas";
import { chordLabel, isBlackKey, noteName } from "@/lib/music";
import {
  HEADER_HEIGHT,
  KEYBOARD_WIDTH,
  pitchToY,
  rowHeight,
  tickToX,
  visibleTicks,
  type PitchRange,
  type Viewport,
} from "./geometry";

export type RollColors = {
  bg: string;
  blackRow: string;
  grid: string;
  bar: string;
  rh: string;
  lh: string;
  playhead: string;
  text: string;
  muted: string;
  brass: string;
  keyWhite: string;
  keyBlack: string;
};

export function readColors(el: Element): RollColors {
  const css = getComputedStyle(el);
  const v = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback;
  return {
    bg: v("--roll-bg", "#fcfcfd"),
    blackRow: v("--roll-black-row", "#f1f2f5"),
    grid: v("--roll-grid", "#e3e5ea"),
    bar: v("--roll-bar", "#b9bfca"),
    rh: v("--roll-rh", "#1d3a6e"),
    lh: v("--roll-lh", "#b8862b"),
    playhead: v("--roll-playhead", "#d23b2b"),
    text: v("--foreground", "#1a1d24"),
    muted: v("--muted-foreground", "#667085"),
    brass: v("--brass", "#94701f"),
    keyWhite: v("--roll-key-white", "#ffffff"),
    keyBlack: v("--roll-key-black", "#1a1d24"),
  };
}

export type DrawInput = {
  score: Score;
  vp: Viewport;
  range: PitchRange;
  playheadTick: number | null;
  hands: { rh: boolean; lh: boolean };
  hover: ScoreNote | null;
  colors: RollColors;
  fontFamily: string;
};

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

export function drawRoll(ctx: CanvasRenderingContext2D, input: DrawInput): void {
  const { score, vp, range, colors: c } = input;
  const tpq = score.tpq;
  const rh = rowHeight(vp, range);
  const [t0, t1] = visibleTicks(vp, tpq);
  const beatsPerBar = score.time_signature[0];
  const barTicks = beatsPerBar * tpq;
  const totalTicks = score.measures * barTicks;

  ctx.clearRect(0, 0, vp.width, vp.height);
  ctx.fillStyle = c.bg;
  ctx.fillRect(0, 0, vp.width, vp.height);

  // Pitch rows.
  for (let p = range.low; p <= range.high; p++) {
    const y = pitchToY(p, vp, range);
    if (isBlackKey(p)) {
      ctx.fillStyle = c.blackRow;
      ctx.fillRect(KEYBOARD_WIDTH, y, vp.width - KEYBOARD_WIDTH, rh);
    }
    if (p % 12 === 0) {
      ctx.fillStyle = c.grid;
      ctx.fillRect(KEYBOARD_WIDTH, y + rh - 1, vp.width - KEYBOARD_WIDTH, 1);
    }
  }

  // Beat and bar lines + bar numbers.
  ctx.font = `11px ${input.fontFamily}`;
  ctx.textBaseline = "top";
  const firstBeat = Math.max(0, Math.floor(t0 / tpq));
  const lastBeat = Math.min(Math.ceil(t1 / tpq), totalTicks / tpq);
  for (let b = firstBeat; b <= lastBeat; b++) {
    const x = Math.round(tickToX(b * tpq, vp, tpq)) + 0.5;
    const isBar = b % beatsPerBar === 0;
    if (!isBar && vp.pxPerBeat < 14) continue;
    ctx.strokeStyle = isBar ? c.bar : c.grid;
    ctx.beginPath();
    ctx.moveTo(x, isBar ? 0 : HEADER_HEIGHT);
    ctx.lineTo(x, vp.height);
    ctx.stroke();
    if (isBar) {
      ctx.fillStyle = c.muted;
      ctx.fillText(String(b / beatsPerBar + 1), x + 3, 2);
    }
  }

  // Header lane: sections (brass tags) and chord symbols.
  ctx.fillStyle = c.bg;
  ctx.globalAlpha = 0.92;
  ctx.fillRect(KEYBOARD_WIDTH, 14, vp.width - KEYBOARD_WIDTH, HEADER_HEIGHT - 14);
  ctx.globalAlpha = 1;
  const tagSpans: [number, number][] = [];
  for (const s of score.sections) {
    if (s.start > t1) continue;
    const x = tickToX(s.start, vp, tpq);
    if (x < KEYBOARD_WIDTH - 20) continue;
    tagSpans.push([x, x + 20]);
    ctx.fillStyle = c.brass;
    roundRect(ctx, x + 2, 15, 16, 16, 3);
    ctx.fill();
    ctx.fillStyle = c.bg;
    ctx.font = `600 11px ${input.fontFamily}`;
    ctx.fillText(s.label, x + 6, 18);
  }
  ctx.font = `12px ${input.fontFamily}`;
  let lastLabelEnd = -Infinity;
  for (const ch of score.chords) {
    if (ch.start > t1) break;
    let x = tickToX(ch.start, vp, tpq) + 3;
    const label = chordLabel(ch.root, ch.quality, ch.bass);
    const w = ctx.measureText(label).width;
    // Step past a section tag the label would overlap.
    for (const [a, b] of tagSpans) if (x < b && x + w > a) x = b + 3;
    if (x + w < KEYBOARD_WIDTH || x < lastLabelEnd + 4) continue;
    ctx.fillStyle = c.text;
    ctx.fillText(label, x, 17);
    lastLabelEnd = x + w;
  }

  // Pedal: thin brass strip at the bottom.
  ctx.fillStyle = c.brass;
  ctx.globalAlpha = 0.35;
  for (const p of score.pedal) {
    if (p.end < t0 || p.start > t1) continue;
    const x0 = Math.max(KEYBOARD_WIDTH, tickToX(p.start, vp, tpq));
    const x1 = tickToX(p.end, vp, tpq);
    ctx.fillRect(x0, vp.height - 3, Math.max(0, x1 - x0), 3);
  }
  ctx.globalAlpha = 1;

  // Notes: left hand first so right-hand melody stays on top.
  ctx.save();
  ctx.beginPath();
  ctx.rect(KEYBOARD_WIDTH, HEADER_HEIGHT, vp.width - KEYBOARD_WIDTH, vp.height - HEADER_HEIGHT);
  ctx.clip();
  const ppt = vp.pxPerBeat / tpq;
  for (const hand of ["lh", "rh"] as const) {
    if (!input.hands[hand]) continue;
    for (const n of score.notes) {
      if (n.hand !== hand || n.start > t1 || n.start + n.dur < t0) continue;
      if (n.pitch < range.low || n.pitch > range.high) continue;
      const x = tickToX(n.start, vp, tpq);
      const w = Math.max(2, n.dur * ppt - 1);
      const y = pitchToY(n.pitch, vp, range);
      const active =
        input.playheadTick !== null && input.playheadTick >= n.start && input.playheadTick < n.start + n.dur;
      ctx.fillStyle = hand === "rh" ? c.rh : c.lh;
      ctx.globalAlpha = n.role === "melody" || n.role === "bass" ? 1 : 0.62;
      if (active) ctx.globalAlpha = 1;
      roundRect(ctx, x, y + 0.5, w, Math.max(2, rh - 1), 2);
      ctx.fill();
      if (active || input.hover === n) {
        ctx.strokeStyle = c.text;
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.lineWidth = 1;
      }
      if (score.show_fingering && n.finger && rh >= 10 && w >= 12) {
        ctx.globalAlpha = 1;
        ctx.fillStyle = c.bg;
        ctx.font = `600 ${Math.min(11, rh - 2)}px ${input.fontFamily}`;
        ctx.textBaseline = "middle";
        ctx.fillText(String(n.finger), x + 3, y + rh / 2 + 0.5);
        ctx.textBaseline = "top";
      }
    }
  }
  ctx.globalAlpha = 1;
  ctx.restore();

  // Keyboard.
  ctx.fillStyle = c.keyWhite;
  ctx.fillRect(0, HEADER_HEIGHT, KEYBOARD_WIDTH, vp.height - HEADER_HEIGHT);
  ctx.font = `10px ${input.fontFamily}`;
  ctx.textBaseline = "middle";
  for (let p = range.low; p <= range.high; p++) {
    const y = pitchToY(p, vp, range);
    if (isBlackKey(p)) {
      ctx.fillStyle = c.keyBlack;
      ctx.fillRect(0, y, KEYBOARD_WIDTH * 0.62, rh);
    } else {
      ctx.fillStyle = c.grid;
      ctx.fillRect(0, y + rh - 0.5, KEYBOARD_WIDTH, 0.5);
    }
    if (p % 12 === 0 && rh >= 6) {
      ctx.fillStyle = c.keyBlack;
      ctx.fillText(noteName(p), KEYBOARD_WIDTH * 0.64, y + rh / 2);
    }
  }
  ctx.fillStyle = c.bar;
  ctx.fillRect(KEYBOARD_WIDTH - 1, 0, 1, vp.height);
  ctx.fillRect(0, HEADER_HEIGHT - 1, vp.width, 1);

  // Playhead.
  if (input.playheadTick !== null) {
    const x = Math.round(tickToX(input.playheadTick, vp, tpq)) + 0.5;
    if (x >= KEYBOARD_WIDTH) {
      ctx.strokeStyle = c.playhead;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, vp.height);
      ctx.stroke();
      ctx.lineWidth = 1;
    }
  }
}
