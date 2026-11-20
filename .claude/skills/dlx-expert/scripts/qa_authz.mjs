#!/usr/bin/env node
// qa_authz.mjs <config.json> [report.json]
// Authorization probe for any web app/API (OWASP A01:2025 Broken Access Control, ASVS V8 Authorization).
// Logs in two real users (A = owner, B = attacker), then for every resource owned by A tries it as B and as
// anonymous. ANY success = FAIL (IDOR / missing server-side authorization). Also checks:
//   - session cookies: HttpOnly, Secure, SameSite
//   - security headers on pages and API responses (CSP, nosniff, frame protection, HSTS on https, Referrer-Policy)
//   - every state-changing <form> has a CSRF token, and a state-changing call WITHOUT the token is rejected
//   - protected pages are not served to anonymous visitors; owner data responses are not cacheable
// Node 18+ only (built-in fetch), no dependencies. Exit 1 on any FAIL. Run against local/staging, never production
// data you do not own: the probe sends real state-changing requests.
//
// Config (see templates/system-blueprint/authz.config.example.json):
// {
//   "baseUrl": "http://127.0.0.1:3000",
//   "allowInsecureCookiesOnLocalhost": false,
//   "csrf": { "fieldNames": ["_csrf"], "headerName": "x-csrf-token", "tokenPage": "/shipments" },
//   "users": {
//     "A": { "login": { "method": "POST", "path": "/login", "form": { "username": "a", "password": "..." } } },
//     "B": { "login": {...}, "csrfPage": "/shipments/2001" }   |   { "cookie": "sid=..." }   |   { "headers": { "Authorization": "Bearer ..." } }
//   },
//   "pages":          ["/shipments", "/shipments/1"],         // fetched as A: headers + CSRF-in-forms
//   "protectedPages": ["/shipments", "/admin"],               // must NOT be served to anonymous
//   "resources": [
//     { "name": "A's shipment JSON", "method": "GET", "path": "/api/shipments/1", "ownerMarker": "Dana Cohen" },
//     { "name": "change A's status", "method": "POST", "path": "/api/shipments/1/status",
//       "json": { "status": "delivered" }, "stateChanging": true, "baseline": true }
//   ]
// }
import fs from 'fs';

const [, , cfgPath, reportPath] = process.argv;
if (!cfgPath) { console.error('Usage: node qa_authz.mjs <config.json> [report.json]'); process.exit(2); }
// "${env:NAME}" anywhere in the config is replaced by that environment variable (keep passwords out of files)
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

const results = [];
const pass = m => results.push(['PASS', m]);
const warn = m => results.push(['WARN', m]);
const fail = m => results.push(['FAIL', m]);
const log = [];

