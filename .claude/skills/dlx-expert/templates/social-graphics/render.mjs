#!/usr/bin/env node
// Social graphics engine: brand.json + content.json -> pixel-exact PNGs (Playwright / Chromium).
// Usage: node render.mjs <project_dir> [--only <id>]
//   <project_dir>/brand.json    colours, font, logo, site
//   <project_dir>/content.json  {"out":"out","creatives":[{"id","layout","format","data":{...}}]}
// Output: <out>/<id>.png (carousel: <id>-1.png ...), and <out>/.qa/<name>.layout.json + <name>.bg.png
// (the same image with all text hidden) which scripts/qa_image.py uses to measure real contrast and safe zones.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {createRequire} from 'node:module';
import {execSync} from 'node:child_process';

const here = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const proj = path.resolve(args[0] || path.join(here, 'example'));
const only = args.includes('--only') ? args[args.indexOf('--only') + 1] : null;

async function loadPlaywright() {
  try { return await import('playwright'); } catch {}
  const req = createRequire(import.meta.url);
  const roots = [process.env.NODE_PATH, (() => { try { return execSync('npm root -g').toString().trim(); } catch { return null; } })()].filter(Boolean);
  for (const r of roots) { try { return req(path.join(r, 'playwright')); } catch {} }
  console.error('FAIL: Playwright not found. Run: npm i -g playwright && npx playwright install chromium'); process.exit(2);
}

const readJSON = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));
const brand = readJSON(path.join(proj, 'brand.json'));
const content = readJSON(path.join(proj, 'content.json'));
const formats = readJSON(path.join(here, 'formats.json'));
const outDir = path.resolve(proj, content.out || 'out');
const qaDir = path.join(outDir, '.qa');
fs.mkdirSync(qaDir, {recursive: true});

