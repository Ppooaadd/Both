/**
 * Three.js space backdrop: twinkling star field, a spiral galaxy with
 * differential rotation, soft nebula glow and the odd shooting star.
 *
 * The cursor tilts the camera slightly (parallax) and brightens stars near it.
 * Rendering pauses while the tab is hidden; with reduced motion a single still
 * frame is drawn. The canvas is transparent (alpha) so the page background and
 * the canvas' CSS opacity (--galaxy-opacity) decide how bright it looks.
 */
import * as THREE from "three";

export interface GalaxyOptions {
  reducedMotion: boolean;
  mobile: boolean;
}

export interface GalaxyHandle {
  dispose(): void;
}

const STAR_VERT = /* glsl */ `
  uniform float uTime;
  uniform float uPixelRatio;
  uniform vec2 uMouse;
  uniform float uAspect;
  attribute float aScale;
  attribute float aPhase;
  attribute float aSpeed;
  attribute vec3 aColor;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    float twinkle = 0.55 + 0.45 * sin(uTime * aSpeed + aPhase);
    vec2 ndc = gl_Position.xy / gl_Position.w;
    float near = smoothstep(0.45, 0.0, distance(ndc * vec2(uAspect, 1.0), uMouse * vec2(uAspect, 1.0)));
    vColor = aColor;
    vAlpha = twinkle + near * 0.8;
    gl_PointSize = aScale * uPixelRatio * (0.7 + 0.6 * twinkle + near * 1.2) * (60.0 / -mv.z);
  }
`;

const GALAXY_VERT = /* glsl */ `
  uniform float uTime;
  uniform float uPixelRatio;
  attribute float aScale;
  attribute float aRadius;
  attribute vec3 aColor;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    // Inner stars orbit faster than outer ones.
    float angle = uTime * 0.05 / (0.4 + aRadius * 0.35);
    float c = cos(angle), s = sin(angle);
    vec3 p = vec3(position.x * c - position.z * s, position.y, position.x * s + position.z * c);
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    vColor = aColor;
    vAlpha = 0.85;
    gl_PointSize = aScale * uPixelRatio * (22.0 / -mv.z);
  }
`;

const POINT_FRAG = /* glsl */ `
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    float glow = pow(smoothstep(0.5, 0.0, d), 1.6);
    float core = smoothstep(0.12, 0.0, d);
    gl_FragColor = vec4(vColor, (glow + core) * vAlpha);
  }
`;

function glowTexture(): THREE.CanvasTexture {
  const size = 128;
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.25, "rgba(255,255,255,0.45)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function pointsMaterial(vertex: string, uniforms: Record<string, THREE.IUniform>): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: vertex,
    fragmentShader: POINT_FRAG,
    uniforms,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
}

