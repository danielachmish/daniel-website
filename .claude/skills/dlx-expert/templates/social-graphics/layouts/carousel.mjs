// Carousel (feed-4x5 slides). Rendered as ONE wide canvas and cut into slides: the lit shelf runs through every
// slide and the brand's slanted bars straddle each slide edge, so swiping feels like one object.
// Every slide has the logo, an eyebrow, a counter and (except the last) a "next" cue. Vary the slide kinds:
//   cover:   {eyebrow, headline:[..], products:[..] (middle = hero), sub}
//   overlap: {eyebrow, title, sub?, items:[{product, spec, name}] x2}  first item in front (hero), second behind
//   range:   {eyebrow, title, items:[{product, spec, name}] x3-4}  same-scale line-up, a label under each
//   compare: {eyebrow, title, items:[{product, spec, name, weight}] x2}  numeral size follows weight (e.g. watts)
//   number:  {eyebrow, value, label, product}   one giant number as the hero
//   cta:     {headline:[..], cta, contact:[..], products:[..]}
import {grain, glow, slashes, logo, product, cta, lines, rich, esc, lineup, eyebrow} from './_shared.mjs';

export default (ctx) => {
  const {fmt, data: d} = ctx; const W = fmt.w, H = fmt.h; const n = d.slides.length; const TW = W * n;
  const L = Math.round(fmt.safe.left * W), R = Math.round(fmt.safe.right * W), T = Math.round(fmt.safe.top * H), B = Math.round(fmt.safe.bottom * H);
  const shelf = Math.round(H * 0.74);
  const decor = `<div class="canvas" style="left:0;width:${TW}px">
    <div data-role="decor" style="position:absolute;inset:0;background:linear-gradient(180deg,var(--bg) 0%,var(--surface) 70%,var(--bg) 100%)"></div>
    ${d.slides.map((_, i) => glow({x: i * W + W / 2, y: shelf - 280, r: 520, a: 0.30})).join('')}
    ${d.slides.slice(1).map((_, i) => slashes({x: (i + 1) * W - 120, y: shelf - 60, h: 120, opacity: 0.9})).join('')}
    <div data-role="decor" style="position:absolute;left:0;width:${TW}px;top:${shelf}px;height:5px;background:var(--accent);box-shadow:0 0 40px 4px color-mix(in srgb,var(--accent) 45%,transparent)"></div>
    <div data-role="decor" style="position:absolute;left:0;width:${TW}px;top:${shelf + 5}px;bottom:0;background:linear-gradient(180deg,color-mix(in srgb,var(--accent) 12%,var(--bg)),var(--bg) 60%)"></div>
    ${grain()}
  </div>`;
  const NEXT = '<svg data-role="decor" width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M11 5l-7 7 7 7"/></svg>';
  const slide = (s, i) => {
    const head = (eb) => `<div style="position:absolute;top:${T + 6}px;left:${L}px;right:${R}px;display:flex;justify-content:space-between;align-items:center">
      ${eyebrow(eb || '')}${logo(ctx, {h: 42})}</div>`;
    const foot = `<div style="position:absolute;bottom:${B}px;left:${L}px;right:${R}px;display:flex;justify-content:space-between;align-items:center">
      <div class="count" data-role="text" dir="ltr">${i + 1}/${n}</div>
      ${i < n - 1 ? `<div class="next" data-role="text">${rich(d.swipeLabel || 'הבא')}${NEXT}</div>` : ''}</div>`;
    const title = (t, size = 84) => `<h2 data-role="headline" class="h2" style="position:absolute;top:${T + 96}px;right:${R}px;left:${L}px;font-size:${size}px">${rich(t)}</h2>`;
    // label centred under its product; name optional (avoid repeating the same caption twice: put it in s.sub)
    const label = (it, cx, vsize = 76) => `<div style="position:absolute;top:${shelf + 30}px;left:${Math.round(cx - 180)}px;width:360px;text-align:center">
      <div class="iv" dir="ltr" style="font-size:${vsize}px">${esc(it.spec)}</div>${it.name ? `<div class="in" data-role="text">${rich(it.name)}</div>` : ''}</div>`;
    const subline = s.sub ? `<div class="sub2" data-role="text" style="position:absolute;top:${T + 196}px;right:${R}px;left:${L}px">${rich(s.sub)}</div>` : '';
    let body = '';
    if (s.kind === 'cover') {
      body = `${head(s.eyebrow)}
        <h1 data-role="headline" class="hl" style="position:absolute;top:${T + 100}px;right:${R}px;left:${L}px">${lines(s.headline)}</h1>
        ${lineup(ctx, s.products || [], {x0: L + 10, x1: W - R - 10, bottom: shelf, h: 520, dimOthers: 0.88})}
        ${s.sub ? `<div class="sub" data-role="text" style="position:absolute;top:${shelf + 64}px;right:${R}px;left:${L}px">${rich(s.sub)}</div>` : ''}`;
    } else if (s.kind === 'overlap') {
      const [a, b] = s.items;
      body = `${head(s.eyebrow)}${title(s.title)}${subline}
        ${product(ctx, b.product, {h: 600, cx: W * 0.36, bottom: shelf - 26, reflect: false, z: 2, dim: 0.8})}
        ${product(ctx, a.product, {h: 600, cx: W * 0.62, bottom: shelf, reflect: false, z: 3})}
        ${label(b, W * 0.25, 60)}${label(a, W * 0.69, 84)}`;
    } else if (s.kind === 'range') {
      const k = s.items.length; const h = k > 3 ? 400 : 480;
      const ws = s.items.map((it) => h * ctx.dim(it.product).w / ctx.dim(it.product).h);
      const gap = (W - L - R - ws.reduce((p, q) => p + q, 0)) / (k + 1); let x = W - R - gap; // RTL: first item on the right
      body = `${head(s.eyebrow)}${title(s.title)}${subline}` + s.items.map((it, j) => { const cx = x - ws[j] / 2; x -= ws[j] + gap;
        return `${product(ctx, it.product, {h, cx, bottom: shelf, reflect: false, z: 3})}
          <div style="position:absolute;top:${shelf + 30}px;left:${Math.round(cx - 120)}px;width:240px;text-align:center">
            <div class="iv" dir="ltr" style="font-size:64px">${esc(it.spec)}</div>${it.name ? `<div class="in" data-role="text" style="font-size:32px">${rich(it.name)}</div>` : ''}</div>`; }).join('');
    } else if (s.kind === 'compare') {
      const [a, b] = s.items; const mx = Math.max(a.weight || 1, b.weight || 1);
      // the stronger item is the hero: bigger, in front; numerals share one baseline
      const [hi, lo] = (a.weight || 1) >= (b.weight || 1) ? [a, b] : [b, a];
      body = `${head(s.eyebrow)}${title(s.title)}${subline}
        ${product(ctx, lo.product, {h: 500, cx: W * 0.32, bottom: shelf, reflect: false, z: 2, dim: 0.88})}
        ${product(ctx, hi.product, {h: 620, cx: W * 0.64, bottom: shelf, reflect: false, z: 3})}
        ${label(lo, W * 0.30, 76)}${label(hi, W * 0.66, 96)}`;
    } else if (s.kind === 'number') {
      body = `${head(s.eyebrow)}
        <div class="big" data-role="headline" dir="ltr" style="position:absolute;top:${T + 90}px;right:${R}px">${esc(s.value)}</div>
        <div class="biglabel" data-role="text" style="position:absolute;top:${T + 380}px;right:${R}px;width:${W * 0.46}px">${rich(s.label)}</div>
        ${product(ctx, s.product, {h: Math.min(640, Math.round(ctx.dim(s.product).h * 1.1)), cx: L + 230, bottom: shelf, reflect: false, z: 3})}
        ${s.note ? `<div class="sub" data-role="text" style="position:absolute;top:${shelf + 64}px;right:${R}px;left:${L}px;text-align:center">${rich(s.note)}</div>` : ''}`;
    } else if (s.kind === 'cta') {
      body = `<div style="position:absolute;top:${T + 60}px;left:${L}px;right:${R}px;display:flex;justify-content:center">${logo(ctx, {h: 64})}</div>
        <h1 data-role="headline" class="hl" style="position:absolute;top:${T + 180}px;right:${R}px;left:${L}px;text-align:center">${lines(s.headline)}</h1>
        <div style="position:absolute;top:${T + 420}px;left:${L}px;right:${R}px;display:flex;justify-content:center">${cta(s.cta || '', {size: 46})}</div>
        ${lineup(ctx, s.products || [], {x0: L + 40, x1: W - R - 40, bottom: shelf, h: 360, dimOthers: 0.88})}
        <div class="contact" style="position:absolute;top:${shelf + 40}px;left:${L}px;right:${R}px">${(s.contact || []).map((c) => `<div data-role="text" dir="ltr">${esc(c)}</div>`).join('')}</div>`;
    }
    return `<div class="canvas slide" style="left:${i * W}px;background:transparent"><div class="layer">${body}${foot}</div></div>`;
  };
  const html = decor + d.slides.map(slide).join('');
  const css = `.slide{overflow:hidden}
    .count{font-weight:700;font-size:34px;color:var(--text);border:2px solid color-mix(in srgb,var(--text) 35%,transparent);border-radius:999px;padding:8px 22px 10px}
    .next{display:flex;align-items:center;gap:12px;font-weight:800;font-size:38px;color:var(--on-accent);background:var(--accent);border-radius:999px;padding:10px 24px 12px}
    .hl{font-weight:900;font-size:100px;line-height:1.02;letter-spacing:-.01em}
    .h2{font-weight:900;line-height:1.05}
    .sub{font-weight:700;font-size:40px;color:var(--text)}
    .iv{font-weight:900;line-height:1;color:var(--accent)}
    .in{font-weight:600;font-size:36px;margin-top:10px}
    .sub2{font-weight:600;font-size:38px;color:var(--muted)}
    .big{margin-right:12px;font-weight:900;font-size:250px;line-height:.85;letter-spacing:-.04em;color:var(--accent)}
    .biglabel{font-weight:800;font-size:56px;line-height:1.12;text-align:right}
    .contact{display:flex;justify-content:center;gap:56px;font-weight:800;font-size:46px;color:var(--text)}`;
  return {html, css, slides: n};
};
