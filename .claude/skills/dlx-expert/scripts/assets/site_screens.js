// site_screens.js - clean, phone-size (iPhone 13 @3x) full-page screenshots of a real website, for use
// inside a video (scrolled inside a code-built phone). Hides cookie banners, WhatsApp / chat bubbles and
// push popups, which otherwise cover the content.
//
// Usage: node site_screens.js <outdir> <name1>=<url1> [<name2>=<url2> ...]
// Example: node site_screens.js ./site home=https://example.com/ cat=https://example.com/category/
// Output: <outdir>/<name>.png  (1170px wide). Also prints the page width: if it is wider than the
// viewport, the site overflows horizontally on mobile - report that to the client.
const {chromium, devices} = require('playwright');
const [out, ...pairs] = process.argv.slice(2);
if (!out || !pairs.length) { console.error('Usage: node site_screens.js <outdir> name=url ...'); process.exit(2); }
const HIDE = '[class*="whatsapp"],[id*="whatsapp"],a[href*="wa.me"],a[href*="whatsapp"],[class*="onesignal"],[id*="onesignal"],.joinchat,[class*="cookie"],[id*="cookie"],[class*="popup"],[class*="push"],[class*="chat-widget"],[id*="chat-widget"]';
(async () => {
  const b = await chromium.launch();
  const c = await b.newContext({...devices['iPhone 13'], deviceScaleFactor: 3, locale: 'he-IL'});
  const p = await c.newPage();
  for (const pair of pairs) {
    const i = pair.indexOf('='); const name = pair.slice(0, i); const url = pair.slice(i + 1);
    await p.goto(url, {waitUntil: 'networkidle', timeout: 60000});
    await p.evaluate((sel) => {
      const f = () => document.querySelectorAll(sel).forEach((e) => e.style.setProperty('display', 'none', 'important'));
      f(); new MutationObserver(f).observe(document.body, {childList: true, subtree: true});
    }, HIDE);
    await p.waitForTimeout(1500);
    try { await p.getByText(/^(הבנתי|אישור|Accept|OK|I agree)$/).first().click({timeout: 2000}); } catch (e) {}
    for (let k = 0; k < 8; k++) { await p.mouse.wheel(0, 700); await p.waitForTimeout(400); } // load lazy images
    await p.evaluate(() => {
      document.querySelectorAll('body *').forEach((e) => {
        const cs = getComputedStyle(e); const t = e.innerText || '';
        if ((cs.position === 'fixed' || cs.position === 'sticky') && /עוגיות|cookie|whatsapp|WhatsApp/i.test(t) && !/חפש|search/i.test(t)) e.style.setProperty('display', 'none', 'important');
      });
      scrollTo(0, 0);
    });
    await p.waitForTimeout(800);
    const w = await p.evaluate(() => document.documentElement.scrollWidth);
    await p.screenshot({path: `${out}/${name}.png`, fullPage: true});
    console.log(`${name}: saved (page width ${w}px vs viewport 390px${w > 392 ? ' - OVERFLOWS on mobile' : ''})`);
  }
  await b.close();
})();
