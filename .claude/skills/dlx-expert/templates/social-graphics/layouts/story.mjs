// Story / Reels (story-9x16 or story-tiktok). All text and the logo inside the safe zone. Products stand on the
// brand's slanted bars and may extend into the bottom UI zone; text may not.
// data: {eyebrow, headline:[..], products:[right, HERO, left] (1-3), cta}. Hero large and tilted in front, others staggered behind.
import {grain, glow, slashes, logo, product, cta, lines, rich, eyebrow} from './_shared.mjs';

export default (ctx) => {
  const {fmt, data: d} = ctx; const W = fmt.w, H = fmt.h;
  const L = Math.round(fmt.safe.left * W), R = Math.round(fmt.safe.right * W), T = Math.round(fmt.safe.top * H);
  const SB = Math.round(H * (1 - fmt.safe.bottom)); // last y for text
  const ps = d.products || []; const floor = SB - 130; const cx = (L + (W - R)) / 2; const ph = 510;
  // reading order: headline -> products -> CTA. Same scale for every pack; depth from offset, overlap and light.
  const html = `<div class="canvas" style="left:0">
    <div data-role="decor" style="position:absolute;inset:0;background:linear-gradient(180deg,var(--bg) 0%,var(--surface) 55%,var(--bg) 100%)"></div>
    ${slashes({x: cx - 400 - (H - floor) * 0.78, y: floor - 480, h: H - floor + 500, bw: 225, gapPx: 190, opacity: 1, fade: 0.3})}
    <div data-role="decor" style="position:absolute;left:0;right:0;top:${floor + 140}px;bottom:0;background:linear-gradient(180deg,transparent 0%,color-mix(in srgb,var(--bg) 55%,transparent) 100%)"></div>
    ${grain()}
    ${ps.length > 1 ? product(ctx, ps[0], {h: ph - 40, cx: cx + 290, bottom: floor - 25, reflect: false, z: 2, rot: 5, dim: 0.75}) : ''}
    ${ps.length > 2 ? product(ctx, ps[2], {h: ph - 40, cx: cx - 290, bottom: floor - 25, reflect: false, z: 2, rot: -5, dim: 0.75}) : ''}
    ${ps.length ? product(ctx, ps[ps.length > 1 ? 1 : 0], {h: ph, cx, bottom: floor, reflect: false, z: 4}) : ''}
    <div class="layer" style="text-align:center">
      <div style="position:absolute;top:${T + 16}px;left:${L}px;right:${R}px;display:flex;justify-content:center">${logo(ctx, {h: 50})}</div>
      <div style="position:absolute;top:${T + 82}px;left:${L}px;right:${R}px;display:flex;justify-content:center">${eyebrow(d.eyebrow || '', {size: 42})}</div>
      <h1 data-role="headline" class="hl" style="position:absolute;top:${T + 140}px;left:${L}px;right:${R}px">${lines(d.headline)}</h1>
      <div style="position:absolute;top:${floor + 24}px;left:${L}px;right:${R}px;display:flex;justify-content:center">${cta(d.cta || '', {size: 44, variant: 'dark', style: 'border:3px solid var(--accent)'})}</div>
    </div></div>`;
  const css = `.hl{font-weight:900;font-size:100px;line-height:1.0;letter-spacing:-.01em} .foot{font-weight:600;font-size:40px;color:var(--text)}`;
  return {html, css};
};
