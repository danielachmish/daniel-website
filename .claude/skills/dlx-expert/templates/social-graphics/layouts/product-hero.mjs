// Product hero post (feed-4x5 or square-1x1): one product, one promise, spec callouts, one CTA.
// data: {eyebrow, headline:[line,line], product, productH?, specs:[{value,label}] (max 3), cta, footer}
import {grain, glow, logo, product, cta, lines, rich, esc, eyebrow} from './_shared.mjs';

export default (ctx) => {
  const {fmt, data: d} = ctx; const W = fmt.w, H = fmt.h;
  const L = Math.round(fmt.safe.left * W), R = Math.round(fmt.safe.right * W), T = Math.round(fmt.safe.top * H), B = Math.round(fmt.safe.bottom * H);
  const sq = H / W < 1.1;
  const nat = ctx.dim(d.product).h;
  const pH = d.productH || Math.min(sq ? 560 : 700, Math.round(nat * 1.1)); // never past 1.1x the real photo (soft)
  const floor = H - B - (sq ? 140 : 150);
  const pcx = Math.round(W * 0.34);
  const specs = (d.specs || []).slice(0, 3);
  const html = `<div class="canvas" style="left:0">
    <div data-role="decor" style="position:absolute;inset:0;background:radial-gradient(120% 80% at 30% 62%, var(--surface) 0%, var(--bg) 70%)"></div>
    ${glow({x: pcx, y: floor - pH * 0.5, r: pH * 0.66, a: 0.32})}
    <div data-role="decor" style="position:absolute;left:0;right:0;top:${floor}px;height:2px;background:linear-gradient(90deg,transparent,color-mix(in srgb,var(--accent) 55%,transparent),transparent)"></div>
    ${grain()}
    ${product(ctx, d.product, {h: pH, cx: pcx, bottom: floor})}
    <div class="layer">
      <div style="position:absolute;top:${T + 6}px;right:${R}px;left:${L}px;display:flex;justify-content:space-between;align-items:center">
        ${eyebrow(d.eyebrow || '')}${logo(ctx, {h: 46})}</div>
      <h1 data-role="headline" class="hl" style="position:absolute;top:${T + 92}px;right:${R}px;left:${L}px">${lines(d.headline)}</h1>
      <div class="specs" style="position:absolute;right:${R}px;bottom:${H - floor}px;width:${Math.round(W * 0.34)}px">
        ${specs.map((s) => `<div class="spec"><div class="v" dir="ltr">${esc(s.value)}</div><div class="k" data-role="text">${rich(s.label)}</div></div>`).join('')}
      </div>
      <div style="position:absolute;bottom:${B}px;right:${R}px;left:${L}px;display:flex;justify-content:space-between;align-items:center">
        ${cta(d.cta || '', {size: 40})}
        <div class="foot" data-role="text">${rich(d.footer || '')}</div>
      </div>
    </div></div>`;
  const css = `
    .hl{font-weight:900;font-size:${sq ? 92 : 108}px;line-height:1.02;letter-spacing:-.01em}
    .spec{padding:24px 0 26px;border-top:2px solid color-mix(in srgb,var(--text) 18%,transparent);text-align:right}
    .spec .v{font-weight:900;font-size:${sq ? 64 : 72}px;line-height:1;color:var(--accent);text-align:right}
    .spec .k{font-weight:500;font-size:36px;line-height:1.15;margin-top:10px;color:var(--text)}
    .foot{font-weight:600;font-size:34px;color:var(--muted)}`;
  return {html, css};
};
