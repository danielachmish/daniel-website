#!/usr/bin/env node
// qa_web.mjs <url-or-file-or-dir> [outdir]
// Agency-grade web QA before delivery. Prints PASS/WARN/FAIL; exits 1 on any FAIL.
//  - Screenshots (full + first screen) at 360 / 390 / 768 / 1440
//  - Console errors, failed same-origin requests
//  - Horizontal overflow / elements sticking out (every width)
//  - Tap targets >= 44x44 on phone (inline text links exempt), body text >= 16px on phone, inputs >= 16px (iOS zoom)
//  - Real-pixel text contrast (WCAG AA 4.5:1, large text 3:1), measured against the rendered background
//  - Perf budget under Lighthouse-like mobile throttling (1.6 Mbps, 150 ms RTT, 4x CPU): LCP, CLS, TBT, page weight
//  - Images: alt, width/height, lazy below the fold, modern format, oversized files
//  - Headings (one H1, no skipped levels), lang/dir, skip link, visible focus on keyboard Tab
//  - SEO: title, description, canonical, Open Graph, valid JSON-LD, favicon
//  - Lead form: empty submit must show errors, labels, autocomplete, honeypot, "demo mode" left on
//  - Leftover placeholders ([...], לאשר, lorem) and persistent mobile CTA
//  - axe-core (WCAG 2.2 AA rules) when installed (npm i -g axe-core; NODE_PATH=$(npm root -g))
// Writes qa_report.json next to the screenshots.
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';

const require = createRequire(import.meta.url);
const tryRequire = (m) => { for (const base of [import.meta.url, path.join(process.env.NODE_PATH || '', 'x'), '/usr/local/lib/node_modules/x', '/usr/lib/node_modules/x']) {
  try { return createRequire(base)(m); } catch {} } return null; };
const pw = tryRequire('playwright');
if (!pw) { console.error('playwright not found (try NODE_PATH=$(npm root -g))'); process.exit(2); }
const { chromium } = pw;
let axeSource = null;
try { const axePath = (() => { for (const base of [import.meta.url, path.join(process.env.NODE_PATH || '', 'x'), '/usr/local/lib/node_modules/x']) {
  try { return createRequire(base).resolve('axe-core/axe.min.js'); } catch {} } return null; })();
  if (axePath) axeSource = fs.readFileSync(axePath, 'utf8'); } catch {}

const [, , target, outArg] = process.argv;
if (!target) { console.error('Usage: node qa_web.mjs <url-or-file-or-dir> [outdir]'); process.exit(2); }
const OUT = path.resolve(outArg || './qa_web_out');
fs.mkdirSync(OUT, { recursive: true });

