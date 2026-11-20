// Promo / sale post (feed-4x5). Accent background, one giant offer, products straddling a dark shelf, deadline + CTA.
// data: {eyebrow, value, valueLabel, offerLine, products:[..] (1-3, middle = hero), deadline, cta, legal}
// Never invent an offer. An unconfirmed value is passed as {"value":"XX%","pending":true}: it renders as a dotted
// placeholder slot with a [לאשר] tag, so nobody can publish "XX%" by accident.
import {grain, glow, slashes, logo, cta, rich, esc, lineup, eyebrow} from './_shared.mjs';

export default (ctx) => {
  const {fmt, data: d} = ctx; const W = fmt.w, H = fmt.h;
  const L = Math.round(fmt.safe.left * W), R = Math.round(fmt.safe.right * W), T = Math.round(fmt.safe.top * H), B = Math.round(fmt.safe.bottom * H);
  const shelf = Math.round(H * 0.565); const floor = H - B - 140;
  const html = `<div class="canvas" style="left:0;background:var(--accent)">
    ${slashes({x: -160, y: -80, h: 820, color: 'var(--bg)', opacity: 0.07})}
    <div data-role="decor" style="position:absolute;left:0;right:0;top:${shelf - 70}px;bottom:0;background:var(--bg);clip-path:polygon(0 140px,100% 0,100% 100%,0 100%)"></div>
    <div data-role="decor" style="position:absolute;left:0;right:0;top:${shelf - 70}px;bottom:0;clip-path:polygon(0 140px,100% 0,100% 100%,0 100%);
      background:radial-gradient(70% 55% at 50% 50%, color-mix(in srgb,var(--accent) 26%,transparent), transparent 70%)"></div>
    <div data-role="decor" style="position:absolute;left:${L}px;right:${R}px;top:${floor}px;height:3px;background:linear-gradient(90deg,transparent,var(--accent),transparent);opacity:.8"></div>
    ${grain(0.05)}
    ${(d.products || []).map((_, i, a) => glow({x: L + (W - L - R) * (i + 0.5) / a.length, y: floor, r: 170, a: 0.35})).join('')}
    ${lineup(ctx, d.products || [], {x0: L, x1: W - R, bottom: floor, h: 500, dimOthers: 0.9})}
    <div class="layer">
      <div style="position:absolute;top:${T + 6}px;left:${L}px;right:${R}px;display:flex;justify-content:space-between;align-items:center">
        ${eyebrow(d.eyebrow || '', {color: 'var(--on-accent)'})}${logo(ctx, {h: 44, mono: 'dark'})}</div>
      <div style="position:absolute;top:${T + 150}px;right:${R + 14}px;left:${L}px;display:flex;align-items:flex-end;gap:44px">
        <div class="value ${d.pending ? 'pending' : ''}" data-role="headline" dir="ltr">${esc(d.value || '')}${d.pending ? '<span class="ptag" data-role="text">[לאשר]</span>' : ''}</div>
        <div class="vlabel" data-role="headline">${rich(d.valueLabel || '')}</div></div>
      <div class="offer" data-role="text" style="position:absolute;top:${T + 432}px;right:${R}px;left:${L}px">${rich(d.offerLine || '')}</div>
      <div style="position:absolute;bottom:${B}px;left:${L}px;right:${R}px;display:flex;justify-content:space-between;align-items:center">
        <div class="deadline" data-role="text">${rich([d.deadline, d.legal].filter(Boolean).join(' · '))}</div>${cta(d.cta || '', {size: 40})}</div>
    </div></div>`;
  const css = `.value{position:relative;font-weight:900;font-size:270px;line-height:.82;letter-spacing:-.04em;color:var(--on-accent)}
    .value.pending{outline:5px dashed var(--on-accent);outline-offset:12px;border-radius:6px}
    .ptag{position:absolute;top:-72px;left:-12px;background:var(--bg);color:var(--accent);font-size:32px;letter-spacing:0;font-weight:800;line-height:1;padding:10px 16px 12px;border-radius:999px}
    .vlabel{font-weight:900;font-size:88px;line-height:1;color:var(--on-accent);margin-bottom:-6px}
    .offer{font-weight:800;font-size:50px;line-height:1.15;color:var(--on-accent)}
    .deadline{font-weight:700;font-size:36px;color:var(--text)}
    .legal{font-weight:500;font-size:32px;color:var(--text);opacity:1}`;
  return {html, css};
};
