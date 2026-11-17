/**
 * shop/js/shop.js — לוגיקת החנות (Vanilla JS, ללא ספריות)
 * קטלוג + סינון, חלון מוצר, סל קניות (נשמר בדפדפן), וטופס הזמנה שנשלח בוואטסאפ.
 */
(function () {
  "use strict";

  const CFG = window.SHOP_CONFIG || {};
  const PRODUCTS = window.PRODUCTS || [];
  const CATEGORIES = window.CATEGORIES || [];
  const CUR = CFG.CURRENCY || "₪";
  const CART_KEY = "dlx-shop-cart-v1";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const money = (n) => CUR + Number(n).toLocaleString("he-IL");
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const byId = (id) => PRODUCTS.find((p) => p.id === id);
  const catName = (id) => (CATEGORIES.find((c) => c.id === id) || {}).name || "";
  const waUrl = (text) => "https://wa.me/" + CFG.WHATSAPP_NUMBER + (text ? "?text=" + encodeURIComponent(text) : "");

  /* ---------------------------------------------------------------------
   * איורי מוצרים (כשאין תמונה אמיתית)
   * ------------------------------------------------------------------- */
  function illo(kind, tint) {
    const t = tint || "#2563eb";
    const light = isLight(t);
    const line = light ? "#475569" : "#ffffff";
    const shapes = {
      chargers: `<rect x="34" y="30" width="52" height="56" rx="12" fill="${t}"/><rect x="48" y="86" width="6" height="16" rx="2" fill="#94a3b8"/><rect x="66" y="86" width="6" height="16" rx="2" fill="#94a3b8"/><rect x="50" y="44" width="20" height="8" rx="4" fill="${line}" opacity=".85"/><path d="M62 58l-6 10h8l-6 10" fill="none" stroke="${line}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" opacity=".8"/>`,
      cables: `<path d="M30 40 C 30 100, 90 20, 90 80" fill="none" stroke="${t}" stroke-width="7" stroke-linecap="round"/><rect x="22" y="22" width="16" height="22" rx="4" fill="#cbd5e1"/><rect x="26" y="14" width="8" height="10" rx="2" fill="#94a3b8"/><rect x="82" y="78" width="16" height="22" rx="4" fill="#cbd5e1"/><rect x="86" y="98" width="8" height="10" rx="2" fill="#94a3b8"/>`,
      cases: `<rect x="36" y="14" width="48" height="92" rx="12" fill="${t}"/><rect x="42" y="20" width="22" height="22" rx="7" fill="${line}" opacity=".25"/><circle cx="49" cy="27" r="4" fill="#0f172a" opacity=".7"/><circle cx="57" cy="35" r="4" fill="#0f172a" opacity=".7"/><circle cx="60" cy="68" r="12" fill="none" stroke="${line}" stroke-width="2" opacity=".35"/>`,
      screen: `<rect x="36" y="14" width="48" height="92" rx="12" fill="#0f172a"/><rect x="40" y="18" width="40" height="84" rx="9" fill="${t}" opacity=".9"/><path d="M44 60 L70 22 L80 22 L50 72 Z" fill="#fff" opacity=".35"/><path d="M52 92 L80 50 L80 60 L58 94 Z" fill="#fff" opacity=".2"/>`,
      audio: `<path d="M38 40c0-10 18-10 18 0v28c0 6-4 10-9 10s-9-4-9-10z" fill="${t}" stroke="#94a3b8" stroke-width="2"/><rect x="42" y="74" width="10" height="28" rx="5" fill="${t}" stroke="#94a3b8" stroke-width="2"/><path d="M64 40c0-10 18-10 18 0v28c0 6-4 10-9 10s-9-4-9-10z" fill="${t}" stroke="#94a3b8" stroke-width="2"/><rect x="68" y="74" width="10" height="28" rx="5" fill="${t}" stroke="#94a3b8" stroke-width="2"/>`,
      power: `<rect x="32" y="22" width="56" height="80" rx="12" fill="${t}"/><rect x="44" y="40" width="32" height="36" rx="4" fill="none" stroke="${line}" stroke-width="2.5" opacity=".7"/><rect x="48" y="62" width="24" height="10" rx="2" fill="#22c55e"/><rect x="48" y="50" width="24" height="10" rx="2" fill="#22c55e" opacity=".7"/><rect x="52" y="84" width="16" height="5" rx="2.5" fill="${line}" opacity=".6"/>`,
      holders: `<rect x="56" y="70" width="8" height="30" rx="3" fill="#94a3b8"/><rect x="40" y="98" width="40" height="8" rx="4" fill="#64748b"/><rect x="38" y="20" width="44" height="54" rx="10" fill="${t}"/><circle cx="60" cy="47" r="12" fill="${line}" opacity=".3"/>`
    };
    return `<svg viewBox="0 0 120 120" role="img" aria-hidden="true"><defs><radialGradient id="g-${kind}-${t.slice(1)}" cx="50%" cy="40%" r="65%"><stop offset="0%" stop-color="${t}" stop-opacity=".18"/><stop offset="100%" stop-color="${t}" stop-opacity="0"/></radialGradient></defs><circle cx="60" cy="60" r="56" fill="url(#g-${kind}-${t.slice(1)})"/>${shapes[kind] || shapes.chargers}</svg>`;
  }
  function isLight(hex) {
    const h = hex.replace("#", "");
    const r = parseInt(h.substr(0, 2), 16), g = parseInt(h.substr(2, 2), 16), b = parseInt(h.substr(4, 2), 16);
    return (r * 299 + g * 587 + b * 114) / 1000 > 180;
  }
  function media(p) {
    if (p.image) return `<img src="${esc(p.image)}" alt="${esc(p.name)}" loading="lazy">`;
    return illo(p.category, p.tint);
  }

  /* ---------------------------------------------------------------------
   * הגדרות כלליות מה-config
   * ------------------------------------------------------------------- */
  function applyConfig() {
    $$("[data-store-name]").forEach((el) => (el.textContent = CFG.STORE_NAME || el.textContent));
    $$("[data-tagline]").forEach((el) => (el.textContent = CFG.TAGLINE || el.textContent));
    $$("[data-wa-link]").forEach((el) => {
      el.href = waUrl("היי, הגעתי מהאתר ויש לי שאלה 🙂");
      el.target = "_blank";
      el.rel = "noopener";
    });
    const phone = $("#phoneLink");
    if (CFG.PHONE_DISPLAY) { phone.href = "tel:" + CFG.PHONE_DISPLAY.replace(/\D/g, ""); phone.textContent = "📞 " + CFG.PHONE_DISPLAY; }
    else phone.hidden = true;
    const free = Number(CFG.FREE_SHIPPING_FROM) || 0;
    $("#topbarShipping").textContent = free ? `משלוח חינם בהזמנה מעל ${money(free)}` : `משלוח עד הבית ב-${money(CFG.SHIPPING_COST)}`;
    $("#trustDelivery").textContent = CFG.DELIVERY_DAYS || "";
    $("#faqDelivery").textContent = `משלוח עד הבית לוקח בדרך כלל ${CFG.DELIVERY_DAYS}. ` + (free ? `משלוח חינם בהזמנה מעל ${money(free)}.` : `עלות משלוח ${money(CFG.SHIPPING_COST)}.`);
    if (!CFG.PICKUP_ENABLED) $("#pickupOption").hidden = true;
    $("#year").textContent = new Date().getFullYear();
    document.title = (CFG.STORE_NAME || "DLX MOBILE") + " — אביזרי סלולר עד הבית";

    // הדמיית Hero
    const picks = ["cases", "chargers", "audio", "power"].map((c) => PRODUCTS.find((p) => p.category === c)).filter(Boolean);
    $("#heroVisual").innerHTML = picks.map((p, i) => `<div class="hero__tile hero__tile--${i}">${media(p)}</div>`).join("");
  }

  /* ---------------------------------------------------------------------
   * קטלוג + סינון
   * ------------------------------------------------------------------- */
  const state = { cat: "all", compat: "all", q: "", sort: "featured" };

  function renderCategories() {
    $("#catGrid").innerHTML = CATEGORIES.map((c) => {
      const tint = (PRODUCTS.find((p) => p.category === c.id) || {}).tint;
      const count = PRODUCTS.filter((p) => p.category === c.id).length;
      return `<button class="cat" data-cat="${c.id}"><span class="cat__img">${illo(c.icon, tint)}</span><span class="cat__name">${esc(c.name)}</span><span class="cat__count">${count} מוצרים</span></button>`;
    }).join("");
    $("#catPills").innerHTML = `<button class="pill is-active" data-cat="all">הכול</button>` +
      CATEGORIES.map((c) => `<button class="pill" data-cat="${c.id}">${esc(c.name)}</button>`).join("");

    $("#catGrid").addEventListener("click", (e) => {
      const b = e.target.closest("[data-cat]"); if (!b) return;
      setCat(b.dataset.cat);
      $("#products").scrollIntoView({ behavior: "smooth" });
    });
    $("#catPills").addEventListener("click", (e) => {
      const b = e.target.closest("[data-cat]"); if (b) setCat(b.dataset.cat);
    });
  }
  function setCat(cat) {
    state.cat = cat;
    $$("#catPills .pill").forEach((p) => p.classList.toggle("is-active", p.dataset.cat === cat));
    $("#productsTitle").textContent = cat === "all" ? "כל המוצרים" : catName(cat);
    renderProducts();
  }

  function filtered() {
    const q = state.q.trim().toLowerCase();
    let list = PRODUCTS.filter((p) =>
      (state.cat === "all" || p.category === state.cat) &&
      (state.compat === "all" || p.compat.includes(state.compat) || p.compat.includes("Universal")) &&
      (!q || [p.name, p.description, catName(p.category), (p.colors || []).join(" "), p.compat.join(" ")].join(" ").toLowerCase().includes(q))
    );
    const s = state.sort;
    if (s === "price-asc") list = list.slice().sort((a, b) => a.price - b.price);
    if (s === "price-desc") list = list.slice().sort((a, b) => b.price - a.price);
    if (s === "sale") list = list.slice().sort((a, b) => (b.oldPrice ? 1 : 0) - (a.oldPrice ? 1 : 0));
    // מוצרים שאזלו תמיד בסוף
    return list.slice().sort((a, b) => (a.inStock === false) - (b.inStock === false));
  }

  function card(p) {
    const off = p.oldPrice ? Math.round((1 - p.price / p.oldPrice) * 100) : 0;
    const out = p.inStock === false;
    const compat = p.compat.includes("Universal") ? "מתאים לכל המכשירים" : "מתאים ל" + p.compat.map((c) => (c === "iPhone" ? "אייפון" : "סמסונג")).join(" ו");
    return `<article class="card${out ? " is-out" : ""}">
      <button class="card__media" data-open="${p.id}" aria-label="פרטים על ${esc(p.name)}">
        ${media(p)}
        ${p.badge ? `<span class="badge badge--${p.badge === "מבצע" ? "sale" : p.badge === "חדש" ? "new" : "hot"}">${esc(p.badge)}${off ? " -" + off + "%" : ""}</span>` : ""}
        ${out ? `<span class="badge badge--out">אזל מהמלאי</span>` : ""}
      </button>
      <div class="card__body">
        <span class="card__cat">${esc(catName(p.category))}</span>
        <h3 class="card__title"><button data-open="${p.id}">${esc(p.name)}</button></h3>
        <span class="card__compat">${compat}</span>
        <div class="card__foot">
          <div class="price"><span class="price__now">${money(p.price)}</span>${p.oldPrice ? `<s class="price__old">${money(p.oldPrice)}</s>` : ""}</div>
          ${out
            ? `<button class="btn btn--sm btn--ghost" disabled>אזל</button>`
            : p.colors ? `<button class="btn btn--sm btn--primary" data-open="${p.id}">בחירה</button>`
            : `<button class="btn btn--sm btn--primary" data-add="${p.id}">הוספה לסל</button>`}
        </div>
      </div>
    </article>`;
  }

  function renderProducts() {
    const list = filtered();
    $("#productGrid").innerHTML = list.map(card).join("");
    $("#emptyState").hidden = list.length > 0;
    $("#productsCount").textContent = list.length + " מוצרים";
  }

  function bindToolbar() {
    let t;
    $("#searchInput").addEventListener("input", (e) => {
      clearTimeout(t);
      t = setTimeout(() => { state.q = e.target.value; renderProducts(); }, 150);
    });
    $("#compatChips").addEventListener("click", (e) => {
      const b = e.target.closest("[data-compat]"); if (!b) return;
      state.compat = b.dataset.compat;
      $$("#compatChips .chip").forEach((c) => c.classList.toggle("is-active", c === b));
      renderProducts();
    });
    $("#sortSelect").addEventListener("change", (e) => { state.sort = e.target.value; renderProducts(); });

    $("#productGrid").addEventListener("click", (e) => {
      const o = e.target.closest("[data-open]");
      if (o) return openProduct(o.dataset.open);
      const a = e.target.closest("[data-add]");
      if (a) { addToCart(a.dataset.add, null, 1); }
    });
  }

  /* ---------------------------------------------------------------------
   * חלון מוצר
   * ------------------------------------------------------------------- */
  function openProduct(id) {
    const p = byId(id); if (!p) return;
    const out = p.inStock === false;
    const isModel = p.category === "cases" || p.category === "screen";
    $("#productModalBody").innerHTML = `
      <div class="pm__media">${media(p)}</div>
      <div class="pm__info">
        <span class="card__cat">${esc(catName(p.category))}</span>
        <h2 id="pmTitle">${esc(p.name)}</h2>
        <div class="price price--lg"><span class="price__now">${money(p.price)}</span>${p.oldPrice ? `<s class="price__old">${money(p.oldPrice)}</s><span class="save">חוסכים ${money(p.oldPrice - p.price)}</span>` : ""}</div>
        <p>${esc(p.description)}</p>
        <ul class="pm__features">${(p.features || []).map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
        ${p.colors ? `<fieldset class="variants"><legend>${isModel ? "בחירת דגם" : "בחירת צבע"}</legend>${p.colors.map((c, i) => `<label><input type="radio" name="variant" value="${esc(c)}"${i === 0 ? " checked" : ""}><span>${esc(c)}</span></label>`).join("")}</fieldset>` : ""}
        <div class="pm__buy">
          <div class="qty" aria-label="כמות">
            <button type="button" data-q="1" aria-label="הוספת יחידה">+</button>
            <output id="pmQty">1</output>
            <button type="button" data-q="-1" aria-label="הפחתת יחידה">−</button>
          </div>
          <button class="btn btn--primary btn--lg" id="pmAdd" ${out ? "disabled" : ""}>${out ? "אזל מהמלאי" : "הוספה לסל"}</button>
        </div>
        ${out ? `<a class="link" target="_blank" rel="noopener" href="${waUrl("היי, אשמח לדעת מתי יחזור למלאי: " + p.name)}">עדכנו אותי כשיחזור למלאי</a>` : ""}
        <p class="muted small">🚚 משלוח ${CFG.DELIVERY_DAYS} · ↩️ החזרה עד 14 יום</p>
      </div>`;
    let qty = 1;
    const body = $("#productModalBody");
    body.querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => {
      qty = Math.max(1, Math.min(20, qty + Number(b.dataset.q)));
      $("#pmQty").textContent = qty;
    }));
    $("#pmAdd").addEventListener("click", () => {
      const v = body.querySelector("input[name=variant]:checked");
      addToCart(p.id, v ? v.value : null, qty);
      $("#productModal").close();
    });
    openDialog($("#productModal"));
  }

  /* ---------------------------------------------------------------------
   * סל קניות
   * ------------------------------------------------------------------- */
  let cart = loadCart();
  function loadCart() {
    try {
      const raw = JSON.parse(localStorage.getItem(CART_KEY) || "[]");
      return Array.isArray(raw) ? raw.filter((l) => byId(l.id) && l.qty > 0) : [];
    } catch (_) { return []; }
  }
  function saveCart() { try { localStorage.setItem(CART_KEY, JSON.stringify(cart)); } catch (_) {} }
  const lineKey = (id, v) => id + "|" + (v || "");

  function addToCart(id, variant, qty) {
    const p = byId(id); if (!p || p.inStock === false) return;
    const key = lineKey(id, variant);
    const line = cart.find((l) => lineKey(l.id, l.variant) === key);
    if (line) line.qty = Math.min(20, line.qty + qty);
    else cart.push({ id, variant: variant || null, qty });
    saveCart(); renderCart();
    toast(`✓ ${p.name} נוסף לסל`, true);
    bump();
  }
  function setQty(key, qty) {
    const line = cart.find((l) => lineKey(l.id, l.variant) === key); if (!line) return;
    if (qty <= 0) cart = cart.filter((l) => l !== line);
    else line.qty = Math.min(20, qty);
    saveCart(); renderCart();
  }
  function totals() {
    const subtotal = cart.reduce((s, l) => s + byId(l.id).price * l.qty, 0);
    const count = cart.reduce((s, l) => s + l.qty, 0);
    const free = Number(CFG.FREE_SHIPPING_FROM) || 0;
    const pickup = ($("input[name=delivery]:checked") || {}).value === "pickup";
    const shipping = !count || pickup || (free && subtotal >= free) ? 0 : Number(CFG.SHIPPING_COST) || 0;
    return { subtotal, count, shipping, total: subtotal + shipping, free, pickup };
  }

  function renderCart() {
    const t = totals();
    $("#cartCount").textContent = t.count;
    $("#cartCount").classList.toggle("is-zero", t.count === 0);

    // פס התקדמות למשלוח חינם
    const sp = $("#shipProgress");
    if (t.free && t.count) {
      const pct = Math.min(100, (t.subtotal / t.free) * 100);
      sp.innerHTML = `<p>${t.subtotal >= t.free ? "🎉 מגיע לך משלוח חינם!" : `עוד <strong>${money(t.free - t.subtotal)}</strong> למשלוח חינם`}</p><div class="bar"><span style="width:${pct}%"></span></div>`;
      sp.hidden = false;
    } else sp.hidden = true;

    if (!cart.length) {
      $("#cartItems").innerHTML = `<div class="cart-empty"><p>הסל ריק כרגע</p><button class="btn btn--primary" data-close data-goto="#products">למוצרים</button></div>`;
      $("#cartFoot").innerHTML = "";
      return;
    }
    $("#cartItems").innerHTML = cart.map((l) => {
      const p = byId(l.id), key = lineKey(l.id, l.variant);
      return `<div class="line">
        <div class="line__img">${media(p)}</div>
        <div class="line__info">
          <strong>${esc(p.name)}</strong>
          ${l.variant ? `<span class="muted small">${esc(l.variant)}</span>` : ""}
          <div class="line__row">
            <div class="qty qty--sm">
              <button data-line="${esc(key)}" data-d="1" aria-label="הוספת יחידה">+</button>
              <output>${l.qty}</output>
              <button data-line="${esc(key)}" data-d="-1" aria-label="הפחתת יחידה">−</button>
            </div>
            <span class="line__price">${money(p.price * l.qty)}</span>
          </div>
        </div>
        <button class="line__rm" data-line="${esc(key)}" data-rm aria-label="הסרת ${esc(p.name)}">✕</button>
      </div>`;
    }).join("");
    $("#cartFoot").innerHTML = `
      <div class="sum-row"><span>סכום ביניים</span><span>${money(t.subtotal)}</span></div>
      <div class="sum-row muted"><span>משלוח</span><span>${t.shipping ? money(t.shipping) : "חינם"}</span></div>
      <div class="sum-row sum-row--total"><span>סה״כ</span><span>${money(t.total)}</span></div>
      <button class="btn btn--primary btn--lg btn--block" id="toCheckout">להזמנה ←</button>`;
  }

  function bindCart() {
    $("#cartOpen").addEventListener("click", () => { renderCart(); openDialog($("#cartDrawer")); });
    $("#cartDrawer").addEventListener("click", (e) => {
      const b = e.target.closest("[data-line]");
      if (b) {
        const line = cart.find((l) => lineKey(l.id, l.variant) === b.dataset.line);
        if (line) setQty(b.dataset.line, b.hasAttribute("data-rm") ? 0 : line.qty + Number(b.dataset.d));
        return;
      }
      if (e.target.closest("#toCheckout")) { $("#cartDrawer").close(); openCheckout(); }
      const g = e.target.closest("[data-goto]");
      if (g) setTimeout(() => $(g.dataset.goto).scrollIntoView({ behavior: "smooth" }), 50);
    });
  }
  function bump() {
    const b = $("#cartOpen");
    b.classList.remove("bump"); void b.offsetWidth; b.classList.add("bump");
  }

  /* ---------------------------------------------------------------------
   * הזמנה (Checkout)
   * ------------------------------------------------------------------- */
  function openCheckout() {
    $("#checkoutForm").hidden = false;
    $("#checkoutDone").hidden = true;
    syncDelivery();
    openDialog($("#checkoutModal"));
  }
  function syncDelivery() {
    const pickup = ($("input[name=delivery]:checked") || {}).value === "pickup";
    $("#shipFields").hidden = pickup;
    const t = totals();
    $("#coSummary").innerHTML =
      `<div class="sum-row"><span>${t.count} פריטים</span><span>${money(t.subtotal)}</span></div>` +
      `<div class="sum-row muted"><span>${pickup ? "איסוף עצמי (" + esc(CFG.PICKUP_AREA || "") + ")" : "משלוח"}</span><span>${t.shipping ? money(t.shipping) : "חינם"}</span></div>` +
      `<div class="sum-row sum-row--total"><span>לתשלום</span><span>${money(t.total)}</span></div>`;
  }

  function buildMessage(data, t) {
    const lines = cart.map((l) => {
      const p = byId(l.id);
      return `• ${p.name}${l.variant ? " (" + l.variant + ")" : ""} × ${l.qty} — ${money(p.price * l.qty)}`;
    });
    return [
      `🛒 *הזמנה חדשה מהאתר — ${CFG.STORE_NAME}*`,
      "",
      ...lines,
      "",
      `סכום ביניים: ${money(t.subtotal)}`,
      `משלוח: ${t.shipping ? money(t.shipping) : "חינם"}`,
      `*סה״כ לתשלום: ${money(t.total)}*`,
      "",
      `👤 ${data.name}`,
      `📞 ${data.phone}`,
      t.pickup ? "📦 איסוף עצמי" : `📦 משלוח ל: ${data.address}, ${data.city}`,
      `💳 תשלום מועדף: ${data.payment}`,
      data.notes ? `📝 ${data.notes}` : ""
    ].filter((x, i, arr) => !(x === "" && arr[i - 1] === "")).join("\n").trim();
  }

  function validate(form) {
    const pickup = form.delivery.value === "pickup";
    const rules = {
      name: (v) => v.trim().length >= 2 || "נא למלא שם מלא",
      phone: (v) => /^0\d{8,9}$/.test(v.replace(/[\s-]/g, "")) || "נא למלא מספר טלפון תקין",
      city: (v) => pickup || v.trim().length >= 2 || "נא למלא עיר",
      address: (v) => pickup || v.trim().length >= 3 || "נא למלא כתובת"
    };
    let ok = true, first = null;
    Object.entries(rules).forEach(([name, rule]) => {
      const el = form[name], res = rule(el.value), err = el.parentElement.querySelector(".field__err");
      const bad = res !== true;
      el.setAttribute("aria-invalid", bad);
      err.textContent = bad ? res : "";
      if (bad) { ok = false; first = first || el; }
    });
    const tErr = $("#termsErr");
    tErr.textContent = form.terms.checked ? "" : "יש לאשר את התקנון";
    if (!form.terms.checked) { ok = false; first = first || form.terms; }
    if (first) first.focus();
    return ok;
  }

  function bindCheckout() {
    const form = $("#checkoutForm");
    $$("input[name=delivery]").forEach((r) => r.addEventListener("change", () => { syncDelivery(); renderCart(); }));
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (form._gotcha.value) return; // בוט
      if (!cart.length) { toast("הסל ריק"); return; }
      if (!validate(form)) return;
      const data = Object.fromEntries(new FormData(form).entries());
      const t = totals();
      const msg = buildMessage(data, t);
      const url = waUrl(msg);

      // עותק במייל (אופציונלי)
      if (CFG.ORDER_ENDPOINT) {
        fetch(CFG.ORDER_ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ _subject: "הזמנה חדשה — " + data.name, order: msg, ...data, total: t.total })
        }).catch(() => {});
      }

      window.open(url, "_blank", "noopener");
      $("#waRetry").href = url;
      form.hidden = true;
      $("#checkoutDone").hidden = false;
      cart = []; saveCart(); renderCart();
      form.reset();
    });
  }

  /* ---------------------------------------------------------------------
   * עזרים: dialogs, toast
   * ------------------------------------------------------------------- */
  function openDialog(d) {
    if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", "");
    document.body.classList.add("no-scroll");
  }
  function bindDialogs() {
    $$("dialog").forEach((d) => {
      d.addEventListener("click", (e) => {
        if (e.target === d || e.target.closest("[data-close]")) d.close();
      });
      d.addEventListener("close", () => {
        if (!$$("dialog").some((x) => x.open)) document.body.classList.remove("no-scroll");
      });
    });
  }
  let toastT;
  function toast(text, withCart) {
    const el = $("#toast");
    el.innerHTML = esc(text) + (withCart ? ` <button class="toast__btn" type="button">לסל</button>` : "");
    el.classList.add("is-on");
    const btn = el.querySelector(".toast__btn");
    if (btn) btn.onclick = () => { el.classList.remove("is-on"); renderCart(); openDialog($("#cartDrawer")); };
    clearTimeout(toastT);
    toastT = setTimeout(() => el.classList.remove("is-on"), 3200);
  }

  /* ---------------------------------------------------------------------
   * הפעלה
   * ------------------------------------------------------------------- */
  applyConfig();
  renderCategories();
  bindToolbar();
  renderProducts();
  bindCart();
  bindCheckout();
  bindDialogs();
  renderCart();
})();