// ---------- brand sanity: contrast of the colour pairs the layouts use ----------
const lum = (hex) => { const v = hex.replace('#', ''); const c = [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16) / 255)
  .map((x) => (x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
const C = brand.colors;
let brandFail = false;
for (const [fg, bg] of [['text', 'bg'], ['muted', 'bg'], ['accent', 'bg'], ['onAccent', 'accent'], ['text', 'surface'], ['muted', 'surface']]) {
  if (!C[fg] || !C[bg]) continue;
  const r = ratio(C[fg], C[bg]);
  console.log(`${r >= 4.5 ? 'PASS' : 'FAIL'}  brand contrast ${fg} on ${bg}: ${r.toFixed(2)}:1`);
  if (r < 4.5) brandFail = true;
}
if (brandFail) { console.error('FAIL: fix brand.json colours before rendering (need >= 4.5:1).'); process.exit(1); }

// ---------- helpers given to layouts ----------
const asset = (p) => pathToFileURL(path.resolve(proj, p)).href;
const dim = (p) => { // PNG/JPEG intrinsic size without extra deps
  const b = fs.readFileSync(path.resolve(proj, p));
  if (b.readUInt32BE(0) === 0x89504e47) return {w: b.readUInt32BE(16), h: b.readUInt32BE(20)};
  let i = 2; while (i < b.length) { const m = b[i + 1]; const len = b.readUInt16BE(i + 2); if (m >= 0xc0 && m <= 0xc3) return {h: b.readUInt16BE(i + 5), w: b.readUInt16BE(i + 7)}; i += 2 + len; }
  throw new Error('unknown image size: ' + p);
};
const fontFiles = brand.font?.files || [
  {src: path.join(here, 'fonts/heebo-hebrew.woff2'), unicodeRange: 'U+0307-0308, U+0590-05FF, U+200C-2010, U+20AA, U+25CC, U+FB1D-FB4F'},
  {src: path.join(here, 'fonts/heebo-latin.woff2')},
];
const family = brand.font?.family || 'Heebo';
const fontCSS = fontFiles.map((f) => `@font-face{font-family:'${family}';src:url('${pathToFileURL(path.resolve(proj, f.src)).href}') format('woff2');font-weight:100 900;font-display:block;${f.unicodeRange ? `unicode-range:${f.unicodeRange};` : ''}}`).join('\n');

const baseCSS = (fmt, totalW) => `
${fontCSS}
:root{--bg:${C.bg};--surface:${C.surface || C.bg};--accent:${C.accent};--text:${C.text};--muted:${C.muted || C.text};--on-accent:${C.onAccent || '#000'};
  --W:${fmt.w}px;--H:${fmt.h}px;--sl:${Math.round(fmt.safe.left * fmt.w)}px;--sr:${Math.round(fmt.safe.right * fmt.w)}px;
  --st:${Math.round(fmt.safe.top * fmt.h)}px;--sb:${Math.round(fmt.safe.bottom * fmt.h)}px;}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:${totalW}px;height:${fmt.h}px;background:var(--bg);overflow:hidden}
body{font-family:'${family}',sans-serif;color:var(--text);-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}
.canvas{position:absolute;top:0;width:${fmt.w}px;height:${fmt.h}px;overflow:hidden;background:var(--bg)}
.grain{position:absolute;inset:0;z-index:1;pointer-events:none;mix-blend-mode:overlay}
.layer{position:absolute;inset:0;z-index:5}
.line{display:block}
em{font-style:normal;color:var(--accent)}
.tbd{text-decoration:underline dotted;text-decoration-thickness:.07em;text-underline-offset:.18em}
.ltr{unicode-bidi:isolate;direction:ltr;display:inline-block}
.cta{display:inline-flex;align-items:center;gap:.45em;font-weight:800;line-height:1;padding:.62em 1.05em .66em;border-radius:999px;white-space:nowrap}
.cta-accent{background:var(--accent);color:var(--on-accent)}
.cta-dark{background:var(--bg);color:var(--text)}
.cta-outline{border:3px solid var(--accent);color:var(--text)}
`;

// Collected in the page: every text line box, images and overflow, in canvas pixels.
function measure() {
  const out = {texts: [], images: [], overflow: [], fontsOk: document.fonts.check(`900 60px "${window.__family}"`, 'אבג')};
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const byEl = new Map(); const blocks = new Map();
  // pieces of one visual line (em, [placeholder], LTR runs) share a block id so they are not flagged as touching
  const blockOf = (el) => { let b = el; while (b.parentElement && (getComputedStyle(b).display === 'inline' || b.classList.contains('ltr'))) b = b.parentElement;
    if (!blocks.has(b)) blocks.set(b, blocks.size); return blocks.get(b); };
  while (walker.nextNode()) {
    const n = walker.currentNode; if (!n.textContent.trim()) continue;
    const el = n.parentElement; const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) continue;
    const r = document.createRange(); r.selectNodeContents(n);
    // Range rects are the font's content area (ascent+descent, ~1.5em) and overlap neighbouring lines when
    // line-height is tight. Shrink each rect to its line box (centred on the content area) = what the eye sees.
    const lh = cs.lineHeight === 'normal' ? parseFloat(cs.fontSize) * 1.2 : parseFloat(cs.lineHeight);
    const rects = [...r.getClientRects()].filter((q) => q.width > 1 && q.height > 1).map((q) => {
      const h = Math.min(q.height, lh); return [q.x, q.y + (q.height - h) / 2, q.width, h].map(Math.round); });
    const host = el.closest('[data-role]');
    const key = el; if (!byEl.has(key)) byEl.set(key, {text: '', block: blockOf(el), role: host ? host.dataset.role : 'text', color: cs.color, size: parseFloat(cs.fontSize), weight: +cs.fontWeight, lines: []});
    const e = byEl.get(key); e.text += n.textContent.trim() + ' '; e.lines.push(...rects);
  }
  out.texts = [...byEl.values()].map((e) => ({...e, text: e.text.trim()}));
  for (const img of document.images) {
    const b = img.getBoundingClientRect(); if (!b.width) continue;
    out.images.push({src: img.src.split('/').pop(), role: img.dataset.role || 'decor', ok: img.complete && img.naturalWidth > 0,
      rect: [b.x, b.y, b.width, b.height].map(Math.round), scale: +(Math.max(img.offsetWidth / img.naturalWidth, img.offsetHeight / img.naturalHeight)).toFixed(2) /* layout size, ignores rotation */});
  }
  for (const el of document.querySelectorAll('.layer *')) {
    const cs = getComputedStyle(el);
    if ((cs.overflow === 'hidden' || el.dataset.fit !== undefined) && (el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2))
      out.overflow.push((el.textContent || '').trim().slice(0, 40));
  }
  return out;
}

const {chromium} = await loadPlaywright();
const browser = await chromium.launch();
const page = await browser.newPage({deviceScaleFactor: 1});
let made = 0;
for (const c of content.creatives) {
  if (only && c.id !== only) continue;
  const fmt = formats[c.format]; if (!fmt) throw new Error(`unknown format ${c.format} (see formats.json)`);
  const layout = (await import(pathToFileURL(path.join(here, 'layouts', `${c.layout}.mjs`)).href)).default;
  const ctx = {brand, fmt, asset, dim, data: c.data || {}};
  const r = layout(ctx); // {html, css?, slides?}
  const n = r.slides || 1; const totalW = fmt.w * n;
  const html = `<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><style>${baseCSS(fmt, totalW)}${r.css || ''}</style>
    <script>window.__family=${JSON.stringify(family)}</script></head><body>${r.html}</body></html>`;
  const htmlPath = path.join(qaDir, `${c.id}.html`); fs.writeFileSync(htmlPath, html);
  await page.setViewportSize({width: totalW, height: fmt.h});
  await page.goto(pathToFileURL(htmlPath).href, {waitUntil: 'load'});
  await page.evaluate(async () => { await document.fonts.ready; await Promise.all([...document.images].map((i) => i.decode().catch(() => null))); });
  const m = await page.evaluate(measure);
  const shots = [];
  for (let i = 0; i < n; i++) {
    const name = n > 1 ? `${c.id}-${i + 1}` : c.id;
    await page.screenshot({path: path.join(outDir, `${name}.png`), clip: {x: i * fmt.w, y: 0, width: fmt.w, height: fmt.h}});
    shots.push(name);
  }
  // background-only render (text invisible, boxes/pills kept) for true contrast sampling
  await page.addStyleTag({content: '*{color:transparent!important;text-shadow:none!important;-webkit-text-stroke:0!important;caret-color:transparent!important}'});
  for (let i = 0; i < n; i++) await page.screenshot({path: path.join(qaDir, `${shots[i]}.bg.png`), clip: {x: i * fmt.w, y: 0, width: fmt.w, height: fmt.h}});
  const sx0 = Math.round(fmt.safe.left * fmt.w), sx1 = Math.round(fmt.w * (1 - fmt.safe.right));
  const sy0 = Math.round(fmt.safe.top * fmt.h), sy1 = Math.round(fmt.h * (1 - fmt.safe.bottom));
  shots.forEach((name, i) => {
    const off = i * fmt.w; const inSlide = ([x, , w]) => x + w > off && x < off + fmt.w;
    const shift = (q) => [q[0] - off, q[1], q[2], q[3]];
    const texts = m.texts.map((t) => ({...t, lines: t.lines.filter(inSlide).map(shift)})).filter((t) => t.lines.length);
    const images = m.images.filter((im) => inSlide(im.rect)).map((im) => ({...im, rect: shift(im.rect)}));
    fs.writeFileSync(path.join(qaDir, `${name}.layout.json`), JSON.stringify({id: name, layout: c.layout, format: c.format, w: fmt.w, h: fmt.h,
      safe: [sx0, sy0, sx1, sy1], minText: fmt.minText, headlineMin: fmt.headlineMin, fontsOk: m.fontsOk, overflow: m.overflow, texts, images}, null, 1));
    console.log(`rendered ${path.join(outDir, name + '.png')}  (${c.layout}, ${c.format})`); made++;
  });
}
await browser.close();
console.log(`\n${made} image(s). Next: python3 <skill>/scripts/qa_image.py ${outDir}`);
