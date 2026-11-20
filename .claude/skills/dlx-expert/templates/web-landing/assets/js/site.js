/* site.js — בלי ספריות. כל מה שכאן הוא שיפור: הדף עובד וקריא גם בלי JS. */
(function () {
  'use strict';
  var doc = document.documentElement;
  doc.classList.add('js');
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- כניסה מדורגת של אלמנטים ---------- */
  var reveals = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && !reduce) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target); }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    reveals.forEach(function (el) { io.observe(el); });
  } else {
    reveals.forEach(function (el) { el.classList.add('is-in'); });
  }

  /* ---------- כפתור דביק בטלפון: מופיע אחרי ה-Hero, נעלם ליד הטופס ---------- */
  var sticky = document.querySelector('.sticky-cta');
  var heroCta = document.querySelector('[data-hero-cta]');
  var formSection = document.getElementById('signup');
  if (sticky && heroCta && formSection && 'IntersectionObserver' in window) {
    var heroVisible = true, formVisible = false;
    var update = function () {
      var show = !heroVisible && !formVisible;
      sticky.classList.toggle('is-visible', show);
      sticky.setAttribute('aria-hidden', show ? 'false' : 'true');
      sticky.querySelectorAll('a,button').forEach(function (b) { b.tabIndex = show ? 0 : -1; });
    };
    new IntersectionObserver(function (es) { heroVisible = es[0].isIntersecting; update(); }).observe(heroCta);
    new IntersectionObserver(function (es) { formVisible = es[0].isIntersecting; update(); }, { rootMargin: '0px 0px -20% 0px' }).observe(formSection);
    update();
  }

  /* ---------- שנה בפוטר ---------- */
  document.querySelectorAll('[data-year]').forEach(function (el) { el.textContent = new Date().getFullYear(); });

  /* ---------- טופס לידים ---------- */
  var form = document.querySelector('form[data-lead-form]');
  if (!form) return;

  // מקור ההגעה (UTM) נשמר בשדות נסתרים, כדי לדעת איזה קמפיין הביא את הליד
  try {
    var params = new URLSearchParams(location.search);
    ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'gclid', 'fbclid'].forEach(function (k) {
      var f = form.querySelector('input[name="' + k + '"]');
      if (f && params.get(k)) f.value = params.get(k).slice(0, 120);
    });
  } catch (e) { /* אין תמיכה: לא קריטי */ }
  var started = form.querySelector('input[name="_started"]');
  if (started) started.value = String(Date.now());

  var digits = function (s) { return (s || '').replace(/\D+/g, ''); };
  var rules = {
    required: function (v, el) { return el.type === 'checkbox' ? el.checked : v.trim().length > 0; },
    name: function (v) { return v.trim().length >= 2; },
    phoneIL: function (v) { var d = digits(v).replace(/^972/, '0'); return /^0(5\d|7\d|[2-489])\d{7}$/.test(d); },
    email: function (v) { return v === '' || /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v.trim()); },
    bizId: function (v) { var d = digits(v); return d.length >= 8 && d.length <= 9; }
  };

  // כל שדה עם data-validate מצביע (aria-describedby) על אלמנט שגיאה שה-id שלו נגמר ב-"-err"
  var errorOf = function (el) {
    var ids = (el.getAttribute('aria-describedby') || '').split(' ');
    for (var i = 0; i < ids.length; i++) if (/-err$/.test(ids[i])) return document.getElementById(ids[i]);
    return null;
  };

  function validate(el) {
    var v = el.type === 'checkbox' ? '' : el.value;
    var msg = '';
    if (el.required && !rules.required(v, el)) msg = el.dataset.msgRequired || 'שדה חובה';
    else if (v && el.dataset.rule && rules[el.dataset.rule] && !rules[el.dataset.rule](v)) msg = el.dataset.msgInvalid || 'הערך לא תקין';
    var err = errorOf(el);
    if (err) err.textContent = msg;
    el.setAttribute('aria-invalid', msg ? 'true' : 'false');
    return !msg;
  }

  var inputs = Array.prototype.slice.call(form.querySelectorAll('[data-validate]'));
  inputs.forEach(function (el) {
    el.addEventListener('blur', function () { if (el.value || el.dataset.touched) validate(el); el.dataset.touched = '1'; });
    el.addEventListener('input', function () { if (el.getAttribute('aria-invalid') === 'true') validate(el); });
    el.addEventListener('change', function () { if (el.type === 'checkbox' || el.tagName === 'SELECT') validate(el); });
  });

  var status = form.querySelector('.form-status');
  var btn = form.querySelector('button[type="submit"]');
  var btnLabel = btn ? btn.innerHTML : '';

  form.addEventListener('submit', function (ev) {
    ev.preventDefault();
    status.textContent = ''; status.className = 'form-status';
    var bad = inputs.filter(function (el) { return !validate(el); });
    if (bad.length) {
      status.classList.add('form-status--error');
      status.textContent = bad.length === 1 ? 'יש שדה אחד שצריך לתקן.' : 'יש ' + bad.length + ' שדות שצריך לתקן.';
      bad[0].focus();
      return;
    }
    var data = Object.fromEntries(new FormData(form).entries());
    // בוט מילא את שדה המלכודת: מציגים הצלחה ולא שולחים כלום
    if (data.company_website) { return success(); }
    if (data.phone) data.phone = digits(data.phone).replace(/^972/, '0');

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" aria-hidden="true"></span> שולחים…';

    // מצב הדגמה (data-demo="true"): בלי שרת. להסיר לפני עלייה לאוויר! qa_web.mjs מזהיר על זה.
    if (form.dataset.demo === 'true') { setTimeout(success, 700); return; }

    var ctrl = 'AbortController' in window ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 15000);
    fetch(form.action, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(data),
      signal: ctrl ? ctrl.signal : undefined
    }).then(function (r) {
      clearTimeout(timer);
      if (!r.ok) throw new Error('HTTP ' + r.status);
      success();
      if (window.dataLayer) window.dataLayer.push({ event: 'generate_lead', form: form.id });
    }).catch(function () {
      clearTimeout(timer);
      btn.disabled = false; btn.innerHTML = btnLabel;
      status.classList.add('form-status--error');
      status.textContent = form.dataset.msgFail || 'השליחה לא הצליחה. בדקו את החיבור ונסו שוב, או התקשרו אלינו.';
      status.focus();
    });
  });

  function success() {
    var tpl = document.getElementById('form-success');
    var card = form.closest('.form-card');
    if (tpl && card) {
      card.innerHTML = tpl.innerHTML;
      var h = card.querySelector('h3');
      if (h) { h.tabIndex = -1; h.focus(); }
    }
  }
})();
