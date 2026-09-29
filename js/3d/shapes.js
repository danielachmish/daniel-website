/**
 * shapes.js — the three "states" every particle moves between:
 *   chaos  → scattered data
 *   logo   → the DANIEL "D" monogram (same path as the SVG logo)
 *   system → an abstract dashboard (cards, chart bars, rows)
 * Each function returns a Float32Array of xyz triplets, n points long.
 */

// Same path as the logo mark in index.html (64×64 viewBox).
const D_PATH =
  "M20 14 H33 C42.5 14 50 21.5 50 32 C50 42.5 42.5 50 33 50 H20 V33 H28 V42 H33 C37.5 42 42 38 42 32 C42 26 37.5 22 33 22 H28 V28 H20 Z";

export function chaosPositions(n, rand) {
  const out = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const u = rand() * 2 - 1;
    const theta = rand() * Math.PI * 2;
    const r = 1.6 + Math.pow(rand(), 0.6) * 2.8;
    const s = Math.sqrt(1 - u * u);
    out[i * 3] = r * s * Math.cos(theta) * 1.25;
    out[i * 3 + 1] = r * s * Math.sin(theta) * 0.85;
    out[i * 3 + 2] = r * u * 0.9;
  }
  return out;
}

export function logoPositions(n, rand) {
  const S = 256;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = S;
  const ctx = canvas.getContext("2d");
  ctx.scale(S / 64, S / 64);
  ctx.fill(new Path2D(D_PATH));
  const data = ctx.getImageData(0, 0, S, S).data;

  const filled = [];
  for (let y = 0; y < S; y++) {
    for (let x = 0; x < S; x++) {
      if (data[(y * S + x) * 4 + 3] > 128) filled.push(x, y);
    }
  }

  // The D spans x 20..50 and y 14..50 in the 64 box — center it, 2.6 units tall.
  const scale = 2.6 / 36;
  const out = new Float32Array(n * 3);
  const count = filled.length / 2;
  for (let i = 0; i < n; i++) {
    const k = Math.floor(rand() * count) * 2;
    const px = ((filled[k] + rand()) / S) * 64;
    const py = ((filled[k + 1] + rand()) / S) * 64;
    out[i * 3] = (px - 35) * scale;
    out[i * 3 + 1] = -(py - 32) * scale;
    out[i * 3 + 2] = (rand() - 0.5) * 0.3;
  }
  return out;
}

export function systemPositions(n, rand) {
  // Rects: [cx, cy, w, h, mode, zDepth]. mode "o" = outline, "f" = fill.
  const rects = [
    [0, 0, 3.4, 2.5, "o", -0.05],        // window frame
    [0, 1.0, 3.1, 0.02, "f", 0],         // top bar divider
    [1.45, 1.12, 0.06, 0.06, "f", 0],    // window dots
    [1.33, 1.12, 0.06, 0.06, "f", 0],
    [1.21, 1.12, 0.06, 0.06, "f", 0],
    [0.8, 0.55, 1.45, 0.55, "o", 0.05],  // KPI card
    [0.95, 0.5, 0.6, 0.12, "f", 0.08],
    [-0.8, 0.55, 1.45, 0.55, "o", 0.05], // KPI card
    [-0.65, 0.5, 0.6, 0.12, "f", 0.08],
    [0, -0.2, 3.05, 0.75, "o", 0.02],    // chart card
    [0, -0.78, 2.8, 0.03, "f", 0],       // rows
    [0, -0.93, 2.8, 0.03, "f", 0],
    [0, -1.08, 2.8, 0.03, "f", 0],
    [-1.2, -0.78, 0.25, 0.07, "f", 0.04],// status pills
    [-1.2, -0.93, 0.25, 0.07, "f", 0.04],
    [-1.2, -1.08, 0.25, 0.07, "f", 0.04]
  ];
  const bars = [0.35, 0.55, 0.4, 0.7, 0.5, 0.85, 0.6, 0.95];
  bars.forEach((h, i) => {
    const bh = h * 0.55;
    rects.push([-1.19 + i * 0.34, -0.52 + bh / 2, 0.16, bh, "f", 0.12]);
  });

  const weights = rects.map(([, , w, h, mode]) =>
    mode === "o" ? 2 * (w + h) * 0.12 : w * h * 1.2 + 0.02
  );
  const total = weights.reduce((a, b) => a + b, 0);
  const cumulative = [];
  weights.reduce((acc, w, i) => (cumulative[i] = acc + w / total), 0);

  const out = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const r = rand();
    let idx = cumulative.findIndex((c) => r <= c);
    if (idx < 0) idx = rects.length - 1;
    const [cx, cy, w, h, mode, z] = rects[idx];
    let x, y;
    if (mode === "f") {
      x = cx + (rand() - 0.5) * w;
      y = cy + (rand() - 0.5) * h;
    } else {
      const t = rand() * 2 * (w + h);
      if (t < w) { x = cx - w / 2 + t; y = cy + h / 2; }
      else if (t < w + h) { x = cx + w / 2; y = cy + h / 2 - (t - w); }
      else if (t < 2 * w + h) { x = cx + w / 2 - (t - w - h); y = cy - h / 2; }
      else { x = cx - w / 2; y = cy - h / 2 + (t - 2 * w - h); }
      x += (rand() - 0.5) * 0.03;
      y += (rand() - 0.5) * 0.03;
    }
    out[i * 3] = x;
    out[i * 3 + 1] = y;
    out[i * 3 + 2] = z + (rand() - 0.5) * 0.06;
  }
  return out;
}

/** Small deterministic PRNG so the formation is identical on every load. */
export function seededRandom(seed) {
  let s = seed >>> 0;
  return function () {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
