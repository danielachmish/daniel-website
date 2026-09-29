/**
 * quality.js — decides whether the 3D hero runs at all, and at what budget.
 * Returns null when 3D should be skipped (no WebGL, Save-Data), so the page
 * keeps the static HTML dashboard exactly as it is.
 */
export function detectQuality() {
  const nav = navigator;
  if (nav.connection && nav.connection.saveData) return null;

  let gl = null;
  try {
    const canvas = document.createElement("canvas");
    gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
  } catch (e) {
    gl = null;
  }
  if (!gl) return null;
  const lose = gl.getExtension("WEBGL_lose_context");
  if (lose) lose.loseContext();

  const cores = nav.hardwareConcurrency || 4;
  const memory = nav.deviceMemory || 4;
  const mobile =
    matchMedia("(max-width: 900px)").matches || matchMedia("(pointer: coarse)").matches;

  let tier = "high";
  if (cores <= 2 || memory <= 2) tier = "low";
  else if (mobile || cores <= 4) tier = "mid";

  const counts = { high: 9000, mid: 5000, low: 2500 };

  return {
    tier,
    count: counts[tier],
    maxPixelRatio: mobile ? 1.5 : 2,
    reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
    finePointer: matchMedia("(pointer: fine)").matches
  };
}
