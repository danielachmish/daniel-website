#!/usr/bin/env node
// qa_web.mjs <url-or-file> [outdir]
// Mandatory web QA before delivery: phone + desktop screenshots, console errors, failed requests,
// mobile horizontal overflow, basic accessibility, tiny text, rough load timing.
// Prints PASS/WARN/FAIL summary; exits 1 if any FAIL.
import { createRequire } from 'module';
import fs from 'fs';
import path from 'path';
import { pathToFileURL } from 'url';

const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require('playwright')); }
catch { console.error('playwright not found (try NODE_PATH to global node_modules)'); process.exit(2); }

const [, , target, outArg] = process.argv;
if (!target) { console.error('Usage: node qa_web.mjs <url-or-file> [outdir]'); process.exit(2); }
const OUT = path.resolve(outArg || './qa_web_out');
fs.mkdirSync(OUT, { recursive: true });
// Local files are served over a tiny in-process http server (file:// breaks ES modules, fetch, CORS).
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
    '.webp': 'image/webp', '.gif': 'image/gif', '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2',
    '.mp4': 'video/mp4', '.webm': 'video/webm', '.glb': 'model/gltf-binary', '.txt': 'text/plain' };
  server = http.createServer((req, res) => {
    let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    let f = path.join(root, p);
    if (!f.startsWith(root)) { res.writeHead(403).end(); return; }
    if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, 'index.html');
    if (!fs.existsSync(f)) { res.writeHead(404).end('not found'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(f).toLowerCase()] || 'application/octet-stream' });
    fs.createReadStream(f).pipe(res);
  });
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  url = `http://127.0.0.1:${server.address().port}/${entry}`;
  console.log(`Serving ${root} at ${url}`);
}

const results = [];
const pass = m => results.push(['PASS', m]);
const warn = m => results.push(['WARN', m]);
const fail = m => results.push(['FAIL', m]);

const VIEWPORTS = [
  { name: 'mobile', width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 1 },
  { name: 'desktop', width: 1440, height: 900, deviceScaleFactor: 1 },
];

