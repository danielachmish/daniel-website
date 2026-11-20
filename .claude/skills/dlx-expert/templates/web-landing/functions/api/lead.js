// Cloudflare Pages Function: מקבל את הטופס בכתובת /api/lead, בודק אותו בשרת, ומעביר הלאה.
// הגדרות (Settings > Environment variables בפרויקט ב-Cloudflare). שום סוד לא נכתב בקוד:
//   LEAD_WEBHOOK_URL  כתובת קבועה שמקבלת את הליד (Make / Zapier / Google Apps Script / CRM). חובה אחת מהשתיים.
//   RESEND_API_KEY + LEAD_TO_EMAIL + LEAD_FROM_EMAIL  שליחת מייל דרך Resend (הדומיין חייב להיות מאומת שם).
//   ALLOWED_ORIGIN    (רשות) למשל https://example.co.il. בקשה ממקור אחר נדחית.
const MAX = { name: 80, business: 120, biz_id: 12, phone: 20, city: 60, email: 120, type: 60 };
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json; charset=utf-8' } });
const clean = (v, n) => String(v ?? '').replace(/[\u0000-\u001F\u007F<>]/g, ' ').trim().slice(0, n);

export async function onRequestPost({ request, env }) {
  const origin = request.headers.get('Origin') || '';
  const allowed = env.ALLOWED_ORIGIN || new URL(request.url).origin;
  if (origin && origin !== allowed) return json(403, { ok: false, error: 'origin' });

  let data;
  try {
    const type = request.headers.get('Content-Type') || '';
    data = type.includes('application/json') ? await request.json() : Object.fromEntries(await request.formData());
  } catch { return json(400, { ok: false, error: 'bad_body' }); }

  // מלכודות בוטים: שדה נסתר מולא, או שליחה מהירה מ-3 שניות. עונים "הצלחה" ולא שומרים.
  const started = Number(data._started || 0);
  if (data.company_website || (started && Date.now() - started < 3000)) return json(200, { ok: true });

  const lead = {};
  for (const k of Object.keys(MAX)) lead[k] = clean(data[k], MAX[k]);
  lead.phone = lead.phone.replace(/\D+/g, '').replace(/^972/, '0');
  lead.marketing_consent = data.marketing_consent === 'yes';
  for (const k of ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'gclid', 'fbclid']) lead[k] = clean(data[k], 120);
  lead.received_at = new Date().toISOString();

  // בדיקה בשרת (לא סומכים על הדפדפן). מתאימים לשדות של הטופס בפועל.
  const errors = [];
  if (lead.name.length < 2) errors.push('name');
  if (!/^0(5\d|7\d|[2-489])\d{7}$/.test(lead.phone)) errors.push('phone');
  if (lead.email && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(lead.email)) errors.push('email');
  if ('biz_id' in data && !/^\d{8,9}$/.test(lead.biz_id.replace(/\D+/g, ''))) errors.push('biz_id');
  if (errors.length) return json(422, { ok: false, errors });

  const jobs = [];
  if (env.LEAD_WEBHOOK_URL) {
    jobs.push(fetch(env.LEAD_WEBHOOK_URL, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(lead) }));
  }
  if (env.RESEND_API_KEY && env.LEAD_TO_EMAIL && env.LEAD_FROM_EMAIL) {
    const rows = Object.entries(lead).filter(([, v]) => v !== '' && v !== false).map(([k, v]) => `${k}: ${v}`).join('\n');
    jobs.push(fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: env.LEAD_FROM_EMAIL, to: [env.LEAD_TO_EMAIL], subject: `ליד חדש: ${lead.business || lead.name}`, text: rows }),
    }));
  }
  if (!jobs.length) return json(500, { ok: false, error: 'not_configured' });

  const results = await Promise.allSettled(jobs);
  const delivered = results.some(r => r.status === 'fulfilled' && r.value.ok);
  return delivered ? json(200, { ok: true }) : json(502, { ok: false, error: 'delivery_failed' });
}

export const onRequest = () => json(405, { ok: false, error: 'method' });
