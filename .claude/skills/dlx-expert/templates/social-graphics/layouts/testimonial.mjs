// Testimonial / quote post (feed-4x5). Only a REAL quote with the person's permission. Until then the template
// shows a visible [placeholder]; never write a quote "in the client's voice", never add star ratings that were not
// given, and never use a stock face as the customer. Design the slot for 1-3 lines (about 12 words).
// data: {eyebrow, quote, name, role, product?, cta?, variant?: 'dark'|'accent'}  accent = lime background (breaks a run
// of dark posts in the feed).
import {grain, glow, slashes, logo, product, cta, rich, eyebrow} from './_shared.mjs';

export default (ctx) => {
  const {fmt, data: d} = ctx; const W = fmt.w, H = fmt.h;
  const L = Math.round(fmt.safe.left * W), R = Math.round(fmt.safe.right * W), T = Math.round(fmt.safe.top * H), B = Math.round(fmt.safe.bottom * H);
  const acc = d.variant === 'accent'; const ink = acc ? 'var(--on-accent)' : 'var(--text)';
  const qlen = (d.quote || '').length; const qs = /^\[.*\]$/.test(d.quote || '') ? 70 : qlen > 90 ? 64 : qlen > 60 ? 74 : qlen > 30 ? 84 : 96;
  const pcx = L + 200, floor = H - B - 10; // product bottom-left, CTA bottom-right on the same floor
  const ph = d.product ? Math.min(500, Math.round(ctx.dim(d.product).h)) : 0;
  const html = `<div class="canvas" style="left:0;background:${acc ? 'var(--accent)' : 'var(--bg)'}">
    ${acc ? `<div data-role="decor" style="position:absolute;left:0;right:0;top:${floor - ph - 60}px;bottom:0;background:var(--bg);clip-path:polygon(0 0,52% 0,40% 100%,0 100%)"></div>`
          : `<div data-role="decor" style="position:absolute;inset:0;background:radial-gradient(110% 70% at 85% 10%, var(--surface) 0%, var(--bg) 65%)"></div>
             ${d.product ? glow({x: pcx, y: floor - 280, r: 380, a: 0.42}) : ''}`}
    ${acc ? '' : slashes({x: W - R - 250, y: floor - 330, h: 150, opacity: 0.12})}
    ${grain(acc ? 0.05 : 0.07)}
    ${d.product ? product(ctx, d.product, {h: ph, cx: pcx, bottom: floor, reflect: false}) : ''}
    <div class="layer" style="color:${ink}">
      <div style="position:absolute;top:${T + 6}px;left:${L}px;right:${R}px;display:flex;justify-content:space-between;align-items:center">
        ${eyebrow(d.eyebrow || '', {color: acc ? 'var(--on-accent)' : 'var(--accent)'})}${logo(ctx, {h: 44, mono: acc ? 'dark' : null})}</div>
      <div style="position:absolute;top:${T + 120}px;right:${R}px;left:${L}px">
        <svg data-role="decor" width="150" height="118" viewBox="0 0 190 150" style="display:block;margin-bottom:36px;transform:rotate(180deg)">
          <path fill="${acc ? 'var(--on-accent)' : 'var(--accent)'}" d="M0 150V88C0 38 26 8 78 0l8 22C58 32 46 52 46 78h38v72zM104 150V88c0-50 26-80 78-88l8 22c-28 10-40 30-40 56h38v72z"/></svg>
        <blockquote data-role="headline" class="q ${/^\[.*\]$/.test(d.quote || '') ? 'slot' : ''}" style="font-size:${qs}px">${rich(d.quote || '')}</blockquote>
        <div class="bar" data-role="decor" style="background:${acc ? 'var(--on-accent)' : 'var(--accent)'}"></div>
        <div class="name" data-role="text">${rich(d.name || '')}</div>
        <div class="role" data-role="text" style="color:${acc ? 'var(--on-accent)' : 'var(--muted)'}">${rich(d.role || '')}</div>
      </div>
      ${d.cta ? `<div style="position:absolute;bottom:${B + 10}px;right:${R}px;display:flex">${cta(d.cta, {size: 40, variant: acc ? 'dark' : 'accent'})}</div>` : ''}
    </div></div>`;
  const css = `.q{font-weight:800;line-height:1.16;letter-spacing:-.005em}
    .q.slot{border:4px dashed currentColor;border-radius:8px;padding:22px 30px 24px;min-height:3.6em}
    .bar{width:110px;height:6px;margin:40px 0 22px}
    .name{font-weight:800;font-size:46px}
    .role{font-weight:600;font-size:38px;margin-top:6px}`;
  return {html, css};
};