// ---------- tiny cookie jar ----------
function parseSetCookie(sc) {
  const [nv, ...attrs] = sc.split(';').map(s => s.trim());
  const i = nv.indexOf('=');
  const c = { name: nv.slice(0, i), value: nv.slice(i + 1), raw: sc, attrs: {} };
  for (const a of attrs) { const [k, ...v] = a.split('='); c.attrs[k.toLowerCase()] = v.join('=') || true; }
  return c;
}
class Session {
  constructor(name, spec = {}) { this.name = name; this.jar = new Map(); this.headers = { ...(spec.headers || {}) }; this.setCookies = []; this.csrf = null;
    if (spec.cookie) for (const part of spec.cookie.split(';')) { const [k, ...v] = part.trim().split('='); if (k) this.jar.set(k, v.join('=')); } }
  cookieHeader() { return [...this.jar].map(([k, v]) => `${k}=${v}`).join('; '); }
  absorb(res) {
    const list = typeof res.headers.getSetCookie === 'function' ? res.headers.getSetCookie() : [];
    for (const sc of list) { const c = parseSetCookie(sc); this.setCookies.push(c);
      if (c.attrs['max-age'] === '0' || /expires=thu, 01 jan 1970/i.test(sc)) this.jar.delete(c.name); else this.jar.set(c.name, c.value); }
  }
  async req(method, path, { json, form, headers = {}, csrf = true, redirect = 'manual' } = {}) {
    const h = { 'User-Agent': 'qa_authz/1.0', ...this.headers, ...headers };
    const ck = this.cookieHeader(); if (ck) h.Cookie = ck;
    let body;
    const changing = !['GET', 'HEAD', 'OPTIONS'].includes(method);
    if (json !== undefined) { const j = { ...json }; if (changing && csrf && this.csrf) { h[CSRF_HEADER] = this.csrf.value; }
      h['Content-Type'] = 'application/json'; body = JSON.stringify(j); }
    else if (form !== undefined) { const f = { ...form }; if (changing && csrf && this.csrf) f[this.csrf.field] = this.csrf.value;
      h['Content-Type'] = 'application/x-www-form-urlencoded'; body = new URLSearchParams(f).toString(); }
    else if (changing && csrf && this.csrf) { h[CSRF_HEADER] = this.csrf.value; }
    const url = path.startsWith('http') ? path : BASE + path;
    const res = await fetch(url, { method, headers: h, body, redirect });
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
  if (meta) return { field: CSRF_FIELDS[0], value: meta[1] };
  return null;
}

async function login(name, spec) {
  const s = new Session(name, spec);
  if (spec.login) {
    const L = spec.login;
    if (L.csrfFrom) { const pg = await s.req('GET', L.csrfFrom); s.csrf = findCsrf(pg.text); }
    const r = await s.req(L.method || 'POST', L.path, { form: L.form, json: L.json });
    if (r.status >= 400) { fail(`[${name}] login failed: HTTP ${r.status} on ${L.path}. Probe cannot continue for this user`); return null; }
    if (!s.jar.size && !Object.keys(s.headers).length) { fail(`[${name}] login returned no session cookie or token`); return null; }
    pass(`[${name}] logged in (${s.jar.size} cookie(s))`);
  }
  const tp = spec.csrfPage || cfg.csrf?.tokenPage;   // a page of THIS user's that renders a form with the token
  if (tp) { const pg = await s.req('GET', tp); const t = findCsrf(pg.text); if (t) s.csrf = t; }
  const changing = (cfg.resources || []).some(r => r.stateChanging || !['GET', 'HEAD'].includes((r.method || 'GET').toUpperCase()));
  if (changing && s.jar.size && !s.csrf)
    warn(`[${name}] no CSRF token found for this user (set users.${name}.csrfPage to one of ITS pages with a form): ` +
         'a refused attack may be stopped by CSRF, not by authorization, so state-changing results are inconclusive');
  return s;
}

function checkCookies(s) {
  const seen = new Map();
  for (const c of s.setCookies) seen.set(c.name, c);
  if (!seen.size) { warn(`[${s.name}] no Set-Cookie observed (token auth?): cookie flags not checked`); return; }
  for (const c of seen.values()) {
    const sessionish = /sess|sid|auth|token|login|jwt|remember/i.test(c.name) || s.setCookies.length <= 2;
    if (!sessionish) continue;
    const probs = [];
    if (!c.attrs.httponly) probs.push('no HttpOnly (JavaScript can steal it)');
    if (!c.attrs.secure) probs.push('no Secure (sent over plain http)');
    const ss = String(c.attrs.samesite || '').toLowerCase();
    if (!ss) probs.push('no SameSite');
    else if (ss === 'none' && !c.attrs.secure) probs.push('SameSite=None without Secure');
    const onlySecure = probs.length === 1 && probs[0].startsWith('no Secure');
    if (!probs.length) pass(`cookie "${c.name}": HttpOnly; Secure; SameSite=${c.attrs.samesite}`);
    else if (onlySecure && isLocal && cfg.allowInsecureCookiesOnLocalhost) warn(`cookie "${c.name}": ${probs.join(', ')} (allowed on localhost only; MUST be Secure in production)`);
    else fail(`cookie "${c.name}": ${probs.join(', ')}`);
  }
}

const reported = new Set();
function checkHeaders(where, h, kind) {
  const key = kind; if (reported.has(key)) return; reported.add(key);
  const csp = h.get('content-security-policy');
  const xfo = h.get('x-frame-options');
  const miss = [], weak = [];
  if (h.get('x-content-type-options')?.toLowerCase() !== 'nosniff') miss.push('X-Content-Type-Options: nosniff');
  if (kind === 'page') {
    if (!csp) miss.push('Content-Security-Policy');
    else { if (/unsafe-inline/.test(csp) && /script-src[^;]*unsafe-inline/.test(csp)) weak.push("CSP allows inline scripts ('unsafe-inline' in script-src)");
      if (!/default-src|script-src/.test(csp)) weak.push('CSP has no default-src/script-src'); }
    if (!(xfo || /frame-ancestors/.test(csp || ''))) miss.push('frame protection (X-Frame-Options or CSP frame-ancestors)');
    if (!h.get('referrer-policy')) weak.push('no Referrer-Policy');
  }
  if (isHttps && !h.get('strict-transport-security')) miss.push('Strict-Transport-Security');
  if (!isHttps) weak.push(isLocal ? 'HSTS not checked over http (check on the https staging URL)' : 'site served over plain http');
  if (h.get('x-powered-by')) weak.push(`X-Powered-By leaks "${h.get('x-powered-by')}"`);
  miss.length ? fail(`${kind} headers (${where}): missing ${miss.join(', ')}`) : pass(`${kind} security headers present (${where})`);
  for (const w of weak) warn(`${kind} (${where}): ${w}`);
}

// the same owner data can arrive JSON-escaped (\u05e8...) or as HTML entities (&#1512;...): match all forms
function markerVariants(m) {
  const u = [...m].map(ch => ch.charCodeAt(0) > 127 ? '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0') : ch).join('');
  const ent = [...m].map(ch => ch.charCodeAt(0) > 127 ? `&#${ch.charCodeAt(0)};` : ch).join('');
  const hex = [...m].map(ch => ch.charCodeAt(0) > 127 ? `&#x${ch.charCodeAt(0).toString(16)};` : ch).join('');
  return [...new Set([m, u, u.toUpperCase().replace(/\\U/g, '\\u'), ent, hex, encodeURIComponent(m)])];
}

