#!/usr/bin/env node
// qa_authz.mjs <config.json> [report.json]
// Authorization probe for any web app/API (OWASP A01:2025 Broken Access Control, A07 Authentication, ASVS V8/V3).
// Logs in real users: A is the owner, EVERY other user is an attacker. For every resource of A it tries the call as
// each attacker and as anonymous. Any 2xx, any of A's data in the response, or ANY change to A's data afterwards = FAIL.
// Also checks:
//   - each user is really logged in as themself (whoami), so a broken login cannot fake a "refused"
//   - session cookies HttpOnly/Secure/SameSite; session id rotated at login (fixation); logout kills the session
//   - security headers on EVERY page and API response listed (CSP, nosniff, frame protection, HSTS on https)
//   - every state-changing <form> has a CSRF token; a call without a token is refused; another user's token is refused
//   - login rate limiting (optional block), protected pages not served to anonymous, owner data not cacheable
// Node 18+ (built-in fetch), no dependencies. Exit 1 on any FAIL. Run against local/staging only: it sends real
// state-changing requests.
//
// Config (full example: templates/system-blueprint/authz.config.example.json). "${env:NAME}" is replaced by an
// environment variable, so passwords stay out of files.
// {
//   "baseUrl": "http://127.0.0.1:3000",
//   "allowInsecureCookiesOnLocalhost": false,
//   "csrf": { "fieldNames": ["_csrf"], "headerName": "x-csrf-token" },
//   "users": {
//     "A": { "login": { "path": "/login", "csrfFrom": "/login", "form": { "username": "a", "password": "${env:QA_PASS_A}" } },
//            "whoami": { "path": "/me", "marker": "Store A" }, "csrfPage": "/orders/1" },
//     "B": { ... same shape ... }            // more users (C, D...) = more attackers; or "cookie" / "headers" instead of login
//   },
//   "pages": ["/orders", "/orders/1"],         // fetched as A: headers + CSRF field in every POST form
//   "protectedPages": ["/orders", "/admin"],   // must NOT be served to anonymous
//   "logout": { "method": "POST", "path": "/logout" },
//   "rateLimit": { "path": "/login", "csrfFrom": "/login", "form": { "username": "a", "password": "wrong" }, "attempts": 20 },
//   "resources": [
//     { "name": "A's order", "path": "/api/orders/1", "ownerMarkers": ["Dana Cohen", "050-0000001"] },
//     { "name": "change A's status", "method": "POST", "path": "/api/orders/1/status", "json": { "status": "done" },
//       "stateChanging": true, "verify": { "path": "/api/orders/1" } }
//   ]
// }
import fs from 'fs';

const [, , cfgPath, reportPath] = process.argv;
if (!cfgPath) { console.error('Usage: node qa_authz.mjs <config.json> [report.json]'); process.exit(2); }
const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8').replace(/\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}/g, (_, n) => {
  if (process.env[n] === undefined) { console.error(`config needs environment variable ${n}`); process.exit(2); }
  return JSON.stringify(process.env[n]).slice(1, -1);
}));
const BASE = cfg.baseUrl.replace(/\/$/, '');
const isHttps = BASE.startsWith('https:');
const isLocal = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(BASE);
const CSRF_FIELDS = (cfg.csrf?.fieldNames || ['_csrf', 'csrf_token', 'csrfToken', 'authenticity_token',
  'csrfmiddlewaretoken', '__RequestVerificationToken', '_token']).map(s => s.toLowerCase());
const CSRF_HEADER = cfg.csrf?.headerName || 'x-csrf-token';
const M = r => (r.method || 'GET').toUpperCase();
const isChanging = r => r.stateChanging || !['GET', 'HEAD'].includes(M(r));
const is2xx = s => s >= 200 && s < 300;

const results = [];
const pass = m => results.push(['PASS', m]);
const warn = m => results.push(['WARN', m]);
const fail = m => results.push(['FAIL', m]);
const log = [];

