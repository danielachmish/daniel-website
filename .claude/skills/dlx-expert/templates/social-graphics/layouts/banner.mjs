// Website hero banner. banner-web (1920x800) / landscape-191: text column on the start side (right, RTL), product
// line-up on a lit shelf on the other side. Portrait formats (feed-4x5, square) render the MOBILE version of the same
// banner: stacked, no sub-line. Always deliver both.
// data: {eyebrow, headline:[..], sub, products:[..] (middle = hero), cta, footer}
import {grain, glow, slashes, logo, product, cta, lines, rich, lineup, eyebrow} from './_shared.mjs';

export default (ctx) => {
  const {fmt, data: d} = ctx; const W = fmt.w, H = fmt.h;
  const L = Math.round(fmt.safe.left * W), R = Math.round(fmt.safe.right * W), T = Math.round(fmt.safe.top * H), B = Math.round(fmt.safe.bottom * H);
  const ps = d.products || [];
  if (H / W >= 0.95) { // mobile / portrait version: accent background, ONE hero product, no sub-line
    const hero = d.mobileProduct || ps[Math.floor(ps.length / 2)] || ps[0]; const floor = H - B - 10; const hh = Math.min(680, Math.round(ctx.dim(hero).h * 1.1));
    const html = `<div class="canvas" style="left:0;background:var(--accent)">
      ${slashes({x: W - R - 250, y: floor - 210, h: 210, color: 'var(--bg)', opacity: 0.9})}
      ${grain(0.05)}
      <div data-role="decor" style="position:absolute;left:${W * 0.5 - 260}px;width:520px;top:${floor - 30}px;height:60px;border-radius:50%;background:radial-gradient(closest-side,rgba(0,0,0,.45),transparent)"></div>
      ${product(ctx, hero, {h: hh, cx: W * 0.5, bottom: floor, reflect: false, z: 3})}
      <div class="layer">
        <div style="position:absolute;top:${T + 6}px;left:${L}px;right:${R}px;display:flex;justify-content:space-between;align-items:center">${eyebrow(d.eyebrow || '', {color: 'var(--on-accent)'})}${logo(ctx, {h: 46, mono: 'dark'})}</div>
        <h1 data-role="headline" class="hl" style="position:absolute;top:${T + 96}px;right:${R}px;left:${L}px;font-size:100px;color:var(--on-accent)">${lines(d.headline)}</h1>
        <div style="position:absolute;top:${T + 320}px;right:${R}px;display:flex">${cta(d.cta || '', {size: 42, variant: 'dark'})}</div>
      </div></div>`;
    return {html, css: `.hl{font-weight:900;line-height:1.02;letter-spacing:-.01em} .hl em{color:inherit}`};
  }
  const k = H / 800;
  const shelf = H - B - Math.round(20 * k); const areaL = Math.max(L, 240 * k), areaR = W * 0.50;
  const html = `<div class="canvas" style="left:0">
    <div data-role="decor" style="position:absolute;inset:0;background:radial-gradient(70% 90% at 28% 60%, var(--surface) 0%, var(--bg) 70%)"></div>
    ${glow({x: (areaL + areaR) / 2, y: shelf - 220 * k, r: 540 * k, a: 0.30})}
    <div data-role="decor" style="position:absolute;left:0;width:${areaR + 140 * k}px;top:${shelf}px;height:${4 * k}px;background:linear-gradient(90deg,transparent,var(--accent) 30%,var(--accent) 80%,transparent)"></div>
    ${grain()}
    ${lineup(ctx, ps, {x0: areaL, x1: areaR, bottom: shelf, h: Math.round(Math.min(440, 680 / Math.max(1, ps.length) * 2.2) * k), dimOthers: 0.88})}
    <div class="layer">
      <div style="position:absolute;top:${T}px;right:${R}px;width:${Math.round(W * 0.44)}px">
        <div style="display:flex;justify-content:flex-start;margin-bottom:${28 * k}px">${logo(ctx, {h: Math.round(46 * k)})}</div>${eyebrow(d.eyebrow || '', {size: Math.round(32 * k)})}
        <h1 data-role="headline" class="hl" style="margin-top:${14 * k}px">${lines(d.headline)}</h1>
        <p class="sub" data-role="text">${rich(d.sub || '')}</p>
        <div style="display:flex;margin-top:${34 * k}px">${cta(d.cta || '', {size: Math.round(38 * k)})}</div>
        ${d.footer ? `<div class="foot" data-role="text" style="margin-top:${18 * k}px">${rich(d.footer)}</div>` : ''}
      </div>
    </div></div>`;
  const css = `.hl{font-weight:900;font-size:${Math.round(90 * k)}px;line-height:1.02;letter-spacing:-.01em}
    .sub{font-weight:500;font-size:${Math.round(38 * k)}px;line-height:1.3;color:var(--muted);margin-top:${34 * k}px;white-space:nowrap}
    .foot{font-weight:600;font-size:${Math.round(32 * k)}px;color:var(--muted)}`;
  return {html, css};
};