// Local files are served over a tiny in-process http server (file:// breaks fetch, CORS, transferSize).
let server = null;
let url;
if (/^https?:\/\//.test(target) || target.startsWith('file:')) {
  url = target;
} else {
  const http = require('http');
  const abs = path.resolve(target);
  const isDir = fs.existsSync(abs) && fs.statSync(abs).isDirectory();
  const root = isDir ? abs : path.dirname(abs);
  const entry = isDir ? 'index.html' : path.basename(abs);
  const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css',
    '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.webp': 'image/webp', '.avif': 'image/avif', '.gif': 'image/gif', '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2',
    '.mp4': 'video/mp4', '.webm': 'video/webm', '.glb': 'model/gltf-binary', '.txt': 'text/plain', '.xml': 'application/xml' };
  server = http.createServer((req, res) => {
    const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    let f = path.join(root, p);
    if (!f.startsWith(root)) { res.writeHead(403).end(); return; }
    if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html');
    if (!fs.existsSync(f)) { res.writeHead(404).end('not found'); return; }
    const body = fs.readFileSync(f);
    res.writeHead(200, { 'Content-Type': MIME[path.extname(f).toLowerCase()] || 'application/octet-stream', 'Content-Length': body.length });
    res.end(body);
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  url = `http://127.0.0.1:${server.address().port}/${entry}`;
  console.log(`Serving ${root} at ${url}`);
}
const origin = new URL(url).origin;

const results = [];
const pass = m => results.push(['PASS', m]);
const warn = m => results.push(['WARN', m]);
const fail = m => results.push(['FAIL', m]);
const report = { url, viewports: {}, perf: null, axe: null };

const VIEWPORTS = [
  { name: 'phone360', width: 360, height: 780, mobile: true },
  { name: 'phone390', width: 390, height: 844, mobile: true },
  { name: 'tablet768', width: 768, height: 1024, mobile: true },
  { name: 'desktop1440', width: 1440, height: 900, mobile: false },
];

async function settle(page) {
  try { await page.waitForLoadState('networkidle', { timeout: 8000 }); } catch {}
  await page.evaluate(async () => { // scroll through: triggers lazy images + reveal animations
    const step = window.innerHeight * 0.7;
    // behavior 'instant': sites with scroll-behavior:smooth would otherwise never reach the bottom
    for (let y = 0; y < document.documentElement.scrollHeight; y += step) { window.scrollTo({ top: y, behavior: 'instant' }); await new Promise(r => setTimeout(r, 120)); }
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' }); await new Promise(r => setTimeout(r, 200));
    window.scrollTo({ top: 0, behavior: 'instant' });
  });
  await page.waitForTimeout(900);
}

// ---------- contrast measured on real pixels ----------
async function contrastAudit(browser, page, vpw) {
  const items = await page.evaluate(() => {
    const out = []; let i = 0;
    const vis = el => { const s = getComputedStyle(el); const r = el.getBoundingClientRect();
      return s.display !== 'none' && s.visibility !== 'hidden' && +s.opacity > 0.05 && r.width > 0 && r.height > 0; };
    const inFixed = el => { for (let a = el; a; a = a.parentElement) { const p = getComputedStyle(a).position; if (p === 'fixed' || p === 'sticky') return true; } return false; };
    const hiddenByAncestor = el => { for (let a = el; a; a = a.parentElement) { const s = getComputedStyle(a); if (+s.opacity < 0.05 || s.visibility === 'hidden') return true;
      if (a.getAttribute && a.getAttribute('aria-hidden') === 'true' && a !== document.body) return true; } return false; };
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const seen = new Set();
    while (w.nextNode()) {
      const t = w.currentNode, el = t.parentElement;
      if (!el || seen.has(el) || !t.textContent.trim()) continue; seen.add(el);
      if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'OPTION'].includes(el.tagName) || !vis(el) || hiddenByAncestor(el)) continue;
      if (el.closest('.visually-hidden, .sr-only, .hp, [hidden]')) continue;
      const range = document.createRange(); range.selectNodeContents(t);
      const r = range.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) continue;
      if (r.bottom + scrollY <= 0 || r.right <= 0 || r.left >= innerWidth) continue; // off-canvas (skip links, drawers)
      let cut = false; // clipped away inside a scroll/overflow container (carousels)
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        if (getComputedStyle(p).overflowX !== 'visible') { const pr = p.getBoundingClientRect(); if (r.left < pr.left - 1 || r.right > pr.right + 1) { cut = true; break; } } }
      if (cut) continue;
      const s = getComputedStyle(el);
      out.push({ i: i++, x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height, color: s.color,
        fs: parseFloat(s.fontSize), fw: parseInt(s.fontWeight, 10) || 400, fixed: inFixed(el),
        txt: t.textContent.trim().slice(0, 40) });
    }
    return out;
  });
  // fixed/sticky bars get painted mid-page in full-page captures: pin sticky in place, hide fixed
  await page.evaluate(() => { for (const el of document.querySelectorAll('body *')) { const p = getComputedStyle(el).position;
    if (p === 'sticky') { el.dataset.qaPos = el.style.position || '-'; el.style.position = 'relative'; }
    else if (p === 'fixed') { el.dataset.qaVis = el.style.visibility || '-'; el.style.visibility = 'hidden'; } } });
  const style = await page.addStyleTag({ content: '*,*::before,*::after{color:transparent!important;-webkit-text-fill-color:transparent!important;text-shadow:none!important;text-decoration-color:transparent!important;caret-color:transparent!important}' });
  await page.waitForTimeout(100);
  const buf = await page.screenshot({ fullPage: true, type: 'png' });
  if (process.env.QA_DEBUG) fs.writeFileSync(path.join(OUT, `contrast_bg_${vpw}.png`), buf);
  await style.evaluate(n => n.remove());
  await page.evaluate(() => { for (const el of document.querySelectorAll('[data-qa-pos],[data-qa-vis]')) {
    if (el.dataset.qaPos) { el.style.position = el.dataset.qaPos === '-' ? '' : el.dataset.qaPos; delete el.dataset.qaPos; }
    if (el.dataset.qaVis) { el.style.visibility = el.dataset.qaVis === '-' ? '' : el.dataset.qaVis; delete el.dataset.qaVis; } } });
  const scratch = await browser.newPage();
  const res = await scratch.evaluate(async ({ b64, items }) => {
    const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
    const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
    const g = c.getContext('2d', { willReadFrequently: true }); g.drawImage(img, 0, 0);
    const lin = v => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    const lum = (r, gg, b) => 0.2126 * lin(r) + 0.7152 * lin(gg) + 0.0722 * lin(b);
    const parse = s => { const m = s.match(/[\d.]+/g).map(Number); return { r: m[0], g: m[1], b: m[2], a: m.length > 3 ? m[3] : 1 }; };
    const out = [];
    for (const it of items) {
      if (it.fixed) continue;
      const x = Math.max(0, Math.floor(it.x)), y = Math.max(0, Math.floor(it.y));
      const w = Math.min(c.width - x, Math.ceil(it.w)), h = Math.min(c.height - y, Math.ceil(it.h));
      if (w < 2 || h < 2) continue;
      const d = g.getImageData(x, y, w, h).data;
      const step = Math.max(1, Math.floor(Math.sqrt((w * h) / 3000)));
      const fg = parse(it.color);
      const ratios = [];
      for (let yy = 0; yy < h; yy += step) for (let xx = 0; xx < w; xx += step) {
        const k = (yy * w + xx) * 4;
        const br = d[k], bgc = d[k + 1], bb = d[k + 2];
        const fr = fg.r * fg.a + br * (1 - fg.a), fgg = fg.g * fg.a + bgc * (1 - fg.a), fb = fg.b * fg.a + bb * (1 - fg.a);
        const L1 = lum(fr, fgg, fb), L2 = lum(br, bgc, bb);
        ratios.push((Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05));
      }
      ratios.sort((a, b) => a - b);
      const ratio = ratios[Math.floor(ratios.length * 0.1)]; // 10th percentile: worst realistic background under the text
      const large = it.fs >= 24 || (it.fs >= 18.66 && it.fw >= 700);
      const need = large ? 3 : 4.5;
      out.push({ ...it, ratio: Math.round(ratio * 100) / 100, need });
    }
    return out;
  }, { b64: buf.toString('base64'), items });
  await scratch.close();
  const bad = res.filter(r => r.ratio < r.need).sort((a, b) => a.ratio / a.need - b.ratio / b.need);
  return { checked: res.length, skippedFixed: items.filter(i => i.fixed).length, bad };
}