const browser = await chromium.launch();
try {
  for (const vp of VIEWPORTS) {
    const ctx = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      isMobile: !!vp.isMobile, hasTouch: !!vp.hasTouch, deviceScaleFactor: vp.deviceScaleFactor,
    });
    const page = await ctx.newPage();
    const consoleErrors = [], failed = [];
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page.on('pageerror', e => consoleErrors.push('pageerror: ' + e.message));
    page.on('requestfailed', r => failed.push(`${r.failure()?.errorText || 'failed'} ${r.url()}`));
    page.on('response', r => { if (r.status() >= 400) failed.push(`HTTP ${r.status()} ${r.url()}`); });

    const t0 = Date.now();
    let navOk = true;
    try { await page.goto(url, { waitUntil: 'load', timeout: 30000 }); }
    catch (e) { navOk = false; fail(`[${vp.name}] page failed to load: ${e.message.split('\n')[0]}`); }
    const loadMs = Date.now() - t0;
    try { await page.waitForLoadState('networkidle', { timeout: 8000 }); } catch {}
    await page.waitForTimeout(800); // let entrance animations settle

    if (!navOk) { await ctx.close(); continue; }

    // scroll through to trigger lazy content, then back to top
    await page.evaluate(async () => {
      const step = window.innerHeight * 0.8;
      for (let y = 0; y < document.body.scrollHeight; y += step) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 120)); }
      window.scrollTo(0, 0);
    });
    await page.waitForTimeout(400);

    const shot = path.join(OUT, `${vp.name}_${vp.width}x${vp.height}_full.png`);
    await page.screenshot({ path: shot, fullPage: true });
    const fold = path.join(OUT, `${vp.name}_${vp.width}x${vp.height}_fold.png`);
    await page.screenshot({ path: fold, fullPage: false });

    const timing = await page.evaluate(() => {
      const n = performance.getEntriesByType('navigation')[0];
      const lcp = performance.getEntriesByType('largest-contentful-paint');
      return { dcl: n ? Math.round(n.domContentLoadedEventEnd) : null, load: n ? Math.round(n.loadEventEnd) : null };
    });

    const audit = await page.evaluate(() => {
      const vis = el => { const s = getComputedStyle(el); const r = el.getBoundingClientRect();
        return s.display !== 'none' && s.visibility !== 'hidden' && +s.opacity !== 0 && r.width > 0 && r.height > 0; };
      const desc = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') +
        (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
      const docW = document.documentElement.scrollWidth, winW = window.innerWidth;
      // elements sticking out of the viewport (catches RTL overflow to the left, which scrollWidth can miss),
      // ignoring ones clipped by a scrolling/hidden ancestor (carousels, marquees)
      const clipped = el => { for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        const o = getComputedStyle(a).overflowX; if (o === 'hidden' || o === 'auto' || o === 'scroll' || o === 'clip') return true; } return false; };
      const overflowers = [...document.querySelectorAll('body *')]
        .filter(e => { const r = e.getBoundingClientRect(); return vis(e) && (r.right > winW + 1 || r.left < -1) && !clipped(e); })
        .slice(0, 5).map(desc);
      const imgNoAlt = [...document.querySelectorAll('img')].filter(i => !i.hasAttribute('alt')).map(i => i.src.split('/').pop()).slice(0, 10);
      const inputs = [...document.querySelectorAll('input, select, textarea')]
        .filter(e => !['hidden', 'submit', 'button', 'reset', 'image'].includes(e.type));
      const inputNoLabel = inputs.filter(e => {
        if (e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') || e.title) return false;
        if (e.id && document.querySelector(`label[for="${CSS.escape(e.id)}"]`)) return false;
        if (e.closest('label')) return false;
        return true;
      }).map(desc).slice(0, 10);
      const btnNoName = [...document.querySelectorAll('button, [role=button], a[href]')].filter(b => vis(b) &&
        !(b.innerText || '').trim() && !b.getAttribute('aria-label') && !b.getAttribute('aria-labelledby') && !b.title &&
        !b.querySelector('img[alt]:not([alt=""]), svg title')).map(desc).slice(0, 10);
      const tiny = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const seen = new Set();
      while (walker.nextNode()) {
        const t = walker.currentNode; const el = t.parentElement;
        if (!el || seen.has(el) || !t.textContent.trim()) continue; seen.add(el);
        if (!vis(el)) continue;
        const fs = parseFloat(getComputedStyle(el).fontSize);
        if (fs < 12) tiny.push(`${fs}px "${t.textContent.trim().slice(0, 30)}"`);
      }
      return {
        docW, winW, overflowers, imgNoAlt, inputNoLabel, btnNoName, tiny: tiny.slice(0, 10), tinyCount: tiny.length,
        lang: document.documentElement.getAttribute('lang'), dir: document.documentElement.getAttribute('dir') || getComputedStyle(document.documentElement).direction,
        title: document.title, viewportMeta: !!document.querySelector('meta[name=viewport]'),
      };
    });

    const P = `[${vp.name}]`;
    console.log(`\n=== ${vp.name.toUpperCase()} ${vp.width}x${vp.height} ===`);
    console.log(`Screenshots: ${shot}\n             ${fold}`);
    console.log(`Load: ${loadMs}ms wall, DOMContentLoaded ${timing.dcl}ms, load ${timing.load}ms`);

    consoleErrors.length ? fail(`${P} ${consoleErrors.length} console error(s): ${consoleErrors.slice(0, 3).join(' | ')}`)
                         : pass(`${P} no console errors`);
    failed.length ? warn(`${P} ${failed.length} failed request(s): ${failed.slice(0, 3).join(' | ')}`)
                  : pass(`${P} no failed requests`);
    if (vp.name === 'mobile') {
      if (audit.docW > audit.winW + 1)
        fail(`${P} horizontal overflow: page ${audit.docW}px > viewport ${audit.winW}px (${audit.overflowers.join(', ')})`);
      else if (audit.overflowers.length)
        fail(`${P} elements extend outside the screen (cut off or scrollable sideways): ${audit.overflowers.join(', ')}`);
      else pass(`${P} no horizontal overflow`);
      audit.viewportMeta ? pass(`${P} viewport meta present`) : fail(`${P} missing <meta name=viewport>`);
    }
    audit.tinyCount ? warn(`${P} ${audit.tinyCount} visible text element(s) under 12px: ${audit.tiny.slice(0, 3).join(' | ')}`)
                    : pass(`${P} no text under 12px`);
    timing.load != null && timing.load > 4000 ? warn(`${P} slow load event ${timing.load}ms (target well under 2.5s LCP)`)
                                              : pass(`${P} load event ${timing.load}ms`);
    if (vp.name === 'desktop') {
      audit.imgNoAlt.length ? fail(`img without alt (${audit.imgNoAlt.length}): ${audit.imgNoAlt.join(', ')}`) : pass('all images have alt');
      audit.inputNoLabel.length ? fail(`form fields without label (${audit.inputNoLabel.length}): ${audit.inputNoLabel.join(', ')}`) : pass('all form fields labelled');
      audit.btnNoName.length ? warn(`buttons/links without accessible name (${audit.btnNoName.length}): ${audit.btnNoName.join(', ')}`) : pass('all buttons/links have accessible names');
      audit.lang ? pass(`html lang="${audit.lang}"`) : fail('html has no lang attribute');
      pass(`direction: ${audit.dir}${audit.lang && audit.lang.startsWith('he') && audit.dir !== 'rtl' ? ' (WARNING: Hebrew but not RTL)' : ''}`);
      if (audit.lang && audit.lang.startsWith('he') && audit.dir !== 'rtl') warn('Hebrew page is not dir=rtl');
      audit.title ? pass(`title: "${audit.title}"`) : fail('page has no <title>');
    }
    await ctx.close();
  }
} finally {
  await browser.close();
  if (server) server.close();
}

console.log('\n=== SUMMARY ===');
for (const [s, m] of results) console.log(`${s.padEnd(5)} ${m}`);
const nFail = results.filter(r => r[0] === 'FAIL').length, nWarn = results.filter(r => r[0] === 'WARN').length;
console.log(`\n${nFail} FAIL, ${nWarn} WARN`);
console.log('NEXT: open the screenshots and LOOK at them. Then click through every user flow (forms, cart, login) -');
console.log('automated checks cannot judge design quality, content, or business logic.');
process.exit(nFail ? 1 : 0);
