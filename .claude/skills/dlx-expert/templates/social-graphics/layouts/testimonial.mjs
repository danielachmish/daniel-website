// Testimonial / quote post (feed-4x5). Only a REAL quote with the person's permission. Until then the template
// shows a visible [placeholder]; never write a quote "in the client's voice" and never use a stock face as the customer.
// Design the slot for 2-3 lines (about 12 words): longer quotes go in the caption.
// data: {eyebrow, quote, name, role, product?, cta?}
import {grain, glow, logo, product, cta, rich, eyebrow} from './_shared.mjs';

export default (ctx) => {
  const {fmt, data: d} = ctx; const W = fmt.w, H = fmt.h;
  const L = Math.round(fmt.safe.left * W), R = Math.round(fmt.safe.right * W), T = Math.round(fmt.safe.top * H), B = Math.round(fmt.safe.bottom * H);
  const qlen = (d.quote || '').length; const qs = qlen > 90 ? 64 : qlen > 60 ? 74 : 84;
  const pcx = L + 190, floor = H - B - 10;
  const html = `<div class="canvas" style="left:0">
    <div data-role="decor" style="position:absolute;inset:0;background:radial-gradient(110% 70% at 85% 10%, var(--surface) 0%, var(--bg) 65%)"></div>
    ${d.product ? glow({x: pcx, y: floor - 280, r: 380, a: 0.42}) : ''}
    <div data-role="decor" style="position:absolute;left:${pcx - 230}px;width:460px;top:${floor}px;height:3px;background:linear-gradient(90deg,transparent,color-mix(in srgb,var(--accent) 55%,transparent),transparent)"></div>
    ${grain()}
    ${d.product ? product(ctx, d.product, {h: Math.min(600, Math.round(ctx.dim(d.product).h * 1.0)), cx: pcx, bottom: floor, reflect: false}) : ''}
    <div class="layer">
      <div style="position:absolute;top:${T + 6}px;left:${L}px;right:${R}px;display:flex;justify-content:space-between;align-items:center">
        ${eyebrow(d.eyebrow || '')}${logo(ctx, {h: 44})}</div>
      <div style="position:absolute;top:${T + 120}px;right:${R}px;left:${L}px">
        <svg data-role="decor" width="150" height="118" viewBox="0 0 190 150" style="display:block;margin-bottom:36px;transform:rotate(180deg)">
          <path fill="var(--accent)" d="M0 150V88C0 38 26 8 78 0l8 22C58 32 46 52 46 78h38v72zM104 150V88c0-50 26-80 78-88l8 22c-28 10-40 30-40 56h38v72z"/></svg>
        <blockquote data-role="headline" class="q" style="font-size:${qs}px">${rich(d.quote || '')}</blockquote>
      </div>
      <div style="position:absolute;bottom:${B + 20}px;right:${R}px;width:${W - L - R - (d.product ? 420 : 0)}px">
        <div class="bar" data-role="decor"></div>
        <div class="name" data-role="text">${rich(d.name || '')}</div>
        <div class="role" data-role="text">${rich(d.role || '')}</div>
        ${d.cta ? `<div style="margin-top:44px;display:flex">${cta(d.cta, {size: 38})}</div>` : ''}
      </div>
    </div></div>`;
  const css = `.q{font-weight:800;line-height:1.16;letter-spacing:-.005em}
    .bar{width:110px;height:6px;background:var(--accent);margin-bottom:26px}
    .name{font-weight:800;font-size:46px}
    .role{font-weight:500;font-size:36px;color:var(--muted);margin-top:6px}`;
  return {html, css};
};