const browser = await chromium.launch();
try {
  // ======================= per-viewport layout checks =======================
  for (const vp of VIEWPORTS) {
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, isMobile: vp.mobile && vp.width < 700,
      hasTouch: vp.mobile, deviceScaleFactor: 1, locale: 'he-IL' });
    const page = await ctx.newPage();
    const consoleErrors = [], failedSame = [], failedOther = [];
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page.on('pageerror', e => consoleErrors.push('pageerror: ' + e.message));
    const noteFail = (u, why) => (u.startsWith(origin) ? failedSame : failedOther).push(`${why} ${u}`);
    page.on('requestfailed', r => noteFail(r.url(), r.failure()?.errorText || 'failed'));
    page.on('response', r => { if (r.status() >= 400) noteFail(r.url(), 'HTTP ' + r.status()); });
    const P = `[${vp.name}]`;
    try { await page.goto(url, { waitUntil: 'load', timeout: 30000 }); }
    catch (e) { fail(`${P} page failed to load: ${e.message.split('\n')[0]}`); await ctx.close(); continue; }
    await settle(page);

    const full = path.join(OUT, `${vp.name}_full.png`), fold = path.join(OUT, `${vp.name}_fold.png`);
    await page.screenshot({ path: fold });
    // full-page capture paints fixed bars (sticky CTA, chat buttons) mid-page: hide them for the overview shot only
    await page.evaluate(() => { for (const el of document.querySelectorAll('body *')) if (getComputedStyle(el).position === 'fixed') { el.dataset.qaFix = el.style.visibility || '-'; el.style.visibility = 'hidden'; } });
    await page.screenshot({ path: full, fullPage: true });
    await page.evaluate(() => { for (const el of document.querySelectorAll('[data-qa-fix]')) { el.style.visibility = el.dataset.qaFix === '-' ? '' : el.dataset.qaFix; delete el.dataset.qaFix; } });

    const a = await page.evaluate(({ VPW, phone }) => {
      const vis = el => { const s = getComputedStyle(el); const r = el.getBoundingClientRect();
        return s.display !== 'none' && s.visibility !== 'hidden' && +s.opacity !== 0 && r.width > 0 && r.height > 0; };
      const desc = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
        (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
      const clipped = el => { for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const o = getComputedStyle(p).overflowX; if (['hidden', 'auto', 'scroll', 'clip'].includes(o)) return true; } return false; };
      const docW = document.documentElement.scrollWidth;
      const overflowers = [...document.querySelectorAll('body *')].filter(e => { const r = e.getBoundingClientRect();
        const off = r.left >= VPW - 1 || r.right <= 1; return vis(e) && !off && (r.right > VPW + 1 || r.left < -1) && !clipped(e); }).slice(0, 5).map(desc);
      // tap targets
      const hiddenTree = el => { for (let p = el; p; p = p.parentElement) { if (p.getAttribute && p.getAttribute('aria-hidden') === 'true') return true;
        const s = getComputedStyle(p); if (+s.opacity === 0 || s.visibility === 'hidden') return true; } return false; };
      const isInlineTextLink = el => el.tagName === 'A' && getComputedStyle(el).display === 'inline' &&
        el.parentElement && /^(P|LI|SPAN|TD|DD|LABEL|SMALL|STRONG|EM)$/.test(el.parentElement.tagName) &&
        (el.parentElement.textContent || '').trim().length > (el.textContent || '').trim().length + 3;
      const smallTargets = [];
      if (phone) {
        for (const el of document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [tabindex="0"]')) {
          if (!vis(el) || hiddenTree(el) || el.closest('.hp, .skip-link')) continue;
          if (isInlineTextLink(el)) continue;
          let t = el;
          if ((el.type === 'checkbox' || el.type === 'radio') && el.closest('label')) t = el.closest('label');
          const r = t.getBoundingClientRect();
          if (r.width < 43.5 || r.height < 43.5) smallTargets.push(`${desc(el)} ${Math.round(r.width)}x${Math.round(r.height)} "${(el.innerText || el.getAttribute('aria-label') || el.name || '').trim().slice(0, 24)}"`);
        }
      }
      // text sizes
      const tiny = [], smallBody = [];
      const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); const seen = new Set();
      while (w.nextNode()) { const t = w.currentNode, el = t.parentElement;
        if (!el || seen.has(el) || !t.textContent.trim() || !vis(el) || el.closest('.visually-hidden,.hp')) continue; seen.add(el);
        const f = parseFloat(getComputedStyle(el).fontSize);
        if (f < 12) tiny.push(`${f}px "${t.textContent.trim().slice(0, 30)}"`);
        if (phone && el.closest('p') && !el.closest('label, figcaption, footer, .legal, .field, small') && f < 15.5 && t.textContent.trim().length > 60)
          smallBody.push(`${f}px "${t.textContent.trim().slice(0, 30)}"`);
      }
      const smallInputs = phone ? [...document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea')]
        .filter(e => vis(e) && !e.closest('.hp') && parseFloat(getComputedStyle(e).fontSize) < 16).map(desc) : [];
      // persistent CTA on phone (checked after scroll in node)
      return { docW, overflowers, smallTargets, tiny, smallBody, smallInputs };
    }, { VPW: vp.width, phone: vp.width < 700 });

    // review/: screen-by-screen frames exactly as a visitor sees them (sticky bars included). Hand THESE to the critic.
    if (vp.name === 'phone390' || vp.name === 'desktop1440') {
      const RV = path.join(OUT, 'review'); fs.mkdirSync(RV, { recursive: true });
      const total = await page.evaluate(() => document.documentElement.scrollHeight);
      let n = 0;
      for (let y = 0; y < total && n < 18; y += Math.round(vp.height * 0.85), n++) {
        await page.evaluate(yy => window.scrollTo({ top: yy, behavior: 'instant' }), y);
        await page.waitForTimeout(450);
        await page.screenshot({ path: path.join(RV, `${vp.name}_${String(n + 1).padStart(2, '0')}.png`) });
      }
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' })); await page.waitForTimeout(300);
    }

    let stickyOk = null;
    if (vp.width < 700) {
      stickyOk = await page.evaluate(async () => {
        window.scrollTo({ top: window.innerHeight * 1.6, behavior: 'instant' }); await new Promise(r => setTimeout(r, 700));
        const H = window.innerHeight;
        const ok = [...document.querySelectorAll('a[href], button')].some(el => {
          let fixed = false; for (let p = el; p; p = p.parentElement) { const s = getComputedStyle(p).position; if (s === 'fixed' || s === 'sticky') { fixed = true; break; } }
          const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
          return fixed && r.top >= 0 && r.bottom <= H && r.width > 60 && s.visibility !== 'hidden' && el.closest('[aria-hidden="true"]') === null; });
        window.scrollTo({ top: 0, behavior: 'instant' }); return ok;
      });
    }

    const cr = await contrastAudit(browser, page, vp.width);
    report.viewports[vp.name] = { screenshots: [full, fold], ...a, consoleErrors, failedSame, failedOther, contrast: { checked: cr.checked, bad: cr.bad.slice(0, 20) } };

    console.log(`\n=== ${vp.name} ${vp.width}x${vp.height} ===\n  ${full}\n  ${fold}`);
    consoleErrors.length ? fail(`${P} ${consoleErrors.length} console error(s): ${consoleErrors.slice(0, 3).join(' | ')}`) : pass(`${P} no console errors`);
    failedSame.length ? fail(`${P} ${failedSame.length} broken own request(s): ${failedSame.slice(0, 3).join(' | ')}`) : pass(`${P} no broken own requests`);
    if (failedOther.length) warn(`${P} ${failedOther.length} failed external request(s): ${failedOther.slice(0, 3).join(' | ')}`);
    if (a.docW > vp.width + 1) fail(`${P} horizontal scroll: page ${a.docW}px > ${vp.width}px (${a.overflowers.join(', ')})`);
    else if (a.overflowers.length) fail(`${P} elements stick out of the screen: ${a.overflowers.join(', ')}`);
    else pass(`${P} no horizontal overflow`);
    a.tiny.length ? warn(`${P} ${a.tiny.length} text element(s) under 12px: ${a.tiny.slice(0, 3).join(' | ')}`) : pass(`${P} no text under 12px`);
    if (vp.width < 700) {
      a.smallTargets.length ? fail(`${P} ${a.smallTargets.length} tap target(s) under 44x44: ${a.smallTargets.slice(0, 4).join(' | ')}`) : pass(`${P} all tap targets >= 44x44`);
      a.smallBody.length ? warn(`${P} body paragraphs under 16px: ${a.smallBody.slice(0, 3).join(' | ')}`) : pass(`${P} body text >= 16px`);
      a.smallInputs.length ? fail(`${P} form inputs under 16px (iPhone zooms in on focus): ${a.smallInputs.join(', ')}`) : pass(`${P} inputs >= 16px`);
      stickyOk ? pass(`${P} a call-to-action stays on screen while scrolling`) : warn(`${P} no persistent call-to-action after scrolling (sticky CTA / header button)`);
    }
    cr.bad.length ? fail(`${P} ${cr.bad.length} text element(s) below WCAG AA contrast (measured on pixels): ` +
      cr.bad.slice(0, 4).map(b => `"${b.txt.slice(0, 22)}" ${b.ratio}:1 < ${b.need}`).join(' | '))
      : pass(`${P} text contrast AA on ${cr.checked} elements (pixel-measured; ${cr.skippedFixed} in fixed bars not measured)`);
    await ctx.close();
  }

  // ======================= desktop: structure, SEO, a11y, focus, images =======================
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'he-IL' });
    const page = await ctx.newPage();
    await page.goto(url, { waitUntil: 'load' }); await settle(page);
    const s = await page.evaluate(() => {
      const q = (sel, attr = 'content') => document.querySelector(sel)?.getAttribute(attr) || '';
      const vis = el => { const st = getComputedStyle(el); const r = el.getBoundingClientRect(); return st.display !== 'none' && st.visibility !== 'hidden' && r.width > 0 && r.height > 0; };
      const desc = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/)[0] : '');
      const heads = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(h => !h.closest('template'));
      const skips = []; let prev = 0;
      for (const h of heads) { const l = +h.tagName[1]; if (prev && l > prev + 1) skips.push(`${h.tagName} after H${prev}: "${h.textContent.trim().slice(0, 30)}"`); prev = l; }
      const ld = [...document.querySelectorAll('script[type="application/ld+json"]')].map(x => { try { JSON.parse(x.textContent); return 'ok'; } catch (e) { return 'invalid: ' + e.message; } });
      const imgs = [...document.querySelectorAll('img')];
      const H = window.innerHeight;
      const imgNoAlt = imgs.filter(i => !i.hasAttribute('alt')).map(i => i.src.split('/').pop());
      const imgNoDims = imgs.filter(i => !(i.getAttribute('width') && i.getAttribute('height'))).map(i => i.src.split('/').pop());
      const imgEagerBelow = imgs.filter(i => i.getBoundingClientRect().top > H * 1.2 && i.loading !== 'lazy').map(i => i.src.split('/').pop());
      const imgOversized = imgs.filter(i => vis(i) && i.naturalWidth > i.getBoundingClientRect().width * 2.6 && i.getBoundingClientRect().width > 0 && !/\.svg/.test(i.currentSrc))
        .map(i => `${i.currentSrc.split('/').pop()} ${i.naturalWidth}px shown at ${Math.round(i.getBoundingClientRect().width)}px`);
      const imgOldFormat = imgs.filter(i => /\.(png|jpe?g|gif)(\?|$)/i.test(i.currentSrc || i.src)).map(i => (i.currentSrc || i.src).split('/').pop());
      const inputs = [...document.querySelectorAll('input, select, textarea')].filter(e => !['hidden', 'submit', 'button', 'reset', 'image'].includes(e.type) && !e.closest('.hp'));
      const inputNoLabel = inputs.filter(e => !(e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') || e.title ||
        (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`)) || e.closest('label'))).map(desc);
      const btnNoName = [...document.querySelectorAll('button, [role=button], a[href]')].filter(b => vis(b) && !(b.innerText || b.textContent || '').trim() &&
        !b.getAttribute('aria-label') && !b.getAttribute('aria-labelledby') && !b.title && !b.querySelector('img[alt]:not([alt=""]), svg title')).map(desc);
      const firstFocusable = document.querySelector('a[href], button, input, select, textarea');
      const skipLink = !!firstFocusable && firstFocusable.tagName === 'A' && /^#/.test(firstFocusable.getAttribute('href') || '');
      const bodyText = document.body.innerText;
      const metaText = [document.title, q('meta[name=description]'), q('meta[property="og:title"]'), q('meta[property="og:description"]')].join(' ');
      const placeholders = (bodyText.match(/\[[^\]\n]{2,60}\]/g) || []).concat(metaText.match(/\[[^\]\n]{2,60}\]/g) || []);
      const tbcCount = document.querySelectorAll('.tbc, .tbc-block').length + (bodyText.match(/לאשר[:\]]/g) || []).length;
      const forms = [...document.querySelectorAll('form')].map(f => ({
        id: f.id || desc(f), demo: f.dataset.demo === 'true', action: f.getAttribute('action') || '',
        honeypot: !!f.querySelector('.hp input, input[tabindex="-1"][autocomplete="off"], input[name*="honey" i]'),
        noAutocomplete: [...f.querySelectorAll('input[type=email], input[type=tel], input[name*=name i]')].filter(i => !i.getAttribute('autocomplete') && !i.closest('.hp')).map(desc),
      }));
      return {
        title: document.title, desc: q('meta[name=description]'), canonical: q('link[rel=canonical]', 'href'),
        ogTitle: q('meta[property="og:title"]'), ogImage: q('meta[property="og:image"]'), favicon: !!document.querySelector('link[rel~=icon]'),
        lang: document.documentElement.lang, dir: document.documentElement.dir || getComputedStyle(document.documentElement).direction,
        viewportMeta: !!document.querySelector('meta[name=viewport]'),
        h1: heads.filter(h => h.tagName === 'H1').length, skips, ld,
        imgNoAlt, imgNoDims, imgEagerBelow, imgOversized, imgOldFormat, inputNoLabel, btnNoName, skipLink,
        lorem: /lorem ipsum|dolor sit amet/i.test(bodyText), placeholders: [...new Set(placeholders)], tbcCount, forms,
      };
    });
    report.structure = s;
    const D = '[desktop1440]';
    s.title ? (s.title.length > 65 ? warn(`title is ${s.title.length} chars (Google cuts ~60): "${s.title}"`) : pass(`title: "${s.title}"`)) : fail('page has no <title>');
    s.desc ? (s.desc.length > 160 ? warn(`meta description ${s.desc.length} chars (> 160)`) : pass(`meta description (${s.desc.length} chars)`)) : fail('missing meta description');
    s.canonical ? pass('canonical link') : warn('no canonical link');
    s.ogTitle && s.ogImage ? pass('Open Graph title + image') : fail('missing og:title / og:image (link previews in WhatsApp/Facebook will look broken)');
    s.favicon ? pass('favicon') : warn('no favicon');
    s.ld.length ? (s.ld.every(x => x === 'ok') ? pass(`JSON-LD valid (${s.ld.length} block(s))`) : fail(`invalid JSON-LD: ${s.ld.filter(x => x !== 'ok').join(' | ')}`)) : warn('no JSON-LD structured data');
    s.viewportMeta ? pass('viewport meta') : fail('missing <meta name=viewport>');
    s.lang ? pass(`html lang="${s.lang}" dir=${s.dir}`) : fail('html has no lang');
    if (s.lang && s.lang.startsWith('he') && s.dir !== 'rtl') fail('Hebrew page is not dir=rtl');
    s.h1 === 1 ? pass('exactly one H1') : fail(`${s.h1} H1 elements (need exactly 1)`);
    s.skips.length ? warn(`heading levels skipped: ${s.skips.slice(0, 3).join(' | ')}`) : pass('heading order OK');
    s.skipLink ? pass('skip link is the first focusable element') : warn('no "skip to content" link as first focusable element');
    s.imgNoAlt.length ? fail(`img without alt: ${s.imgNoAlt.join(', ')}`) : pass('all images have alt');
    s.imgNoDims.length ? warn(`img without width/height (layout shift): ${s.imgNoDims.slice(0, 5).join(', ')}`) : pass('all images have width/height');
    s.imgEagerBelow.length ? warn(`below-the-fold images without loading="lazy": ${s.imgEagerBelow.slice(0, 5).join(', ')}`) : pass('below-the-fold images lazy');
    s.imgOldFormat.length ? warn(`PNG/JPG images (convert to WebP/AVIF): ${s.imgOldFormat.slice(0, 5).join(', ')}`) : pass('images in modern formats');
    if (s.imgOversized.length) warn(`images much larger than shown: ${s.imgOversized.slice(0, 3).join(' | ')}`);
    s.inputNoLabel.length ? fail(`form fields without label: ${s.inputNoLabel.join(', ')}`) : pass('all form fields labelled');
    s.btnNoName.length ? fail(`buttons/links without accessible name: ${s.btnNoName.join(', ')}`) : pass('all buttons/links named');
    s.lorem ? fail('lorem ipsum on the page') : pass('no lorem ipsum');
    if (s.placeholders.length) warn(`${s.placeholders.length} bracket placeholder(s) left (template text?): ${s.placeholders.slice(0, 5).join(' ')}`);
    if (s.tbcCount) warn(`${s.tbcCount} item(s) marked "לאשר": list them for the client, none may go live unconfirmed`);
    for (const f of s.forms) {
      if (f.demo) warn(`form ${f.id} is in DEMO mode (data-demo="true"): leads go nowhere. Remove before launch`);
      f.honeypot ? pass(`form ${f.id} has a honeypot`) : warn(`form ${f.id} has no honeypot / spam trap`);
      if (f.noAutocomplete.length) warn(`form ${f.id} fields without autocomplete: ${f.noAutocomplete.join(', ')}`);
    }

    // keyboard focus visibility: Tab through the first 14 stops
    const noFocus = [];
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
    for (let k = 0; k < 14; k++) {
      await page.keyboard.press('Tab');
      const r = await page.evaluate(() => {
        const el = document.activeElement; if (!el || el === document.body) return null;
        const pick = s => [s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0 ? s.outlineStyle + s.outlineWidth + s.outlineColor : '', s.boxShadow, s.borderColor, s.backgroundColor, s.textDecorationLine, s.color].join('|');
        const on = pick(getComputedStyle(el));
        const clone = el.cloneNode(true); // compare against the same element when not focused
        el.blur(); const off = pick(getComputedStyle(el)); el.focus({ preventScroll: true });
        clone.remove();
        return { same: on === off, name: el.tagName.toLowerCase() + ' "' + (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 20) + '"' };
      });
      if (r && r.same) noFocus.push(r.name);
    }
    noFocus.length ? fail(`${D} no visible focus indicator on: ${noFocus.slice(0, 4).join(', ')}`) : pass(`${D} visible focus on keyboard Tab`);

    if (axeSource) {
      await page.addScriptTag({ content: axeSource });
      const ax = await page.evaluate(async () => (await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] } }))
        .violations.map(v => ({ id: v.id, impact: v.impact, n: v.nodes.length, help: v.help })));
      report.axe = ax;
      const serious = ax.filter(v => ['serious', 'critical'].includes(v.impact));
      serious.length ? fail(`axe: ${serious.map(v => `${v.id}(${v.n})`).join(', ')}`) : pass('axe-core: no serious/critical WCAG 2.2 AA violations');
      const minor = ax.filter(v => !['serious', 'critical'].includes(v.impact));
      if (minor.length) warn(`axe minor: ${minor.map(v => `${v.id}(${v.n})`).join(', ')}`);
    } else warn('axe-core not installed: deeper WCAG audit skipped (npm i -g axe-core, NODE_PATH=$(npm root -g))');
    await ctx.close();
  }

  // ======================= phone: form behaviour =======================
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: 'he-IL' });
    const page = await ctx.newPage();
    await page.goto(url, { waitUntil: 'load' }); await settle(page);
    const formSel = await page.evaluate(() => { const f = document.querySelector('form[data-lead-form]') || [...document.querySelectorAll('form')].find(x => x.querySelector('[required]'));
      if (!f) return null; f.setAttribute('data-qa-form', '1'); return '[data-qa-form]'; });
    if (formSel) {
      const before = page.url();
      const btn = page.locator(`${formSel} [type=submit]`).first();
      await btn.scrollIntoViewIfNeeded(); await btn.click(); await page.waitForTimeout(500);
      const r = await page.evaluate((sel) => {
        const f = document.querySelector(sel);
        const invalid = f ? f.querySelectorAll('[aria-invalid="true"]').length : 0;
        const msgs = f ? [...f.querySelectorAll('.field__error, [role=alert], .error, [id$="-err"]')].filter(e => e.textContent.trim()).length : 0;
        const ae = document.activeElement; return { invalid, msgs, focusInForm: !!(f && f.contains(ae) && ae.tagName !== 'BUTTON'), nativeInvalid: f ? f.querySelectorAll(':invalid').length : 0, novalidate: f ? f.noValidate : false };
      }, formSel);
      const shot = path.join(OUT, 'phone390_form_errors.png');
      await page.screenshot({ path: shot });
      if (page.url() !== before && !page.url().startsWith(before.split('#')[0])) fail('empty form submit navigated away (no validation)');
      else if (r.novalidate && !r.invalid && !r.msgs) fail('empty form submit shows no error messages (novalidate without custom validation)');
      else if (r.invalid || r.msgs) pass(`empty submit shows ${r.msgs || r.invalid} error message(s)${r.focusInForm ? ', focus moved to first error' : ''} (${shot})`);
      else pass('empty submit blocked by browser validation (consider custom Hebrew messages)');
      if ((r.invalid || r.msgs) && !r.focusInForm) warn('after a failed submit, focus does not move to the first invalid field');
    } else warn('no form found: is there a way to act (call/WhatsApp/form)?');
    await ctx.close();
  }

  // ======================= phone: performance under throttling =======================
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
    const page = await ctx.newPage();
    const cdp = await ctx.newCDPSession(page);
    await cdp.send('Network.enable');
    await cdp.send('Network.setCacheDisabled', { cacheDisabled: true });
    await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: 1.6 * 1024 * 1024 / 8, uploadThroughput: 750 * 1024 / 8 });
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    await page.addInitScript(() => {
      window.__qa = { lcp: 0, cls: 0, tbt: 0, lcpEl: '' };
      try {
        new PerformanceObserver(l => { for (const e of l.getEntries()) { window.__qa.lcp = e.startTime; const el = e.element; window.__qa.lcpEl = el ? el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ')[0] : '') : ''; } }).observe({ type: 'largest-contentful-paint', buffered: true });
        new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__qa.cls += e.value; }).observe({ type: 'layout-shift', buffered: true });
        new PerformanceObserver(l => { for (const e of l.getEntries()) window.__qa.tbt += Math.max(0, e.duration - 50); }).observe({ type: 'longtask', buffered: true });
      } catch {}
    });
    const t0 = Date.now();
    await page.goto(url, { waitUntil: 'load', timeout: 60000 });
    try { await page.waitForLoadState('networkidle', { timeout: 15000 }); } catch {}
    await page.waitForTimeout(1500);
    const m = await page.evaluate(() => {
      const res = performance.getEntriesByType('resource'); const nav = performance.getEntriesByType('navigation')[0];
      const by = { html: nav ? nav.transferSize || nav.encodedBodySize : 0, css: 0, js: 0, font: 0, img: 0, other: 0 };
      for (const r of res) { const sz = r.transferSize || r.encodedBodySize || 0; const u = r.name.split('?')[0];
        const k = /\.css$/.test(u) ? 'css' : /\.m?js$/.test(u) ? 'js' : /\.(woff2?|ttf|otf)$/.test(u) ? 'font' : /\.(png|jpe?g|webp|avif|gif|svg)$/.test(u) || r.initiatorType === 'img' ? 'img' : 'other'; by[k] += sz; }
      const fcp = performance.getEntriesByName('first-contentful-paint')[0];
      return { ...window.__qa, fcp: fcp ? fcp.startTime : null, by, total: Object.values(by).reduce((a, b) => a + b, 0), requests: res.length + 1 };
    });
    m.wall = Date.now() - t0;
    report.perf = m;
    const kb = n => Math.round(n / 1024) + 'KB';
    const PP = '[perf phone, 1.6Mbps/150ms/4xCPU]';
    console.log(`\n=== PERF === LCP ${Math.round(m.lcp)}ms (${m.lcpEl}), FCP ${Math.round(m.fcp)}ms, CLS ${m.cls.toFixed(3)}, TBT ${Math.round(m.tbt)}ms, ` +
      `${m.requests} requests, ${kb(m.total)} (html ${kb(m.by.html)}, css ${kb(m.by.css)}, js ${kb(m.by.js)}, fonts ${kb(m.by.font)}, img ${kb(m.by.img)})`);
    m.lcp <= 2500 ? pass(`${PP} LCP ${Math.round(m.lcp)}ms <= 2500`) : fail(`${PP} LCP ${Math.round(m.lcp)}ms > 2500 (element: ${m.lcpEl})`);
    m.cls <= 0.1 ? pass(`${PP} CLS ${m.cls.toFixed(3)} <= 0.1`) : fail(`${PP} CLS ${m.cls.toFixed(3)} > 0.1`);
    m.tbt <= 200 ? pass(`${PP} TBT ${Math.round(m.tbt)}ms <= 200`) : warn(`${PP} TBT ${Math.round(m.tbt)}ms > 200 (slow to respond to taps)`);
    m.total > 2 * 1024 * 1024 ? fail(`${PP} page weight ${kb(m.total)} > 2MB`) : m.total > 1024 * 1024 ? warn(`${PP} page weight ${kb(m.total)} > 1MB`) : pass(`${PP} page weight ${kb(m.total)}`);
    if (m.by.js > 150 * 1024) warn(`${PP} JavaScript ${kb(m.by.js)} > 150KB`);
    await ctx.close();
  }
} finally {
  await browser.close();
  if (server) server.close();
}

console.log('\n=== SUMMARY ===');
for (const [s, m] of results) console.log(`${s.padEnd(5)} ${m}`);
const nFail = results.filter(r => r[0] === 'FAIL').length, nWarn = results.filter(r => r[0] === 'WARN').length;
report.summary = { fail: nFail, warn: nWarn, results };
fs.writeFileSync(path.join(OUT, 'qa_report.json'), JSON.stringify(report, null, 2));
console.log(`\n${nFail} FAIL, ${nWarn} WARN   (report: ${path.join(OUT, 'qa_report.json')})`);
console.log('NEXT: LOOK at every screenshot (phone360/390, tablet768, desktop1440, form errors). Then an independent critic');
console.log('scores the page against "רף הסוכנות" in references/website-store.md. Automated checks cannot judge design or copy.');
process.exit(nFail ? 1 : 0);
