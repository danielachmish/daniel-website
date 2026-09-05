(function () {
  "use strict";

  var cfg = window.SITE_CONFIG || {};

  /* ------------------------------------------------------------------ */
  /* Footer year                                                         */
  /* ------------------------------------------------------------------ */
  var yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = new Date().getFullYear();

  /* ------------------------------------------------------------------ */
  /* Contact details from config (email / phone / socials)               */
  /* ------------------------------------------------------------------ */
  function applyConfigText() {
    var emailEl = document.querySelector('[data-config="CONTACT_EMAIL"]');
    var phoneEl = document.querySelector('[data-config="CONTACT_PHONE"]');
    var emailPoint = emailEl ? emailEl.closest(".contact-point") : null;
    var phonePoint = phoneEl ? phoneEl.closest(".contact-point") : null;

    if (cfg.CONTACT_EMAIL) {
      emailEl.textContent = cfg.CONTACT_EMAIL;
    } else if (emailPoint) {
      emailPoint.style.display = "none";
    }

    if (cfg.CONTACT_PHONE) {
      phoneEl.textContent = cfg.CONTACT_PHONE;
    } else if (phonePoint) {
      phonePoint.style.display = "none";
    }

    var socialWrap = document.getElementById("footerSocial");
    if (socialWrap && cfg.SOCIAL_LINKS) {
      var icons = {
        linkedin: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM3 9h4v12H3zM9 9h3.8v1.7h.05c.53-1 1.83-2.05 3.77-2.05 4.03 0 4.78 2.65 4.78 6.1V21h-4v-5.6c0-1.34-.02-3.05-1.86-3.05-1.87 0-2.16 1.46-2.16 2.96V21H9z"/></svg>',
        github: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.46-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.9 1.53 2.34 1.09 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.56-1.11-4.56-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.4 9.4 0 0 1 5 0c1.91-1.3 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0 0 12 2z"/></svg>',
        whatsapp: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 0 0-8.6 15L2 22l5.16-1.35A10 10 0 1 0 12 2zm0 18a8 8 0 0 1-4.08-1.12l-.29-.17-3.05.8.81-2.97-.19-.3A8 8 0 1 1 12 20zm4.4-5.9c-.24-.12-1.43-.7-1.65-.79-.22-.08-.38-.12-.54.12-.16.24-.62.79-.76.95-.14.16-.28.18-.52.06-.24-.12-1.02-.38-1.94-1.2-.72-.64-1.2-1.43-1.34-1.67-.14-.24-.02-.37.1-.49.11-.11.24-.28.36-.42.12-.14.16-.24.24-.4.08-.16.04-.3-.02-.42-.06-.12-.54-1.3-.74-1.78-.19-.46-.39-.4-.54-.4h-.46c-.16 0-.42.06-.64.3-.22.24-.84.82-.84 2s.86 2.32.98 2.48c.12.16 1.7 2.6 4.12 3.64.58.25 1.03.4 1.38.51.58.18 1.11.16 1.53.1.47-.07 1.43-.58 1.63-1.15.2-.56.2-1.04.14-1.15-.06-.1-.22-.16-.46-.28z"/></svg>'
      };
      var labels = { linkedin: "LinkedIn", github: "GitHub", whatsapp: "WhatsApp" };
      Object.keys(cfg.SOCIAL_LINKS).forEach(function (key) {
        var url = cfg.SOCIAL_LINKS[key];
        if (url && icons[key]) {
          var a = document.createElement("a");
          a.href = url;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          a.setAttribute("aria-label", labels[key] || key);
          a.innerHTML = icons[key];
          socialWrap.appendChild(a);
        }
      });
    }
  }
  applyConfigText();

  /* ------------------------------------------------------------------ */
  /* Sticky header state on scroll                                       */
  /* ------------------------------------------------------------------ */
  var header = document.getElementById("siteHeader");
  function onScrollHeader() {
    if (window.scrollY > 12) header.classList.add("is-scrolled");
    else header.classList.remove("is-scrolled");
  }
  onScrollHeader();
  window.addEventListener("scroll", onScrollHeader, { passive: true });

  /* ------------------------------------------------------------------ */
  /* Mobile nav drawer                                                    */
  /* ------------------------------------------------------------------ */
  var navToggle = document.getElementById("navToggle");
  var navClose = document.getElementById("navClose");
  var mobileNav = document.getElementById("mobileNav");

  function openMobileNav() {
    mobileNav.classList.add("is-open");
    navToggle.setAttribute("aria-expanded", "true");
    document.body.style.overflow = "hidden";
    var firstLink = mobileNav.querySelector("a");
    if (firstLink) firstLink.focus();
  }
  function closeMobileNav() {
    mobileNav.classList.remove("is-open");
    navToggle.setAttribute("aria-expanded", "false");
    document.body.style.overflow = "";
    navToggle.focus();
  }
  navToggle.addEventListener("click", openMobileNav);
  navClose.addEventListener("click", closeMobileNav);
  mobileNav.addEventListener("click", function (e) {
    if (e.target === mobileNav) closeMobileNav();
  });
  mobileNav.querySelectorAll("a").forEach(function (a) {
    a.addEventListener("click", closeMobileNav);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && mobileNav.classList.contains("is-open")) closeMobileNav();
  });

  /* ------------------------------------------------------------------ */
  /* Scrollspy: highlight active nav link                                 */
  /* ------------------------------------------------------------------ */
  var sections = ["hero", "what-i-do", "projects", "about", "process", "contact"]
    .map(function (id) { return document.getElementById(id); })
    .filter(Boolean);
  var navLinks = document.querySelectorAll('[data-nav]');

  function setActiveLink(id) {
    navLinks.forEach(function (link) {
      var match = link.getAttribute("href") === "#" + id;
      link.classList.toggle("active", match);
      if (match) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  }

  var spyObserver = new IntersectionObserver(
    function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) setActiveLink(entry.target.id);
      });
    },
    { rootMargin: "-45% 0px -50% 0px", threshold: 0 }
  );
  sections.forEach(function (s) { spyObserver.observe(s); });

  /* ------------------------------------------------------------------ */
  /* Reveal-on-scroll animation                                          */
  /* ------------------------------------------------------------------ */
  var revealEls = document.querySelectorAll(".reveal");
  var revealObserver;
  if ("IntersectionObserver" in window) {
    revealObserver = new IntersectionObserver(
      function (entries, obs) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            obs.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    revealEls.forEach(function (el) { revealObserver.observe(el); });
  } else {
    // Fallback for browsers without IntersectionObserver support
    revealEls.forEach(function (el) { el.classList.add("is-visible"); });
    revealObserver = { observe: function () {} };
  }

  /* ------------------------------------------------------------------ */
  /* Back-to-top button                                                   */
  /* ------------------------------------------------------------------ */
  var toTop = document.getElementById("toTop");
  window.addEventListener(
    "scroll",
    function () {
      toTop.classList.toggle("is-visible", window.scrollY > 600);
    },
    { passive: true }
  );
  toTop.addEventListener("click", function () {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  /* ------------------------------------------------------------------ */
  /* Projects: render cards + modal detail                                */
  /* ------------------------------------------------------------------ */
  var projectsGrid = document.getElementById("projectsGrid");
  var projects = window.PROJECTS_DATA || [];

  function projectCardHTML(p, i) {
    return (
      '<article class="project-card reveal" data-index="' + i + '">' +
        '<div class="project-visual" aria-hidden="true">' +
          '<div class="mini-window">' +
            '<div class="mini-topbar"><i></i><i></i><i></i></div>' +
            '<div class="mini-rows">' +
              '<div class="mini-row"></div>' +
              '<div class="mini-row short"></div>' +
              '<div class="mini-row accent"></div>' +
              '<div class="mini-row"></div>' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div class="project-body">' +
          '<span class="project-kicker">' + p.kicker + '</span>' +
          '<h3>' + p.name + '</h3>' +
          '<p class="project-row"><b>סוג המערכת:</b> ' + p.type + '</p>' +
          '<div class="project-stack">' + p.stack.map(function (s) { return "<span>" + s + "</span>"; }).join("") + '</div>' +
          '<div class="project-footer">' +
            '<button type="button" class="btn btn-ghost btn-sm project-detail-btn" data-index="' + i + '">לפרטים</button>' +
          '</div>' +
        '</div>' +
      '</article>'
    );
  }

  if (projectsGrid) {
    projectsGrid.innerHTML = projects.map(projectCardHTML).join("");
    projectsGrid.querySelectorAll(".reveal").forEach(function (el) { revealObserver.observe(el); });
  }

  var modal = document.getElementById("projectModal");
  var modalClose = document.getElementById("modalClose");
  var modalKicker = document.getElementById("modalKicker");
  var modalTitle = document.getElementById("modalTitle");
  var modalProblem = document.getElementById("modalProblem");
  var modalBuilt = document.getElementById("modalBuilt");
  var modalStack = document.getElementById("modalStack");
  var lastFocusedEl = null;

  function openModal(index) {
    var p = projects[index];
    if (!p) return;
    modalKicker.textContent = p.kicker;
    modalTitle.textContent = p.name;
    modalProblem.textContent = p.problem;
    modalBuilt.textContent = p.built;
    modalStack.innerHTML = p.stack.map(function (s) { return "<span>" + s + "</span>"; }).join("");
    lastFocusedEl = document.activeElement;
    modal.classList.add("is-open");
    document.body.style.overflow = "hidden";
    modalClose.focus();
  }
  function closeModal() {
    modal.classList.remove("is-open");
    document.body.style.overflow = "";
    if (lastFocusedEl) lastFocusedEl.focus();
  }
  if (projectsGrid) {
    projectsGrid.addEventListener("click", function (e) {
      var btn = e.target.closest(".project-detail-btn");
      if (btn) openModal(Number(btn.getAttribute("data-index")));
    });
  }
  modalClose.addEventListener("click", closeModal);
  modal.addEventListener("click", function (e) {
    if (e.target === modal) closeModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && modal.classList.contains("is-open")) closeModal();
  });

  /* ------------------------------------------------------------------ */
  /* Contact form: validation + submit                                   */
  /* ------------------------------------------------------------------ */
  var form = document.getElementById("contactForm");
  var submitBtn = document.getElementById("submitBtn");
  var formStatus = document.getElementById("formStatus");
  var isSubmitting = false;

  var validators = {
    fullName: function (v) {
      if (!v.trim()) return "יש להזין שם מלא.";
      if (v.trim().length < 2) return "השם קצר מדי.";
      return "";
    },
    email: function (v) {
      if (!v.trim()) return "יש להזין כתובת אימייל.";
      var re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!re.test(v.trim())) return "כתובת האימייל אינה תקינה.";
      return "";
    },
    phone: function (v) {
      if (!v.trim()) return "";
      var re = /^[0-9+\-\s()]{7,20}$/;
      if (!re.test(v.trim())) return "מספר הטלפון אינו תקין.";
      return "";
    },
    projectType: function (v) {
      if (!v) return "יש לבחור סוג פרויקט.";
      return "";
    },
    message: function (v) {
      if (!v.trim()) return "יש לתאר את הפרויקט.";
      if (v.trim().length < 20) return "אנא הוסיפו עוד כמה מילים על הפרויקט (לפחות 20 תווים).";
      return "";
    },
    consent: function (checked) {
      if (!checked) return "יש לאשר יצירת קשר כדי לשלוח את הטופס.";
      return "";
    }
  };

  function showFieldError(name, msg) {
    var errEl = document.getElementById("err-" + name);
    var fieldEl = document.getElementById(name);
    var wrapper = fieldEl ? fieldEl.closest(".field") : null;
    if (errEl) errEl.textContent = msg || "";
    if (wrapper) wrapper.classList.toggle("has-error", !!msg);
    if (name === "consent" && errEl) errEl.textContent = msg || "";
  }

  function validateField(name) {
    var el = document.getElementById(name);
    if (!el) return true;
    var value = el.type === "checkbox" ? el.checked : el.value;
    var msg = validators[name] ? validators[name](value) : "";
    showFieldError(name, msg);
    return !msg;
  }

  ["fullName", "email", "phone", "projectType", "message", "consent"].forEach(function (name) {
    var el = document.getElementById(name);
    if (!el) return;
    var evt = el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input";
    el.addEventListener(evt, function () { validateField(name); });
    el.addEventListener("blur", function () { validateField(name); });
  });

  function setLoading(loading) {
    isSubmitting = loading;
    submitBtn.disabled = loading;
    submitBtn.classList.toggle("is-loading", loading);
  }

  async function sendToBackend(payload) {
    var endpoint = cfg.CONTACT_ENDPOINT;
    if (!endpoint) {
      // No backend configured yet — simulate success locally so the UI can
      // be demoed end-to-end. Replace CONTACT_ENDPOINT in js/config.js
      // (or wire a real API — see server/README.md) to send real emails.
      await new Promise(function (r) { setTimeout(r, 900); });
      console.info("[contact-form] Demo mode — payload that would be sent:", payload);
      return { ok: true, demo: true };
    }

    // Formspree (https://formspree.io) expects a JSON POST with an
    // "Accept: application/json" header — without it, it redirects instead
    // of returning JSON, which breaks a fetch()-based flow like this one.
    // "_subject" is a Formspree special field that sets the email subject.
    var body = Object.assign(
      { _subject: "פנייה חדשה מהאתר — " + payload.fullName + " (" + payload.projectType + ")" },
      payload
    );

    var res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(body)
    });

    var data = await res.json().catch(function () { return {}; });

    if (!res.ok) {
      // Formspree error shape: { errors: [{ field, message }, ...] }
      var msg =
        (data && data.errors && data.errors.map(function (e) { return e.message; }).join(" ")) ||
        "Server responded with " + res.status;
      throw new Error(msg);
    }
    return data;
  }

  if (form) {
    form.addEventListener("submit", async function (e) {
      e.preventDefault();
      if (isSubmitting) return;

      // honeypot check — bots fill hidden fields
      var honeypot = document.getElementById("websiteUrl");
      if (honeypot && honeypot.value.trim() !== "") {
        formStatus.textContent = "";
        return; // silently drop — looks like a bot
      }

      var fields = ["fullName", "email", "phone", "projectType", "message", "consent"];
      var allValid = fields.map(validateField).every(Boolean);
      if (!allValid) {
        formStatus.className = "form-status error";
        formStatus.textContent = "יש לתקן את השדות המסומנים לפני השליחה.";
        var firstError = form.querySelector(".has-error input, .has-error select, .has-error textarea");
        if (firstError) firstError.focus();
        return;
      }

      var payload = {
        fullName: document.getElementById("fullName").value.trim(),
        company: document.getElementById("company").value.trim(),
        email: document.getElementById("email").value.trim(),
        phone: document.getElementById("phone").value.trim(),
        projectType: document.getElementById("projectType").value,
        budget: document.getElementById("budget").value,
        message: document.getElementById("message").value.trim(),
        submittedAt: new Date().toISOString()
      };

      setLoading(true);
      formStatus.className = "form-status";
      formStatus.textContent = "";

      try {
        await sendToBackend(payload);
        formStatus.className = "form-status success";
        formStatus.textContent = "תודה, הפרטים התקבלו בהצלחה. אחזור אליכם בהקדם.";
        form.reset();
        fields.forEach(function (name) { showFieldError(name, ""); });
      } catch (err) {
        console.error("[contact-form] submit failed:", err);
        formStatus.className = "form-status error";
        formStatus.textContent = "אירעה שגיאה בשליחת הטופס. נסו שוב, או צרו קשר ישירות באימייל.";
      } finally {
        setLoading(false);
      }
    });
  }
})();