function starField(count: number, uniforms: Record<string, THREE.IUniform>): THREE.Points {
  const pos = new Float32Array(count * 3);
  const col = new Float32Array(count * 3);
  const scale = new Float32Array(count);
  const phase = new Float32Array(count);
  const speed = new Float32Array(count);
  const palette = [new THREE.Color("#cfd8ff"), new THREE.Color("#ffffff"), new THREE.Color("#ffe3b0"), new THREE.Color("#b9a8ff")];
  for (let i = 0; i < count; i++) {
    const r = 35 + Math.random() * 55;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    pos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    pos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    pos[i * 3 + 2] = r * Math.cos(phi);
    palette[Math.floor(Math.random() * palette.length)].toArray(col, i * 3);
    scale[i] = 0.6 + Math.random() ** 3 * 2.8;
    phase[i] = Math.random() * Math.PI * 2;
    speed[i] = 0.6 + Math.random() * 2.2;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("aColor", new THREE.BufferAttribute(col, 3));
  geo.setAttribute("aScale", new THREE.BufferAttribute(scale, 1));
  geo.setAttribute("aPhase", new THREE.BufferAttribute(phase, 1));
  geo.setAttribute("aSpeed", new THREE.BufferAttribute(speed, 1));
  return new THREE.Points(geo, pointsMaterial(STAR_VERT, uniforms));
}

function spiralGalaxy(count: number, uniforms: Record<string, THREE.IUniform>): THREE.Points {
  const radius = 7;
  const branches = 4;
  const spin = 1.1;
  const randomness = 0.38;
  const power = 3;
  const inner = new THREE.Color("#ffd9a0");
  const mid = new THREE.Color("#b28cff");
  const outer = new THREE.Color("#3fb8ff");
  const pos = new Float32Array(count * 3);
  const col = new Float32Array(count * 3);
  const scale = new Float32Array(count);
  const rad = new Float32Array(count);
  const tmp = new THREE.Color();
  for (let i = 0; i < count; i++) {
    const r = Math.random() ** 1.4 * radius;
    const branch = ((i % branches) / branches) * Math.PI * 2;
    const spinAngle = r * spin;
    const jitter = () => Math.random() ** power * (Math.random() < 0.5 ? 1 : -1) * randomness * (r + 0.3);
    pos[i * 3] = Math.cos(branch + spinAngle) * r + jitter();
    pos[i * 3 + 1] = jitter() * 0.35;
    pos[i * 3 + 2] = Math.sin(branch + spinAngle) * r + jitter();
    const t = r / radius;
    tmp.copy(inner).lerp(mid, Math.min(1, t * 1.8));
    if (t > 0.55) tmp.lerp(outer, (t - 0.55) / 0.45);
    tmp.toArray(col, i * 3);
    scale[i] = 0.5 + Math.random() * 1.6;
    rad[i] = r;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("aColor", new THREE.BufferAttribute(col, 3));
  geo.setAttribute("aScale", new THREE.BufferAttribute(scale, 1));
  geo.setAttribute("aRadius", new THREE.BufferAttribute(rad, 1));
  return new THREE.Points(geo, pointsMaterial(GALAXY_VERT, uniforms));
}

function sprite(tex: THREE.Texture, color: string, opacity: number, size: number): THREE.Sprite {
  const mat = new THREE.SpriteMaterial({
    map: tex,
    color: new THREE.Color(color),
    transparent: true,
    opacity,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  const s = new THREE.Sprite(mat);
  s.scale.setScalar(size);
  return s;
}

interface Meteor {
  line: THREE.Line;
  start: THREE.Vector3;
  dir: THREE.Vector3;
  age: number;
  life: number;
}

export function createGalaxy(canvas: HTMLCanvasElement, opts: GalaxyOptions): GalaxyHandle | null {
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: "low-power" });
  } catch {
    return null; // no WebGL: the CSS gradient background remains
  }
  let dpr = Math.min(window.devicePixelRatio || 1, opts.mobile ? 1.25 : 1.5);
  renderer.setPixelRatio(dpr);
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 200);
  const base = new THREE.Vector3(0, 3.2, 9);
  camera.position.copy(base);

  const uniforms = {
    uTime: { value: 0 },
    uPixelRatio: { value: dpr },
    uMouse: { value: new THREE.Vector2(9, 9) },
    uAspect: { value: 1 },
  };

  const stars = starField(opts.mobile ? 1500 : 3500, uniforms);
  scene.add(stars);

  const galaxyGroup = new THREE.Group();
  // Tilted towards the viewer so the spiral arms read, and placed off-centre
  // (lower right) so the brightest core stays out from behind the main text.
  galaxyGroup.position.set(opts.mobile ? 1.5 : 4.2, opts.mobile ? -5.2 : -1.6, -3);
  galaxyGroup.rotation.set(0.95, 0, 0.35);
  const galaxy = spiralGalaxy(opts.mobile ? 7000 : 18000, uniforms);
  galaxyGroup.add(galaxy);

  const tex = glowTexture();
  const core = sprite(tex, "#ffcf99", 0.55, 3.2);
  galaxyGroup.add(core);
  scene.add(galaxyGroup);

  const nebulae: THREE.Sprite[] = [
    sprite(tex, "#6b3dff", 0.16, 30),
    sprite(tex, "#c040ff", 0.1, 24),
    sprite(tex, "#1f8fff", 0.12, 28),
    sprite(tex, "#ff4fa3", 0.07, 20),
  ];
  const nebulaPos = [
    [-12, 6, -30],
    [14, -4, -34],
    [-4, -8, -26],
    [8, 9, -38],
  ];
  nebulae.forEach((n, i) => {
    n.position.set(nebulaPos[i][0], nebulaPos[i][1], nebulaPos[i][2]);
    scene.add(n);
  });

  // Shooting stars: a short fading line swept across the sky now and then.
  const meteors: Meteor[] = [];
  let nextMeteor = 3 + Math.random() * 5;
  const spawnMeteor = () => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
    geo.setAttribute("color", new THREE.BufferAttribute(new Float32Array([1, 1, 1, 0.3, 0.4, 1]), 3));
    const mat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const line = new THREE.Line(geo, mat);
    const start = new THREE.Vector3(-18 + Math.random() * 36, 8 + Math.random() * 6, -20);
    const dir = new THREE.Vector3(-0.6 - Math.random() * 0.5, -0.45 - Math.random() * 0.3, 0).normalize();
    scene.add(line);
    meteors.push({ line, start, dir, age: 0, life: 1.1 + Math.random() * 0.6 });
  };

  const resize = () => {
    const w = window.innerWidth;
    const h = window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    uniforms.uAspect.value = w / h;
  };
  resize();

  const target = new THREE.Vector2(0, 0);
  const cur = new THREE.Vector2(0, 0);
  const mouseNdc = new THREE.Vector2(9, 9);
  const onPointer = (e: PointerEvent) => {
    target.set((e.clientX / window.innerWidth) * 2 - 1, (e.clientY / window.innerHeight) * 2 - 1);
    mouseNdc.set(target.x, -target.y);
  };
  const onLeave = () => mouseNdc.set(9, 9);

  let lastFrame = 0;
  let raf = 0;
  let running = false;

  // Adaptive quality: when frames run slow (weak GPU, software rendering),
  // first lower the resolution, then draw every other frame. The page's own
  // work (playback, live progress) must never starve behind the backdrop.
  let slowEma = 1 / 60;
  let skip = false;
  let skipToggle = false;
  let slowFrames = 0;
  const adapt = (dtRaw: number) => {
    slowEma = slowEma * 0.95 + dtRaw * 0.05;
    slowFrames = slowEma > 1 / 35 ? slowFrames + 1 : 0;
    if (slowFrames < 90) return;
    slowFrames = 0;
    if (dpr > 0.6) {
      dpr = Math.max(0.6, dpr * 0.7);
      renderer.setPixelRatio(dpr);
      uniforms.uPixelRatio.value = dpr;
      resize();
    } else {
      skip = true;
    }
  };

  const frame = (now: number) => {
    const dtRaw = (now - lastFrame) / 1000;
    lastFrame = now;
    adapt(dtRaw);
    if (skip && (skipToggle = !skipToggle)) {
      if (running) raf = requestAnimationFrame(frame);
      return;
    }
    const dt = Math.min(dtRaw * (skip ? 2 : 1), 0.1);
    const t = (uniforms.uTime.value += dt);
    cur.lerp(target, 0.04);
    uniforms.uMouse.value.lerp(mouseNdc, 0.15);
    const scroll = Math.min(1, window.scrollY / Math.max(1, document.body.scrollHeight - window.innerHeight));
    camera.position.set(base.x + cur.x * 0.9, base.y - cur.y * 0.6, base.z + scroll * 1.5);
    camera.lookAt(0, 0, 0);
    stars.rotation.y = t * 0.006;
    galaxyGroup.rotation.z = 0.35 + cur.x * 0.06;
    nebulae.forEach((n, i) => {
      (n.material as THREE.SpriteMaterial).rotation = t * 0.01 * (i % 2 ? 1 : -1);
    });

    nextMeteor -= dt;
    if (nextMeteor <= 0) {
      spawnMeteor();
      nextMeteor = 5 + Math.random() * 8;
    }
    for (let i = meteors.length - 1; i >= 0; i--) {
      const m = meteors[i];
      m.age += dt;
      const p = m.age / m.life;
      const head = m.start.clone().addScaledVector(m.dir, p * 26);
      const tail = head.clone().addScaledVector(m.dir, -3.5);
      const arr = m.line.geometry.getAttribute("position") as THREE.BufferAttribute;
      arr.setXYZ(0, head.x, head.y, head.z);
      arr.setXYZ(1, tail.x, tail.y, tail.z);
      arr.needsUpdate = true;
      (m.line.material as THREE.LineBasicMaterial).opacity = Math.sin(Math.PI * Math.min(1, p));
      if (p >= 1) {
        scene.remove(m.line);
        m.line.geometry.dispose();
        (m.line.material as THREE.Material).dispose();
        meteors.splice(i, 1);
      }
    }

    renderer.render(scene, camera);
    if (running) raf = requestAnimationFrame(frame);
  };

  const start = () => {
    if (running || opts.reducedMotion) return;
    running = true;
    lastFrame = performance.now();
    raf = requestAnimationFrame(frame);
  };
  const stop = () => {
    running = false;
    cancelAnimationFrame(raf);
  };
  const onVisibility = () => (document.hidden ? stop() : start());
  const onResize = () => {
    resize();
    if (opts.reducedMotion) renderer.render(scene, camera);
  };

  window.addEventListener("resize", onResize);
  if (opts.reducedMotion) {
    uniforms.uTime.value = 12;
    camera.lookAt(0, 0, 0);
    renderer.render(scene, camera);
  } else {
    window.addEventListener("pointermove", onPointer, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
    document.addEventListener("visibilitychange", onVisibility);
    start();
  }

  return {
    dispose() {
      stop();
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onPointer);
      document.documentElement.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("visibilitychange", onVisibility);
      scene.traverse((o) => {
        const obj = o as THREE.Mesh;
        obj.geometry?.dispose();
        const mat = obj.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else mat?.dispose();
      });
      tex.dispose();
      renderer.dispose();
    },
  };
}
