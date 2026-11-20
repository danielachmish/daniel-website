// Website hero banner. banner-web (1920x800) / landscape-191: text column on the start side (right, RTL), product
// line-up on a lit shelf on the other side. Portrait formats (feed-4x5, square) render the MOBILE version of the same
// banner: stacked, no sub-line. Always deliver both.
// data: {eyebrow, headline:[..], sub, products:[..] (middle = hero), cta, footer}
import {grain, glow, slashes, logo, product, cta, lines, rich, lineup, eyebrow} from './_shared.mjs';

export default (ctx) => {
  const {fmt, data: d} = ctx; const W = fmt.w, H = fmt.h;
  const L = Math.round(fmt.safe.left * W), R = Math.round(fmt.safe.right * W), T = Math.round(fmt.safe.top * H), B = Math.round(fmt.safe.bottom * H);
  const ps = d.products || [];
  if (H / W >= 0.95) { // mobile / portrait version of the SAME banner: products on top, words below, no sub-line
    const floor = T + 700; const hp = ps.slice(0, 3);
    const html = `<div class="canvas" style="left:0">
      <div data-role="decor" style="position:absolute;inset:0;background:radial-gradient(90% 55% at 50% 35%, var(--surface) 0%, var(--bg) 70%)"></div>
      ${slashes({x: W / 2 - 460, y: floor - 520, h: 560, bw: 218, gapPx: 187, opacity: 1, fade: 0.35})}
      <div data-role="decor" style="position:absolute;left:0;right:0;top:${floor}px;bottom:0;background:var(--bg)"></div>
      <div data-role="decor" style="position:absolute;left:${L}px;right:${R}px;top:${floor}px;height:4px;background:linear-gradient(90deg,transparent,var(--accent) 25%,var(--accent) 75%,transparent)"></div>
      ${grain()}
      ${hp.length > 1 ? product(ctx, hp[0], {h: 500, cx: W / 2 + 290, bottom: floor - 40, reflect: false, z: 2, dim: 0.72}) : ''}
      ${hp.length > 2 ? product(ctx, hp[2], {h: 500, cx: W / 2 - 290, bottom: floor - 40, reflect: false, z: 2, dim: 0.72}) : ''}
      ${hp.length ? product(ctx, hp[hp.length > 1 ? 1 : 0], {h: 500, cx: W / 2, bottom: floor + 10, reflect: false, z: 4}) : ''}
      <div class="layer">
        <div style="position:absolute;top:${T + 6}px;left:${L}px;right:${R}px;display:flex;justify-content:space-between;align-items:center">${eyebrow(d.eyebrow || '')}${logo(ctx, {h: 46})}</div>
        <h1 data-role="headline" class="hl" style="position:absolute;top:${floor + 50}px;right:${R}px;left:${L}px;font-size:100px">${lines(d.headline)}</h1>
        <div style="position:absolute;top:${floor + 300}px;right:${R}px;left:${L}px;display:flex;align-items:center;justify-content:space-between">${cta(d.cta || '', {size: 42})}
          ${d.footer ? `<div class="foot" data-role="text">${rich(d.footer)}</div>` : ''}</div>
      </div></div>`;
    return {html, css: `.hl{font-weight:900;line-height:1.02;letter-spacing:-.01em} .foot{font-weight:700;font-size:36px;color:var(--text)}`};
  }
  const k = H / 800;
  const shelf = H - B - Math.round(20 * k); const areaL = L, areaR = W * 0.49;
  const html = `<div class="canvas" style="left:0">
    <div data-role="decor" style="position:absolute;inset:0;background:radial-gradient(70% 90% at 28% 60%, var(--surface) 0%, var(--bg) 70%)"></div>
    ${(() => { const sh = Math.round(420 * k); const sx = Math.min(areaL - 40 * k, W * 0.54 - 40 * k - 1.98 * sh) - (H - shelf) * 0.78; // bars' skew must stay clear of the text column
      return slashes({x: sx, y: shelf - sh, h: H - shelf + sh + 10, bw: sh * 0.42, gapPx: sh * 0.36, opacity: 1}); })()}
    <div data-role="decor" style="position:absolute;left:0;width:${areaR + 200 * k}px;top:0;height:${shelf}px;background:linear-gradient(180deg,var(--bg) 0%,transparent 55%)"></div>
    <div data-role="decor" style="position:absolute;left:0;width:${areaR + 160 * k}px;top:${shelf}px;height:${4 * k}px;background:linear-gradient(90deg,transparent,var(--accent) 20%,var(--accent) 70%,transparent 100%)"></div>
    ${grain()}
    ${lineup(ctx, ps, {x0: areaL, x1: areaR, bottom: shelf, h: Math.round(Math.min(480, 1500 / Math.max(1, ps.length)) * k), dimOthers: 0.88})}
    <div class="layer">
      <div style="position:absolute;top:${T}px;right:${R}px;width:${Math.round(W * 0.44)}px">
        ${d.logo === false ? '' : `<div style="display:flex;justify-content:flex-start;margin-bottom:${28 * k}px">${logo(ctx, {h: Math.round(46 * k)})}</div>`}${eyebrow(d.eyebrow || '', {size: Math.round(32 * k)})}
        <h1 data-role="headline" class="hl" style="margin-top:${14 * k}px">${lines(d.headline)}</h1>
        <p class="sub" data-role="text">${rich(d.sub || '')}</p>
        <div style="display:flex;margin-top:${34 * k}px">${cta(d.cta || '', {size: Math.round(38 * k)})}</div>
        ${d.footer ? `<div class="foot" data-role="text" style="margin-top:${18 * k}px">${rich(d.footer)}</div>` : ''}
      </div>
    </div></div>`;
  const css = `.hl{font-weight:900;font-size:${Math.round(90 * k)}px;line-height:1.02;letter-spacing:-.01em}
    .sub{font-weight:500;font-size:${Math.round(42 * k)}px;line-height:1.3;color:var(--muted);margin-top:${34 * k}px;white-space:nowrap}
    .foot{font-weight:700;font-size:${Math.round(38 * k)}px;color:var(--text)}`;
  return {html, css};
};
