// Story / Reels (story-9x16 or story-tiktok). All text and the logo inside the safe zone. Products stand on the
// brand's slanted bars and may extend into the bottom UI zone; text may not.
// data: {eyebrow, headline:[..], products:[right, HERO, left] (1-3), cta}. Hero large and tilted in front, others staggered behind.
import {grain, glow, slashes, logo, product, cta, lines, eyebrow} from './_shared.mjs';

export default (ctx) => {
  const {fmt, data: d} = ctx; const W = fmt.w, H = fmt.h;
  const L = Math.round(fmt.safe.left * W), R = Math.round(fmt.safe.right * W), T = Math.round(fmt.safe.top * H);
  const SB = Math.round(H * (1 - fmt.safe.bottom)); // last y for text
  const ps = d.products || []; const floor = SB + 200; const cx = (L + (W - R)) / 2;
  const html = `<div class="canvas" style="left:0">
    <div data-role="decor" style="position:absolute;inset:0;background:linear-gradient(180deg,var(--bg) 0%,var(--surface) 55%,var(--bg) 100%)"></div>
    ${slashes({x: cx - 420, y: floor - 560, h: H - (floor - 470) + 40, opacity: 1})}
    <div data-role="decor" style="position:absolute;left:0;right:0;top:${floor - 560}px;bottom:0;background:linear-gradient(180deg,transparent 0%,transparent 45%,color-mix(in srgb,var(--bg) 70%,transparent) 100%)"></div>
    ${glow({x: cx, y: floor - 250, r: 420, color: '#000', a: 0.45})}
    ${grain()}
    ${ps.length > 1 ? product(ctx, ps[0], {h: 480, cx: cx + 255, bottom: floor - 50, reflect: false, z: 2, rot: 6, dim: 0.85}) : ''}
    ${ps.length > 2 ? product(ctx, ps[2], {h: 480, cx: cx - 255, bottom: floor - 50, reflect: false, z: 2, rot: -6, dim: 0.85}) : ''}
    ${ps.length ? product(ctx, ps[ps.length > 1 ? 1 : 0], {h: Math.min(560, Math.round(ctx.dim(ps[ps.length > 1 ? 1 : 0]).h * 1.1)), cx, bottom: floor + 20, reflect: true, z: 4, rot: -4}) : ''}
    <div class="layer" style="text-align:center">
      <div style="position:absolute;top:${T + 36}px;left:${L}px;right:${R}px;display:flex;justify-content:center">${logo(ctx, {h: 50})}</div>
      <div style="position:absolute;top:${T + 124}px;left:${L}px;right:${R}px;display:flex;justify-content:center">${eyebrow(d.eyebrow || '', {size: 42})}</div>
      <h1 data-role="headline" class="hl" style="position:absolute;top:${T + 190}px;left:${L}px;right:${R}px">${lines(d.headline)}</h1>
      <div style="position:absolute;top:${T + 480}px;left:${L}px;right:${R}px;display:flex;justify-content:center">${cta(d.cta || '', {size: 46})}</div>
    </div></div>`;
  const css = `.hl{font-weight:900;font-size:128px;line-height:1.0;letter-spacing:-.01em}`;
  return {html, css};
};