async function attempt(who, sess, r) {
  const opts = { json: r.json, form: r.form, headers: r.headers };
  const res = await sess.req(r.method || 'GET', r.path, opts);
  const ok2xx = res.status >= 200 && res.status < 300;
  const redirectedToLogin = res.status >= 300 && res.status < 400 && /login|signin|auth/i.test(res.headers.get('location') || '');
  const leaked = (r.ownerMarker ? markerVariants(r.ownerMarker).some(v => res.text.includes(v)) : false)
    || (ok2xx && ownerBodies.has(r.path) && ownerBodies.get(r.path).length > 20 && res.text === ownerBodies.get(r.path));
  const changing = r.stateChanging || !['GET', 'HEAD'].includes((r.method || 'GET').toUpperCase());
  const tag = `${who} -> ${r.method || 'GET'} ${r.path} (${r.name})`;
  if (leaked) return fail(`${tag}: HTTP ${res.status} and the response CONTAINS A's data (${r.ownerMarker ? '"' + r.ownerMarker + '"' : "identical to A's own response"})`);
  if (ok2xx && (changing || r.ownerMarker === undefined)) return fail(`${tag}: HTTP ${res.status}: succeeded but must be refused`);
  if (ok2xx) return warn(`${tag}: HTTP ${res.status} without A's data: confirm it is an empty/denied page, prefer 403/404`);
  if (res.status >= 500) return warn(`${tag}: HTTP ${res.status} (refused by crashing: return 403/404 cleanly, and check logs)`);
  pass(`${tag}: refused (HTTP ${res.status}${redirectedToLogin ? ' -> login' : ''})`);
}

