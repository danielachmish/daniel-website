// Shared building blocks for all layouts. Every visible text must be real text (not an image) so qa_image.py can
// measure it: size, contrast against the real background, and position against the platform safe zone.
// data-role values: headline | text | cta | legal | logo | product | decor.

export const esc = (s = '') => String(s).replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

// Rich text: *word* -> accent colour, `65W` -> isolated left-to-right run (numbers/Latin inside Hebrew lines).
export const rich = (s = '') => esc(s)
  .replace(/`([^`]+)`/g, '<span class="ltr" dir="ltr">$1</span>')
  .replace(/\*([^*]+)\*/g, '<em>$1</em>')
  .replace(/(\[[^\]]+\])/g, '<span class="tbd">$1</span>');   // [לאשר] placeholders stay visibly marked

export const lines = (arr) => (Array.isArray(arr) ? arr : [arr]).map((l) => `<span class="line">${rich(l)}</span>`).join('');

// Film grain under the content (never over text): kills the flat "template" look.
const GRAIN = `url("data:image/svg+xml;utf8,${encodeURIComponent("<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .55 0'/></filter><rect width='100%' height='100%' filter='url(#n)'/></svg>")}")`;
export const grain = (opacity = 0.07) => `<div class="grain" data-role="decor" style="opacity:${opacity};background-image:${GRAIN}"></div>`;

export const glow = ({x, y, r, color = 'var(--accent)', a = 0.28}) =>
  `<div data-role="decor" style="position:absolute;left:${x - r}px;top:${y - r}px;width:${2 * r}px;height:${2 * r}px;border-radius:50%;
   background:radial-gradient(circle, color-mix(in srgb, ${color} ${Math.round(a * 100)}%, transparent) 0%, transparent 68%);"></div>`;

// Brand device taken from the client's own logo (two slanted bars). Override in brand.json -> motif: false to disable.
export const slashes = ({x, y, h, color = 'var(--accent)', opacity = 1, gap = 0.36, w = 0.42}) => {
  const bw = h * w;
  return `<div data-role="decor" style="position:absolute;left:${x}px;top:${y}px;height:${h}px;opacity:${opacity}">
    <div style="position:absolute;left:0;top:0;width:${bw}px;height:${h}px;background:${color};transform:skewX(-38deg);transform-origin:bottom left"></div>
    <div style="position:absolute;left:${bw + h * gap}px;top:0;width:${bw}px;height:${h}px;background:${color};transform:skewX(-38deg);transform-origin:bottom left"></div></div>`;
};

// mono: 'dark' -> solid black logo for light/accent backgrounds (when no onLight file exists).
export const logo = (ctx, {h = 52, style = '', mono = null} = {}) => {
  const src = (mono === 'dark' && ctx.brand.logo?.onLight) || ctx.brand.logo?.onDark;
  if (mono === 'dark' && !ctx.brand.logo?.onLight) style += ';filter:brightness(0)';
  if (!src) return `<div data-role="logo" style="font-weight:900;font-size:${h}px;line-height:1;${style}">${esc(ctx.brand.name)}</div>`;
  return `<img data-role="logo" src="${ctx.asset(src)}" style="height:${h}px;width:auto;display:block;${style}">`;
};

// Real product photo (cut out). Never re-draw or AI-generate the product. Optional floor reflection + contact shadow.
// Position by centre x and floor line (bottom). Width comes from the real image ratio.
export const product = (ctx, src, {h, cx, bottom, reflect = true, shadow = true, z = 2, rot = 0, dim: dimmed = 1}) => {
  const d = ctx.dim(src); const w = Math.round(h * d.w / d.h); const x = Math.round(cx - w / 2); const y = Math.round(bottom - h);
  return `
  <div data-role="decor" style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;z-index:${z};transform:rotate(${rot}deg)">
    ${shadow ? `<div style="position:absolute;left:8%;right:8%;bottom:-${h * 0.035}px;height:${h * 0.07}px;border-radius:50%;background:radial-gradient(closest-side,rgba(0,0,0,.85),transparent);filter:blur(6px)"></div>` : ''}
    <img data-role="product" src="${ctx.asset(src)}" style="height:${h}px;width:auto;display:block;position:relative;filter:drop-shadow(0 ${h * 0.03}px ${h * 0.05}px rgba(0,0,0,.55))${dimmed < 1 ? ` brightness(${dimmed})` : ''}">
    ${reflect ? `<img data-role="decor" src="${ctx.asset(src)}" style="height:${h}px;width:auto;display:block;position:absolute;top:${h + 4}px;left:0;transform:scaleY(-1);opacity:.08;
      -webkit-mask-image:linear-gradient(to top, rgba(0,0,0,1) 0%, rgba(0,0,0,0) 32%);mask-image:linear-gradient(to top, rgba(0,0,0,1) 0%, rgba(0,0,0,0) 32%)">` : ''}
  </div>`;
};

// CTA pill. A trailing "←" becomes a drawn arrow (font arrows render tiny/inconsistent). In RTL, "forward" points left.
const ARROW = (px) => `<svg data-role="decor" width="${px}" height="${px}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" style="flex:none"><path d="M19 12H5M11 5l-7 7 7 7"/></svg>`;
export const cta = (text = '', {size = 40, style = '', variant = 'accent'} = {}) => {
  const arrow = /\s*←\s*$/.test(text); const t = text.replace(/\s*←\s*$/, '');
  return `<div class="cta cta-${variant}" data-role="cta" style="font-size:${size}px;${style}"><span>${rich(t)}</span>${arrow ? ARROW(Math.round(size * 0.95)) : ''}</div>`;
};

// A row of real products on one floor line, all at the SAME scale (packs of the same size must look the same size:
// a bigger "hero" box misrepresents the product). The hero is brought forward by light and z-order, not by size.
// Widths come from the real image ratios; if space is short, reduce h rather than overlapping printed labels.
export const lineup = (ctx, srcs, {x0, x1, bottom, h, hero = Math.floor(srcs.length / 2), reflect = false, dimOthers = 0.85}) => {
  const hs = srcs.map(() => h);
  const ws = srcs.map((s, i) => { const d = ctx.dim(s); return hs[i] * d.w / d.h; });
  const total = ws.reduce((a, b) => a + b, 0); const gap = srcs.length > 1 ? Math.min(40, (x1 - x0 - total) / (srcs.length - 1)) : 0;
  let x = x0 + Math.max(0, (x1 - x0 - total - gap * (srcs.length - 1)) / 2);
  return srcs.map((s, i) => { const cx = x + ws[i] / 2; x += ws[i] + gap;
    return product(ctx, s, {h: hs[i], cx, bottom, reflect, z: i === hero ? 4 : 2, dim: i === hero ? 1 : dimOthers}); }).join('');
};

// Eyebrow with the brand's slash mark in front: the same small device on every piece ties the set together.
export const eyebrow = (text, {size = 32, color = 'var(--accent)', mark = true} = {}) =>
  `<div class="eyebrow" style="display:flex;align-items:center;gap:${Math.round(size * 0.45)}px;font-weight:800;font-size:${size}px;letter-spacing:.05em;color:${color}">
    ${mark ? `<span data-role="decor" style="display:inline-flex;gap:${Math.round(size * 0.14)}px;flex:none">${`<i style="display:block;width:${Math.round(size * 0.28)}px;height:${Math.round(size * 0.72)}px;background:currentColor;transform:skewX(-38deg);transform-origin:top"></i>`.repeat(2)}</span>` : ''}
    <span>${rich(text)}</span></div>`;
