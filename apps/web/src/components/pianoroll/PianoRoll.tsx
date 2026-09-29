"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import type { Score, ScoreNote } from "@/lib/api/schemas";
import { noteName } from "@/lib/music";
import { timeMap } from "@/lib/timing";
import { cn } from "@/lib/utils";
import { drawRoll, readColors, type RollColors } from "./draw";
import {
  KEYBOARD_WIDTH,
  MAX_PX_PER_BEAT,
  MIN_PX_PER_BEAT,
  clampScroll,
  followScroll,
  hitTest,
  pitchRange,
  xToTick,
  type Viewport,
} from "./geometry";

export type PianoRollProps = {
  score: Score;
  /** Current playback position in seconds (read every animation frame while playing). */
  getTime: () => number;
  playing: boolean;
  onSeek: (seconds: number) => void;
  hands: { rh: boolean; lh: boolean };
  follow?: boolean;
  className?: string;
};

const HAND_KO = { rh: "오른손", lh: "왼손" } as const;
const ROLE_KO = { melody: "멜로디", harmony: "화음", bass: "베이스", accomp: "반주" } as const;

export function PianoRoll({ score, getTime, playing, onSeek, hands, follow = true, className }: PianoRollProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ width: 800, height: 360 });
  const [pxPerBeat, setPxPerBeat] = useState(36);
  const [scrollX, setScrollX] = useState(0);
  const [hover, setHover] = useState<{ note: ScoreNote; x: number; y: number } | null>(null);
  const colorsRef = useRef<RollColors | null>(null);
  const drag = useRef<{ x: number; scroll: number; moved: boolean } | null>(null);

  const range = useMemo(() => pitchRange(score.notes), [score.notes]);
  const tm = useMemo(() => timeMap(score), [score]);
  const vp: Viewport = useMemo(
    () => ({ width: size.width, height: size.height, scrollX, pxPerBeat }),
    [size, scrollX, pxPerBeat],
  );
  const vpRef = useRef(vp);
  useLayoutEffect(() => {
    vpRef.current = vp;
  }, [vp]);
  const paintRef = useRef<(tick?: number) => void>(() => undefined);

  // Size + theme tracking.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width: Math.max(200, width), height: Math.max(160, height) });
    });
    ro.observe(el);
    colorsRef.current = readColors(el);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onTheme = () => {
      colorsRef.current = readColors(el);
      paintRef.current();
    };
    mq.addEventListener("change", onTheme);
    return () => {
      ro.disconnect();
      mq.removeEventListener("change", onTheme);
    };
  }, []);

  // Fit roughly eight bars into view on first layout.
  const fitted = useRef(false);
  useEffect(() => {
    if (fitted.current || size.width <= 200) return;
    fitted.current = true;
    const beats = Math.min(8, score.measures) * score.time_signature[0];
    setPxPerBeat(Math.min(MAX_PX_PER_BEAT, Math.max(MIN_PX_PER_BEAT, (size.width - KEYBOARD_WIDTH) / beats)));
  }, [size.width, score.measures, score.time_signature]);

  const paint = useCallback(
    (playheadTick?: number) => {
      const canvas = canvasRef.current;
      const colors = colorsRef.current;
      if (!canvas || !colors) return;
      const dpr = window.devicePixelRatio || 1;
      const v = vpRef.current;
      if (canvas.width !== Math.round(v.width * dpr) || canvas.height !== Math.round(v.height * dpr)) {
        canvas.width = Math.round(v.width * dpr);
        canvas.height = Math.round(v.height * dpr);
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const tick = playheadTick ?? tm.secToTick(getTime());
      drawRoll(ctx, {
        score,
        vp: v,
        range,
        playheadTick: tick,
        hands,
        hover: hover?.note ?? null,
        colors,
        fontFamily: getComputedStyle(canvas).fontFamily || "sans-serif",
      });
    },
    [score, range, hands, hover, getTime, tm],
  );

  // Static repaint whenever inputs change.
  useEffect(() => {
    paintRef.current = paint;
    paint();
  }, [paint, vp]);

  // Animation loop while playing: redraw playhead, page-turn scroll.
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const loop = () => {
      const tick = tm.secToTick(getTime());
      if (follow) {
        const next = clampScroll(followScroll(tick, vpRef.current, score.tpq), score, vpRef.current);
        if (Math.abs(next - vpRef.current.scrollX) > 1) {
          vpRef.current = { ...vpRef.current, scrollX: next };
          setScrollX(next);
        }
      }
      paint(tick);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [playing, follow, getTime, tm, paint, score]);

  const zoomAt = useCallback(
    (factor: number, anchorX: number) => {
      setPxPerBeat((old) => {
        const next = Math.min(MAX_PX_PER_BEAT, Math.max(MIN_PX_PER_BEAT, old * factor));
        const v = vpRef.current;
        const anchorTick = xToTick(anchorX, v, score.tpq);
        const newScroll = anchorTick * (next / score.tpq) - (anchorX - KEYBOARD_WIDTH);
        setScrollX(clampScroll(newScroll, score, { ...v, pxPerBeat: next }));
        return next;
      });
    },
    [score],
  );

  // Wheel: ctrl/cmd zooms around the cursor, otherwise scrolls horizontally.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      if (e.ctrlKey || e.metaKey) {
        zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.clientX - rect.left);
      } else {
        const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
        setScrollX((s) => clampScroll(s + delta, score, vpRef.current));
      }
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [zoomAt, score]);

  const local = (e: React.PointerEvent) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  };

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, scroll: vpRef.current.scrollX, moved: false };
  };
  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current;
    if (d) {
      const dx = e.clientX - d.x;
      if (Math.abs(dx) > 4) d.moved = true;
      if (d.moved) setScrollX(clampScroll(d.scroll - dx, score, vpRef.current));
      return;
    }
    const { x, y } = local(e);
    const note = hitTest(
      score.notes.filter((n) => hands[n.hand]),
      x,
      y,
      vpRef.current,
      score.tpq,
      range,
    );
    setHover(note ? { note, x, y } : null);
  };
  const onPointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current;
    drag.current = null;
    if (d && !d.moved) {
      const { x } = local(e);
      if (x > KEYBOARD_WIDTH) onSeek(Math.max(0, tm.tickToSec(xToTick(x, vpRef.current, score.tpq))));
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const step = vpRef.current.pxPerBeat * score.time_signature[0];
    if (e.key === "ArrowRight") setScrollX((s) => clampScroll(s + step, score, vpRef.current));
    else if (e.key === "ArrowLeft") setScrollX((s) => clampScroll(s - step, score, vpRef.current));
    else if (e.key === "+" || e.key === "=") zoomAt(1.25, vpRef.current.width / 2);
    else if (e.key === "-") zoomAt(0.8, vpRef.current.width / 2);
    else return;
    e.preventDefault();
  };

  return (
    <div
      ref={wrapRef}
      className={cn("relative h-full min-h-[240px] w-full overflow-hidden rounded-lg border bg-card font-mono", className)}
      tabIndex={0}
      role="application"
      aria-label={`피아노 롤: ${score.measures}마디. 좌우 화살표로 이동, +/-로 확대·축소, 클릭하면 그 위치부터 재생합니다.`}
      onKeyDown={onKeyDown}
    >
      <canvas
        ref={canvasRef}
        className="absolute inset-0 h-full w-full cursor-crosshair touch-none"
        style={{ width: size.width, height: size.height }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => setHover(null)}
      />
      {hover && (
        <div
          className="pointer-events-none absolute z-10 rounded-md border bg-popover px-2 py-1 font-sans text-xs text-popover-foreground shadow-md"
          style={{ left: Math.min(hover.x + 12, size.width - 150), top: Math.max(4, hover.y - 36) }}
        >
          <span className="font-mono font-semibold">{noteName(hover.note.pitch)}</span> · {HAND_KO[hover.note.hand]} ·{" "}
          {ROLE_KO[hover.note.role]}
          {hover.note.finger ? ` · ${hover.note.finger}번 손가락` : ""}
        </div>
      )}
    </div>
  );
}