// ---------- run ----------
const ownerBodies = new Map();   // path -> A's own response to a safe GET, captured before the attacks
const sessions = {};
for (const [name, spec] of Object.entries(cfg.users || {})) sessions[name] = await login(name, spec);
const A = sessions.A, B = sessions.B, anon = new Session('anonymous');
if (!A || !B) { fail('need two working users A (owner) and B (other user) in config.users'); }
else {
  checkCookies(A);
  // pages as A: headers + CSRF token in every state-changing form
  for (const p of cfg.pages || []) {
    const r = await A.req('GET', p);
    if (r.status >= 400) { fail(`[A] page ${p} returned HTTP ${r.status}`); continue; }
    checkHeaders(p, r.headers, 'page');
    const forms = [...r.text.matchAll(/<form\b([^>]*)>([\s\S]*?)<\/form>/gi)];
    for (const f of forms) {
      const method = ((f[1].match(/method\s*=\s*["']?(\w+)/i) || [])[1] || 'GET').toUpperCase();
      if (method === 'GET') continue;
      const action = (f[1].match(/action\s*=\s*["']([^"']*)/i) || [])[1] || p;
      findCsrf(f[2]) ? pass(`form ${method} ${action} on ${p} has a CSRF token`)
                     : fail(`form ${method} ${action} on ${p} has NO CSRF token field (${CSRF_FIELDS.slice(0, 3).join('/')}...)`);
    }
  }
  // anonymous must not see protected pages
  for (const p of cfg.protectedPages || []) {
    const r = await anon.req('GET', p);
    const ok = r.status >= 200 && r.status < 300 && !/name=["']?password/i.test(r.text);
    ok ? fail(`anonymous GET ${p}: HTTP ${r.status}: protected page served without login`)
       : pass(`anonymous GET ${p}: refused (HTTP ${r.status}${r.headers.get('location') ? ' -> ' + r.headers.get('location') : ''})`);
  }
  // capture A's own response to every safe GET first (to recognise A's data even without a marker)
  for (const r of cfg.resources || []) {
    if ((r.method || 'GET').toUpperCase() === 'GET' && !r.stateChanging) {
      const o = await A.req('GET', r.path, { headers: r.headers });
      if (o.status >= 200 && o.status < 300) ownerBodies.set(r.path, o.text);
    }
  }
  // attacks first (so a destructive baseline cannot hide them), then the owner baseline
  for (const r of cfg.resources || []) {
    await attempt('anonymous', anon, r);
    await attempt('B', B, r);
  }
  for (const r of cfg.resources || []) {
    if (r.baseline === false) continue;
    const res = await A.req(r.method || 'GET', r.path, { json: r.json, form: r.form, headers: r.headers });
    const ok = res.status >= 200 && res.status < 300 && (!r.ownerMarker || markerVariants(r.ownerMarker).some(v => res.text.includes(v)));
    ok ? pass(`baseline A -> ${r.method || 'GET'} ${r.path}: HTTP ${res.status} (owner can do it, so the refusals above are meaningful)`)
       : fail(`baseline A -> ${r.method || 'GET'} ${r.path}: HTTP ${res.status}: the OWNER cannot do it, so this probe proves nothing. Fix the config`);
    if (ok) {
      checkHeaders(r.path, res.headers, /json/i.test(res.headers.get('content-type') || '') ? 'api' : 'page');
      const cc = (res.headers.get('cache-control') || '').toLowerCase();
      if (r.ownerMarker && !/no-store|private/.test(cc)) warn(`${r.path}: owner data without Cache-Control: no-store/private`);
    }
    // CSRF enforcement: same call, real owner session, but no token. Must be refused (cookie-based auth only).
    const changing = r.stateChanging || !['GET', 'HEAD'].includes((r.method || 'GET').toUpperCase());
    if (changing && A.jar.size && r.csrfCheck !== false) {
      const nr = await A.req(r.method, r.path, { json: r.json, form: r.form, headers: { Origin: 'https://evil.example' }, csrf: false });
      nr.status >= 200 && nr.status < 300
        ? fail(`CSRF: ${r.method} ${r.path} succeeded WITHOUT a CSRF token from a foreign Origin (HTTP ${nr.status})`)
        : pass(`CSRF: ${r.method} ${r.path} without token refused (HTTP ${nr.status})`);
    }
  }
}

console.log('\n=== AUTHZ PROBE SUMMARY ===');
for (const [s, m] of results) console.log(`${s.padEnd(5)} ${m}`);
const nFail = results.filter(r => r[0] === 'FAIL').length, nWarn = results.filter(r => r[0] === 'WARN').length;
console.log(`\n${nFail} FAIL, ${nWarn} WARN  (${log.length} requests sent)`);
console.log('NEXT: this covers only the resources you listed. List EVERY route that takes an id (read, update, delete,');
console.log('export, file download) and every role pair (driver vs driver, store vs store, driver vs admin screens).');
if (reportPath) fs.writeFileSync(reportPath, JSON.stringify({ base: BASE, results, requests: log }, null, 2));
process.exit(nFail ? 1 : 0);
