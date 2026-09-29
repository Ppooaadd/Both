/**
 * Click effect overlay: an expanding glow ring plus a puff of star dust at
 * every pointer press. Clicks on `.galaxy-neon-btn` get a stronger burst.
 * The canvas has pointer-events: none, so it never intercepts clicks; the
 * animation loop runs only while particles are alive.
 */

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  max: number;
  size: number;
  hue: number;
}

interface Ring {
  x: number;
  y: number;
  life: number;
  max: number;
  radius: number;
  hue: number;
}

const HUES = [285, 230, 330, 45]; // violet, cyan, magenta, gold

export function createClickBurst(canvas: HTMLCanvasElement): () => void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return () => undefined;
  const particles: Particle[] = [];
  const rings: Ring[] = [];
  let raf = 0;
  let last = 0;

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(window.innerWidth * dpr);
    canvas.height = Math.round(window.innerHeight * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  resize();

  const frame = (now: number) => {
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    ctx.globalCompositeOperation = "lighter";

    for (let i = rings.length - 1; i >= 0; i--) {
      const r = rings[i];
      r.life += dt;
      const p = r.life / r.max;
      if (p >= 1) {
        rings.splice(i, 1);
        continue;
      }
      if (p <= 0) continue; // delayed ring not started yet
      const ease = 1 - (1 - p) ** 3;
      ctx.beginPath();
      ctx.arc(r.x, r.y, 4 + ease * r.radius, 0, Math.PI * 2);
      ctx.strokeStyle = `hsla(${r.hue}, 95%, 72%, ${0.85 * (1 - p)})`;
      ctx.lineWidth = 2.5 * (1 - p) + 0.5;
      ctx.shadowColor = `hsla(${r.hue}, 100%, 65%, ${1 - p})`;
      ctx.shadowBlur = 16;
      ctx.stroke();
    }

    ctx.shadowBlur = 0;
    for (let i = particles.length - 1; i >= 0; i--) {
      const q = particles[i];
      q.life += dt;
      const p = q.life / q.max;
      if (p >= 1) {
        particles.splice(i, 1);
        continue;
      }
      q.vx *= 0.93;
      q.vy = q.vy * 0.93 + 18 * dt; // a little drift downward
      q.x += q.vx * dt;
      q.y += q.vy * dt;
      const a = (1 - p) * (0.6 + 0.4 * Math.sin(q.life * 30 + q.hue));
      const g = ctx.createRadialGradient(q.x, q.y, 0, q.x, q.y, q.size * 3);
      g.addColorStop(0, `hsla(${q.hue}, 100%, 85%, ${a})`);
      g.addColorStop(1, `hsla(${q.hue}, 100%, 60%, 0)`);
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(q.x, q.y, q.size * 3, 0, Math.PI * 2);
      ctx.fill();
    }

    if (particles.length || rings.length) raf = requestAnimationFrame(frame);
    else raf = 0;
  };

  const burst = (x: number, y: number, strong: boolean) => {
    const hue = HUES[Math.floor(Math.random() * HUES.length)];
    rings.push({ x, y, life: 0, max: strong ? 0.9 : 0.7, radius: strong ? 90 : 55, hue });
    if (strong) rings.push({ x, y, life: -0.08, max: 1.0, radius: 130, hue: (hue + 60) % 360 });
    const n = strong ? 34 : 16;
    for (let i = 0; i < n; i++) {
      const angle = Math.random() * Math.PI * 2;
      const speed = (strong ? 160 : 90) * (0.4 + Math.random());
      particles.push({
        x,
        y,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        life: 0,
        max: 0.5 + Math.random() * 0.6,
        size: 0.8 + Math.random() * 1.8,
        hue: HUES[Math.floor(Math.random() * HUES.length)],
      });
    }
    if (!raf) {
      last = performance.now();
      raf = requestAnimationFrame(frame);
    }
  };

  const onDown = (e: PointerEvent) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    const target = e.target instanceof Element ? e.target : null;
    burst(e.clientX, e.clientY, Boolean(target?.closest(".galaxy-neon-btn")));
  };

  window.addEventListener("pointerdown", onDown, { passive: true, capture: true });
  window.addEventListener("resize", resize);
  return () => {
    cancelAnimationFrame(raf);
    window.removeEventListener("pointerdown", onDown, { capture: true });
    window.removeEventListener("resize", resize);
  };
}