// ---------- cookie jar + session ----------
function parseSetCookie(sc) {
  const [nv, ...attrs] = sc.split(';').map(s => s.trim());
  const i = nv.indexOf('=');
  const c = { name: nv.slice(0, i), value: nv.slice(i + 1), raw: sc, attrs: {} };
  for (const a of attrs) { const [k, ...v] = a.split('='); c.attrs[k.toLowerCase()] = v.join('=') || true; }
  return c;
}
class Session {
  constructor(name, spec = {}) { this.name = name; this.spec = spec; this.jar = new Map(); this.headers = { ...(spec.headers || {}) }; this.setCookies = []; this.csrf = null;
    if (spec.cookie) for (const part of spec.cookie.split(';')) { const [k, ...v] = part.trim().split('='); if (k) this.jar.set(k, v.join('=')); } }
  cookieHeader() { return [...this.jar].map(([k, v]) => `${k}=${v}`).join('; '); }
  absorb(res) {
    const list = typeof res.headers.getSetCookie === 'function' ? res.headers.getSetCookie() : [];
    for (const sc of list) { const c = parseSetCookie(sc); this.setCookies.push(c);
      if (c.attrs['max-age'] === '0' || /expires=thu, 01 jan 1970/i.test(sc)) this.jar.delete(c.name); else this.jar.set(c.name, c.value); }
  }
  async req(method, path, { json, form, headers = {}, csrf = true, token = null, redirect = 'manual' } = {}) {
    const h = { 'User-Agent': 'qa_authz/2.0', ...this.headers, ...headers };
    const ck = this.cookieHeader(); if (ck) h.Cookie = ck;
    const tok = token || (csrf ? this.csrf : null);
    let body;
    const changing = !['GET', 'HEAD', 'OPTIONS'].includes(method);
    if (json !== undefined) { if (changing && tok) h[CSRF_HEADER] = tok.value; h['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
    else if (form !== undefined) { const f = { ...form }; if (changing && tok) f[tok.field] = tok.value;
      h['Content-Type'] = 'application/x-www-form-urlencoded'; body = new URLSearchParams(f).toString(); }
    else if (changing && tok) h[CSRF_HEADER] = tok.value;
    const res = await fetch(path.startsWith('http') ? path : BASE + path, { method, headers: h, body, redirect });
    this.absorb(res);
    const text = await res.text();
    log.push({ who: this.name, method, path, status: res.status, location: res.headers.get('location') || undefined, bytes: text.length });
    return { status: res.status, headers: res.headers, text };
  }
}

function findCsrf(html) {
  for (const m of html.matchAll(/<input\b[^>]*>/gi)) {
    const tag = m[0]; const name = (tag.match(/name\s*=\s*["']([^"']+)/i) || [])[1];
    const value = (tag.match(/value\s*=\s*["']([^"']*)/i) || [])[1];
    if (name && CSRF_FIELDS.includes(name.toLowerCase()) && value) return { field: name, value };
  }
  const meta = html.match(/<meta\b[^>]*name\s*=\s*["']csrf-token["'][^>]*content\s*=\s*["']([^"']+)/i);
  return meta ? { field: CSRF_FIELDS[0], value: meta[1] } : null;
}

// the same data can arrive JSON-escaped (ר...), as HTML entities or URL-encoded: match all forms
function variants(m) {
  const map = f => [...m].map(ch => ch.charCodeAt(0) > 127 ? f(ch.charCodeAt(0)) : ch).join('');
  return [...new Set([m, map(c => '\\u' + c.toString(16).padStart(4, '0')), map(c => '\\u' + c.toString(16).toUpperCase().padStart(4, '0')),
    map(c => `&#${c};`), map(c => `&#x${c.toString(16)};`), encodeURIComponent(m)])];
}
const contains = (text, markers) => markers.find(mk => variants(mk).some(v => text.includes(v)));
// personal data that is easy to recognise automatically in A's own response (phones, e-mails, Israeli ID-like numbers)
function autoMarkers(text) {
  const out = new Set();
  for (const m of text.matchAll(/\+?\d[\d\- ]{7,}\d/g)) out.add(m[0]);
  for (const m of text.matchAll(/[\w.+-]+@[\w-]+\.[\w.]+/g)) out.add(m[0]);
  return [...out].slice(0, 20);
}

async function login(name, spec) {
  const s = new Session(name, spec);
  if (spec.login) {
    const L = spec.login;
    let pre = new Map();
    if (L.csrfFrom) { const pg = await s.req('GET', L.csrfFrom); s.csrf = findCsrf(pg.text); pre = new Map(s.jar); }
    const r = await s.req(L.method || 'POST', L.path, { form: L.form, json: L.json });
    if (r.status >= 400) { fail(`[${name}] login failed: HTTP ${r.status} on ${L.path}`); return null; }
    if (!s.jar.size && !Object.keys(s.headers).length) { fail(`[${name}] login returned no session cookie or token`); return null; }
    s.csrf = null;   // the pre-login token belongs to the old session
    // session fixation: a cookie that existed before login must not keep its value after login
    const kept = [...pre].filter(([k, v]) => s.jar.get(k) === v).map(([k]) => k);
    if (pre.size) kept.length ? fail(`[${name}] session id NOT rotated at login (cookie ${kept.join(', ')} kept its pre-login value): session fixation`)
                              : pass(`[${name}] session id rotated at login`);
  }
  // whoami: prove the session really belongs to this user (a failed login otherwise looks like a "refused" attack)
  if (!spec.whoami) fail(`[${name}] no "whoami" {path, marker} in config: cannot prove this user is logged in, so refusals prove nothing`);
  else {
    const w = await s.req('GET', spec.whoami.path);
    is2xx(w.status) && contains(w.text, [spec.whoami.marker]) ? pass(`[${name}] logged in as themself (whoami ${spec.whoami.path} shows "${spec.whoami.marker}")`)
      : fail(`[${name}] whoami ${spec.whoami.path}: HTTP ${w.status} without "${spec.whoami.marker}": NOT logged in as ${name}`);
    s.whoText = w.text;
  }
  const tp = spec.csrfPage || cfg.csrf?.tokenPage;   // one of THIS user's pages that renders a form with a token
  if (tp) { const pg = await s.req('GET', tp); const t = findCsrf(pg.text); if (t) s.csrf = t; }
  if ((cfg.resources || []).some(isChanging) && s.jar.size && !s.csrf)
    warn(`[${name}] no CSRF token for this user (set users.${name}.csrfPage to one of ITS pages with a form): ` +
         'state-changing refusals may come from CSRF, not authorization, so they are inconclusive');
  return s;
}

function checkCookies(s) {
  const seen = new Map();
  for (const c of s.setCookies) seen.set(c.name, c);
  if (!seen.size) { warn(`[${s.name}] no Set-Cookie observed (token auth?): cookie flags not checked`); return; }
  for (const c of seen.values()) {
    if (!(/sess|sid|auth|token|login|jwt|remember/i.test(c.name) || seen.size <= 2)) continue;
    const probs = [];
    if (!c.attrs.httponly) probs.push('no HttpOnly (JavaScript can steal it)');
    if (!c.attrs.secure) probs.push('no Secure (sent over plain http)');
    const ss = String(c.attrs.samesite || '').toLowerCase();
    if (!ss) probs.push('no SameSite'); else if (ss === 'none' && !c.attrs.secure) probs.push('SameSite=None without Secure');
    const onlySecure = probs.length === 1 && probs[0].startsWith('no Secure');
    if (!probs.length) pass(`cookie "${c.name}": HttpOnly; Secure; SameSite=${c.attrs.samesite}`);
    else if (onlySecure && isLocal && cfg.allowInsecureCookiesOnLocalhost) warn(`cookie "${c.name}": ${probs.join(', ')} (localhost only; MUST be Secure in production)`);
    else fail(`cookie "${c.name}": ${probs.join(', ')}`);
  }
}

const checkedHeaders = new Set();
function checkHeaders(where, h, kind) {
  const key = `${kind}:${where}`; if (checkedHeaders.has(key)) return; checkedHeaders.add(key);
  const csp = h.get('content-security-policy'), xfo = h.get('x-frame-options');
  const miss = [], weak = [];
  if (h.get('x-content-type-options')?.toLowerCase() !== 'nosniff') miss.push('X-Content-Type-Options: nosniff');
  if (kind === 'page') {
    if (!csp) miss.push('Content-Security-Policy');
    else { if (/script-src[^;]*unsafe-inline/.test(csp) || (!/script-src/.test(csp) && /default-src[^;]*unsafe-inline/.test(csp))) weak.push("CSP allows inline scripts");
      if (!/default-src|script-src/.test(csp)) miss.push('CSP default-src/script-src'); }
    if (!(xfo || /frame-ancestors/.test(csp || ''))) miss.push('frame protection (X-Frame-Options or CSP frame-ancestors)');
    if (!h.get('referrer-policy')) weak.push('no Referrer-Policy');
  }
  if (isHttps && !h.get('strict-transport-security')) miss.push('Strict-Transport-Security');
  if (h.get('x-powered-by')) weak.push(`X-Powered-By leaks "${h.get('x-powered-by')}"`);
  miss.length ? fail(`${kind} headers ${where}: missing ${miss.join(', ')}`) : pass(`${kind} security headers ${where}`);
  for (const w of weak) warn(`${kind} ${where}: ${w}`);
}

// ---------- attacks ----------
const ownerBodies = new Map();
async function snapshot(A, r) {
  if (!r.verify) return null;
  const v = await A.req('GET', r.verify.path);
  return is2xx(v.status) ? v.text : null;
}
async function attempt(who, sess, r, A) {
  const before = await snapshot(A, r);
  const res = await sess.req(M(r), r.path, { json: r.json, form: r.form, headers: r.headers });
  const after = before !== null ? await snapshot(A, r) : null;
  const tag = `${who} -> ${M(r)} ${r.path} (${r.name})`;
  const markers = [...(r.ownerMarkers || []), ...(r.ownerMarker ? [r.ownerMarker] : []), ...autoMarkers(ownerBodies.get(r.path) || '')];
  // only flag markers the attacker could not legitimately see in its own data
  const leakedMarker = contains(res.text, markers.filter(mk => !(sess.whoText || '').includes(mk)));
  const same = is2xx(res.status) && ownerBodies.has(r.path) && ownerBodies.get(r.path).length > 20 && res.text === ownerBodies.get(r.path);
  if (before !== null && after !== null && before !== after)
    return fail(`${tag}: HTTP ${res.status} BUT A's data CHANGED (${r.verify.path} differs after the attempt): write happened before/without the ownership check`);
  if (isChanging(r) && !r.verify) warn(`${tag}: no "verify" path, so a write that answers 4xx but still saves would go unnoticed`);
  if (leakedMarker || same) return fail(`${tag}: HTTP ${res.status} and the response contains A's data (${leakedMarker ? '"' + leakedMarker + '"' : 'identical to A\'s response'})`);
  if (is2xx(res.status) && !r.allowEmpty2xx) return fail(`${tag}: HTTP ${res.status}: succeeded but must be refused (403/404/401)`);
  if (is2xx(res.status)) return warn(`${tag}: HTTP ${res.status} without A's data (allowEmpty2xx): confirm by eye`);
  if (res.status >= 500) return warn(`${tag}: HTTP ${res.status} (refused by crashing: return 403/404 cleanly)`);
  const toLogin = res.status >= 300 && res.status < 400 && /login|signin|auth/i.test(res.headers.get('location') || '');
  pass(`${tag}: refused (HTTP ${res.status}${toLogin ? ' -> login' : ''})${before !== null ? ', A\'s data unchanged' : ''}`);
}

// ---------- run ----------
const sessions = {};
for (const [name, spec] of Object.entries(cfg.users || {})) sessions[name] = await login(name, spec);
const A = sessions.A;
const attackers = Object.entries(sessions).filter(([n, s]) => n !== 'A' && s);
const anon = new Session('anonymous');
if (!A || !attackers.length || Object.values(sessions).some(s => !s)) fail('need user A (owner) and at least one other working user in config.users');
else {
  checkCookies(A);
  for (const p of cfg.pages || []) {
    const r = await A.req('GET', p);
    if (r.status >= 400) { fail(`[A] page ${p} returned HTTP ${r.status}`); continue; }
    checkHeaders(p, r.headers, 'page');
    for (const f of r.text.matchAll(/<form\b([^>]*)>([\s\S]*?)<\/form>/gi)) {
      const method = ((f[1].match(/method\s*=\s*["']?(\w+)/i) || [])[1] || 'GET').toUpperCase();
      if (method === 'GET') continue;
      const action = (f[1].match(/action\s*=\s*["']([^"']*)/i) || [])[1] || p;
      findCsrf(f[2]) ? pass(`form ${method} ${action} on ${p} has a CSRF token`)
                     : fail(`form ${method} ${action} on ${p} has NO CSRF token field`);
    }
  }
  for (const p of cfg.protectedPages || []) {
    const r = await anon.req('GET', p);
    is2xx(r.status) && !/name=["']?password/i.test(r.text)
      ? fail(`anonymous GET ${p}: HTTP ${r.status}: protected page served without login`)
      : pass(`anonymous GET ${p}: refused (HTTP ${r.status}${r.headers.get('location') ? ' -> ' + r.headers.get('location') : ''})`);
  }
  for (const r of cfg.resources || []) if (!isChanging(r)) {
    const o = await A.req('GET', r.path, { headers: r.headers });
    if (is2xx(o.status)) ownerBodies.set(r.path, o.text);
  }
  // attacks before the owner baseline, so a destructive baseline cannot hide them
  for (const r of cfg.resources || []) {
    await attempt('anonymous', anon, r, A);
    for (const [n, s] of attackers) await attempt(n, s, r, A);
  }
  for (const r of cfg.resources || []) {
    if (r.baseline === false) continue;
    // CSRF first, while the call would still succeed for the owner: no token, then another user's token
    if (isChanging(r) && A.jar.size && r.csrfCheck !== false && !r.ownerMustBeRefused) {
      for (const [label, opts] of [['without a token from a foreign Origin', { headers: { Origin: 'https://evil.example' }, csrf: false }],
                                   ["with ANOTHER user's token", { token: attackers.map(([, x]) => x.csrf).find(t => t && t.value !== A.csrf?.value) }]]) {
        if ('token' in opts && !opts.token) continue;
        const before = await snapshot(A, r);
        const nr = await A.req(M(r), r.path, { json: r.json, form: r.form, ...opts });
        const after = before !== null ? await snapshot(A, r) : null;
        is2xx(nr.status) || (before !== null && before !== after)
          ? fail(`CSRF: ${M(r)} ${r.path} accepted ${label} (HTTP ${nr.status}${before !== after ? ', data changed' : ''})`)
          : pass(`CSRF: ${M(r)} ${r.path} ${label} refused (HTTP ${nr.status})`);
      }
      if (!r.verify) warn(`CSRF: ${r.path} has no "verify" path, so a refused-but-saved CSRF write would go unnoticed`);
    }
    if (r.ownerMustBeRefused) {   // a business rule: even the owner may not do this (e.g. a store marking "delivered")
      const before = await snapshot(A, r);
      const res = await A.req(M(r), r.path, { json: r.json, form: r.form, headers: r.headers });
      const after = before !== null ? await snapshot(A, r) : null;
      is2xx(res.status) || (before !== null && before !== after)
        ? fail(`rule: A -> ${M(r)} ${r.path} (${r.name}) must be refused even for the owner, got HTTP ${res.status}${before !== after ? ' and data changed' : ''}`)
        : pass(`rule: A -> ${M(r)} ${r.path} (${r.name}) refused for the owner too (HTTP ${res.status})`);
      continue;
    }
    const res = await A.req(M(r), r.path, { json: r.json, form: r.form, headers: r.headers });
    const mk = [...(r.ownerMarkers || []), ...(r.ownerMarker ? [r.ownerMarker] : [])];
    const ok = is2xx(res.status) && (!mk.length || contains(res.text, mk));
    ok ? pass(`baseline A -> ${M(r)} ${r.path}: HTTP ${res.status} (the owner can, so the refusals above mean something)`)
       : fail(`baseline A -> ${M(r)} ${r.path}: HTTP ${res.status}: the OWNER cannot do it, so this check proves nothing. Fix the config`);
    if (ok) {
      checkHeaders(r.path, res.headers, /json/i.test(res.headers.get('content-type') || '') ? 'api' : 'page');
      if (mk.length && !/no-store|private/.test((res.headers.get('cache-control') || '').toLowerCase()))
        warn(`${r.path}: owner data without Cache-Control: no-store/private`);
    }
  }
  if (cfg.rateLimit) {
    const RL = cfg.rateLimit, n = RL.attempts || 20;
    let limited = null;
    for (let i = 0; i < n && !limited; i++) {
      const s = new Session('ratelimit');
      if (RL.csrfFrom) { const pg = await s.req('GET', RL.csrfFrom); s.csrf = findCsrf(pg.text); }
      const r = await s.req(RL.method || 'POST', RL.path, { form: RL.form, json: RL.json });
      if ([429, 423].includes(r.status) || /too many|try again later|נסה שוב מאוחר|יותר מדי/i.test(r.text)) limited = i + 1;
    }
    limited ? pass(`rate limit: ${RL.path} blocked after ${limited} wrong attempts`)
            : fail(`rate limit: ${n} wrong attempts on ${RL.path} and none was blocked (brute force possible)`);
  } else warn('no "rateLimit" block in config: login brute-force protection not tested');
  if (cfg.logout && A.spec.whoami) {
    const stolen = new Session('stolen-cookie'); stolen.jar = new Map(A.jar);
    if (cfg.logout.csrfFrom) { const t = findCsrf((await A.req('GET', cfg.logout.csrfFrom)).text); if (t) A.csrf = t; }
    const lo = await A.req(cfg.logout.method || 'POST', cfg.logout.path, { form: cfg.logout.form || {} });
    if (lo.status >= 400) fail(`logout: ${cfg.logout.path} itself was refused (HTTP ${lo.status}); a user cannot log out`);
    const w = await stolen.req('GET', A.spec.whoami.path);
    is2xx(w.status) && contains(w.text, [A.spec.whoami.marker])
      ? fail(`logout: the old session cookie still works after ${cfg.logout.path} (session not killed on the server)`)
      : pass(`logout: old session cookie refused after logout (HTTP ${w.status})`);
  } else warn('no "logout" block in config: server-side logout not tested');
}

console.log('\n=== AUTHZ PROBE SUMMARY ===');
for (const [s, m] of results) console.log(`${s.padEnd(5)} ${m}`);
const nFail = results.filter(r => r[0] === 'FAIL').length, nWarn = results.filter(r => r[0] === 'WARN').length;
console.log(`\n${nFail} FAIL, ${nWarn} WARN  (${log.length} requests sent)`);
console.log('NEXT: this covers only what the config lists. Every route that takes an id (read, update, delete, export,');
console.log('file download) needs a resource entry with "verify" for writes, and every role pair needs its own users.');
if (reportPath) fs.writeFileSync(reportPath, JSON.stringify({ base: BASE, results, requests: log }, null, 2));
process.exit(nFail ? 1 : 0);
