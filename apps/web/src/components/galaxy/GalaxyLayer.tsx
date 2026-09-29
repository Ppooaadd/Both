"use client";

import { useEffect, useRef } from "react";

/**
 * Galaxy theme runtime, mounted once in the root layout:
 * - #galaxy-canvas: Three.js space backdrop behind all content (z-index -1)
 * - #galaxy-click-layer: click bursts above all content (pointer-events none)
 * - scroll reveal for `.animate-fade-up`
 *
 * Three.js and GSAP are loaded lazily after first paint so they never delay
 * the page. With prefers-reduced-motion the backdrop is a still frame and the
 * click and scroll effects are off.
 */
export function GalaxyLayer() {
  const bgRef = useRef<HTMLCanvasElement>(null);
  const fxRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const bg = bgRef.current;
    const fx = fxRef.current;
    if (!bg || !fx) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const mobile = window.matchMedia("(max-width: 768px), (pointer: coarse)").matches;
    let cancelled = false;
    const cleanups: Array<() => void> = [];

    void import("@/lib/galaxy/scene").then(({ createGalaxy }) => {
      if (cancelled) return;
      const handle = createGalaxy(bg, { reducedMotion: reduced, mobile });
      if (!handle) return;
      bg.classList.add("is-ready");
      cleanups.push(() => handle.dispose());
    });

    if (!reduced) {
      void import("@/lib/galaxy/clickBurst").then(({ createClickBurst }) => {
        if (!cancelled) cleanups.push(createClickBurst(fx));
      });
      void import("@/lib/galaxy/scrollReveal")
        .then(({ startScrollReveal }) => {
          if (!cancelled) cleanups.push(startScrollReveal());
        })
        .catch(() => document.documentElement.classList.remove("galaxy-js"));
    }

    return () => {
      cancelled = true;
      bg.classList.remove("is-ready");
      cleanups.forEach((fn) => fn());
    };
  }, []);

  return (
    <>
      <canvas id="galaxy-canvas" ref={bgRef} aria-hidden="true" />
      <canvas id="galaxy-click-layer" ref={fxRef} aria-hidden="true" />
    </>
  );
}
