/**
 * hero.js — 3D hero: particles that organize themselves from chaos into the
 * "D" monogram and then into a system dashboard ("complex → simple").
 *
 * Progressive enhancement: the HTML dashboard stays in place until the scene
 * has rendered its first frame; if anything fails, the page is unchanged.
 * Three.js is fetched lazily from a free public CDN only after page load.
 */
import { detectQuality } from "./quality.js";

const THREE_URL = "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.min.js";

const container = document.querySelector(".hero-3d");
const visual = document.querySelector(".hero-visual");
const hero = document.getElementById("hero");
const ui = document.querySelector(".hero-3d-ui");
const steps = ui ? Array.from(ui.querySelectorAll("[data-step]")) : [];
const toggle = ui ? ui.querySelector(".hero-3d-toggle") : null;
const quality = container ? detectQuality() : null;

/** Caption under the scene: highlights which phase is on screen right now. */
let currentStep = -1;
function setStep(index) {
  if (index === currentStep) return;
  currentStep = index;
  steps.forEach((el, i) => {
    el.classList.toggle("is-active", i === index);
    if (i === index) el.setAttribute("aria-current", "step");
    else el.removeAttribute("aria-current");
  });
}
const stepFor = (m1, m2) => (m2 >= 0.5 ? 2 : m1 >= 0.5 ? 1 : 0);

function showReady() {
  visual.classList.add("is-3d-ready");
  if (ui) ui.hidden = false;
}

if (quality) {
  whenIdle(() =>
    start().catch((err) => {
      console.warn("[hero-3d] disabled:", err);
      fallback();
    })
  );
} else {
  fallback();
}

/** Give the layout back to the static HTML dashboard. */
function fallback() {
  if (visual) visual.classList.remove("will-3d", "is-3d-ready");
}

function whenIdle(fn) {
  const run = () =>
    "requestIdleCallback" in window ? requestIdleCallback(fn, { timeout: 1500 }) : setTimeout(fn, 200);
  if (document.readyState === "complete") run();
  else window.addEventListener("load", run, { once: true });
}

const clamp01 = (v) => Math.min(1, Math.max(0, v));
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/** chaos→D intro, then a slow D ⇄ system loop (period 14s, starting at 5s). */
function morphAt(t) {
  const m1 = ease(clamp01((t - 0.3) / 2.2));
  let m2 = 0;
  if (t > 5) {
    const c = (t - 5) % 14;
    if (c < 2) m2 = ease(c / 2);
    else if (c < 7) m2 = 1;
    else if (c < 9) m2 = 1 - ease((c - 7) / 2);
  }
  return { m1, m2 };
}

async function start() {
  const [THREE, { createParticles }] = await Promise.all([import(THREE_URL), import("./particles.js")]);

  const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: "high-performance" });
  let pixelRatio = Math.min(window.devicePixelRatio || 1, quality.maxPixelRatio);
  renderer.setPixelRatio(pixelRatio);
  renderer.setClearColor(0x000000, 0);
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 50);
  const group = new THREE.Group();
  const points = createParticles(THREE, quality.count);
  const uniforms = points.material.uniforms;
  uniforms.uPixelRatio.value = pixelRatio;
  group.add(points);
  scene.add(group);

  function resize() {
    const w = container.clientWidth || 1;
    const h = container.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // Keep the ~3.9-unit-wide dashboard inside the frame on narrow screens.
    const fit = 3.9 / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.aspect);
    camera.position.z = Math.max(7.2, fit);
    camera.updateProjectionMatrix();
  }
  resize();
  new ResizeObserver(() => {
    resize();
    if (quality.reducedMotion) renderer.render(scene, camera);
  }).observe(container);

  // Reduced motion: one static frame of the finished system, no animation loop.
  if (quality.reducedMotion) {
    uniforms.uMorph1.value = 1;
    uniforms.uMorph2.value = 1;
    group.rotation.y = -0.15;
    renderer.render(scene, camera);
    setStep(2);
    if (toggle) toggle.hidden = true;
    showReady();
    return;
  }

  // Pause / play (WCAG 2.2.2 — looping motion must be stoppable).
  let paused = false;
  if (toggle) {
    toggle.addEventListener("click", () => {
      paused = !paused;
      toggle.setAttribute("aria-pressed", String(paused));
      toggle.textContent = paused ? "הפעלת אנימציה" : "עצירת אנימציה";
      if (!paused) schedule();
    });
  }

  // Pointer parallax (desktop only).
  const pointer = { x: 0, y: 0 };
  if (quality.finePointer) {
    window.addEventListener(
      "pointermove",
      (e) => {
        pointer.x = e.clientX / window.innerWidth - 0.5;
        pointer.y = e.clientY / window.innerHeight - 0.5;
      },
      { passive: true }
    );
  }

  // Only render while the hero is on screen and the tab is visible.
  let onScreen = true;
  new IntersectionObserver(([entry]) => {
    onScreen = entry.isIntersecting;
    if (onScreen) schedule();
  }).observe(hero);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) schedule();
  });

  // Elapsed time that pauses while off-screen (so the intro never replays).
  let elapsed = 0;
  let lastNow = 0;
  let rafId = 0;
  let firstFrame = true;
  let scatter = 0;

  // Adaptive quality: if FPS stays under 45, drop resolution, then particle count.
  let fpsFrames = 0;
  let fpsStart = 0;
  let downgrades = 0;
  function adapt(now) {
    if (elapsed < 3 || downgrades >= 3) return;
    if (!fpsStart) fpsStart = now;
    fpsFrames++;
    const span = now - fpsStart;
    if (span < 2000) return;
    const fps = (fpsFrames * 1000) / span;
    fpsFrames = 0;
    fpsStart = now;
    if (fps >= 45) return;
    downgrades++;
    if (pixelRatio > 1) {
      pixelRatio = 1;
      renderer.setPixelRatio(1);
      uniforms.uPixelRatio.value = 1;
      resize();
    } else {
      const current = points.geometry.drawRange.count;
      const total = current === Infinity ? quality.count : current;
      points.geometry.setDrawRange(0, Math.floor(total * 0.6));
    }
  }

  function schedule() {
    if (!rafId) rafId = requestAnimationFrame(frame);
  }

  function frame(now) {
    rafId = 0;
    if (!onScreen || document.hidden || paused) {
      lastNow = 0;
      fpsStart = 0;
      fpsFrames = 0;
      return;
    }
    if (lastNow) elapsed += Math.min(0.1, (now - lastNow) / 1000);
    lastNow = now;

    const t = elapsed;
    const { m1, m2 } = morphAt(t);
    uniforms.uTime.value = t;
    uniforms.uMorph1.value = m1;
    uniforms.uMorph2.value = m2;
    setStep(stepFor(m1, m2));

    const rect = hero.getBoundingClientRect();
    const target = ease(clamp01(-rect.top / (rect.height * 0.8))) * 0.9;
    scatter += (target - scatter) * 0.08;
    uniforms.uScatter.value = scatter;

    const rotY = -0.18 + Math.sin(t * 0.3) * 0.08 + pointer.x * 0.5;
    const rotX = 0.04 + Math.sin(t * 0.23) * 0.04 + pointer.y * 0.3;
    group.rotation.y += (rotY - group.rotation.y) * 0.05;
    group.rotation.x += (rotX - group.rotation.x) * 0.05;

    renderer.render(scene, camera);
    if (firstFrame) {
      firstFrame = false;
      showReady();
    }
    adapt(now);
    schedule();
  }

  schedule();
}
