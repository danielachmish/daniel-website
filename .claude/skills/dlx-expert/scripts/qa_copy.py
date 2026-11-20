#!/usr/bin/env python3
"""qa_copy.py: בדיקת איכות לקופי שיווקי, מודעות מכירה, פוסטים ותגובות לביקורות.

בודק: מגבלות תווים לכל פלטפורמה, טענות אסורות או מסוכנות (עברית ואנגלית), הנעה לפעולה חסרה,
שאריות של placeholders (כמו [לאשר]), קריאות (אורך משפט), כללי עריכה של גוגל, וכללי חוק הספאם
(סעיף 30א) להודעות SMS / מייל / וואטסאפ תפוצה.

קלט:
  * Markdown: כל יחידת קופי בבלוק מגודר עם תגית שדה:
        ```copy meta.primary v=A
        הטקסט...
        ```
    בשדות רשימה (google.headline, google.description, google.callout, google.sitelink, google.path)
    כל שורה היא יחידה נפרדת ("1. " או "- " בתחילת שורה מוסרים). אפשר להוסיף each-line לכל בלוק.
    היתר מתועד לטענה: <!-- qa-allow: מובטח | אחריות יצרן 12 חודשים, תעודה אצל הלקוח -->
  * JSON: {"units":[{"field":"meta.primary","variant":"A","text":"..."}], "qa_allow":[{"term":"..","reason":".."}]}
    או מילון פשוט {"meta.primary": ["..",".."], "google.headline": [..]}.

הפעלה:
  python3 qa_copy.py copy.md            # מסירה סופית: placeholder בקופי = FAIL
  python3 qa_copy.py template.md --draft  # טיוטה/תבנית: placeholder = WARN
  python3 qa_copy.py copy.md --strict   # גם WARN מכשיל
  python3 qa_copy.py copy.md --counts   # רק טבלת ספירת תווים
קוד יציאה: 0 = אין FAIL, 1 = יש FAIL, 2 = שגיאת קלט.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field

# --------------------------------------------------------------------------------------
# מגבלות. hard = FAIL מעל, soft = WARN מעל. src: מקור / רמת אימות (נבדק 11/2026).
# --------------------------------------------------------------------------------------
LIMITS = {
    # Meta (פייסבוק/אינסטגרם) — מקורות צד ג' עקביים; Meta עצמה מציגה כהמלצה ומקצצת בתצוגה
    "meta.primary": {"soft": 125, "hard": 2200, "kind": "ad", "src": "Meta: ~125 תווים נראים לפני 'עוד' (צד ג', עקבי)"},
    "meta.headline": {"soft": 27, "hard": 40, "kind": "ad", "src": "Meta: כותרת 40 מומלץ; ~27 נראים בנייד (לא מאומת)"},
    "meta.description": {"soft": 25, "hard": 30, "kind": "ad", "src": "Meta: תיאור 25-30 (מקורות סותרים)"},
    "meta.reels": {"soft": 72, "hard": 125, "kind": "ad", "src": "Meta Reels: ~72 נראים (צד ג', לא מאומת)"},
    "meta.cta": {"hard": 40, "kind": "button", "src": "כפתור מרשימה סגורה של Meta"},
    # Google RSA — support.google.com/google-ads/answer/7684791 (מאומת)
    "google.headline": {"hard": 30, "kind": "ad", "src": "Google RSA: כותרת עד 30 (רשמי)"},
    "google.description": {"hard": 90, "kind": "ad", "src": "Google RSA: תיאור עד 90 (רשמי)"},
    "google.path": {"hard": 15, "kind": "ad", "src": "Google RSA: נתיב תצוגה עד 15 (רשמי)"},
    "google.sitelink": {"hard": 25, "kind": "ad", "src": "Google: קישור לאתר עד 25"},
    "google.callout": {"hard": 25, "kind": "ad", "src": "Google: נכס יתרון עד 25"},
    # TikTok — ads.tiktok.com: עד 100 תווים כדי לא להיחתך ב'ראה עוד' (רשמי, כהמלצה)
    "tiktok.text": {"hard": 100, "kind": "ad", "src": "TikTok in-feed: 100 תווים (רשמי, המלצת תצוגה)"},
    # אורגני
    "instagram.caption": {"soft": 125, "hard": 2200, "kind": "organic", "hashtags": 5,
                          "src": "Instagram: 2200 תווים; עד 5 האשטגים מ-12/2025"},
    "facebook.post": {"hard": 63206, "kind": "organic", "src": "Facebook post"},
    "linkedin.post": {"soft": 210, "hard": 3000, "kind": "organic", "src": "LinkedIn: 3000; ~210 לפני 'ראה עוד' (לא מאומת)"},
    "gbp.post": {"hard": 1500, "kind": "organic", "src": "Google Business Profile post: 1500"},
    "gbp.reply": {"soft": 600, "hard": 4000, "kind": "reply", "src": "תגובת בעלים: 4000-4096 (לא מאומת); מעל 600 = ארוך מדי"},
    "youtube.title": {"soft": 70, "hard": 100, "kind": "organic", "src": "YouTube: כותרת 100, ~70 נראים"},
    "youtube.description": {"hard": 5000, "kind": "organic", "src": "YouTube: תיאור 5000"},
    "post": {"kind": "organic", "src": "פוסט כללי"},
    "landing": {"kind": "ad", "src": "טקסט דף נחיתה (חייב הנעה לפעולה)"},
    # הודעות ישירות (חוק הספאם)
    "sms": {"soft": 70, "hard": 335, "kind": "direct", "src": "SMS עברי: 70 תווים להודעה אחת (UCS-2)"},
    "email.subject": {"soft": 60, "hard": 150, "kind": "direct", "src": "שורת נושא"},
    "email.body": {"kind": "direct", "src": "גוף מייל"},
    "whatsapp.broadcast": {"soft": 700, "kind": "direct", "src": "הודעת תפוצה"},
    "whatsapp": {"soft": 700, "kind": "chat", "src": "הודעה אישית (תשובה לפנייה)"},
    # מודעות מכירה
    "listing.title": {"hard": 60, "kind": "listing", "src": "כותרת מודעה: עד ~60, המילים החשובות בהתחלה"},
    "listing.body": {"hard": 4000, "kind": "listing", "src": "גוף מודעה"},
    "listing.short": {"soft": 400, "hard": 700, "kind": "listing", "src": "גרסה קצרה לוואטסאפ/סטטוס"},
    "reply": {"soft": 500, "kind": "chat", "src": "תשובה מוכנה לפנייה"},
}
HOOK_FIELDS = {"meta.primary", "instagram.caption", "linkedin.post"}
LIST_FIELDS = {"google.headline", "google.description", "google.path", "google.sitelink", "google.callout"}
META_CTA_BUTTONS = {
    "הרשמה", "להרשמה", "למידע נוסף", "מידע נוסף", "שליחת הודעה", "צור קשר", "יצירת קשר", "קנה עכשיו", "לקנייה",
    "הזמנה", "להזמנה", "קבלת הצעת מחיר", "הורדה", "הגשת מועמדות", "שליחת הודעת WhatsApp", "התקשרו עכשיו",
    "Sign Up", "Learn More", "Send Message", "Contact Us", "Shop Now", "Book Now", "Get Quote", "Download",
    "Apply Now", "Subscribe", "Send WhatsApp Message", "Call Now", "Get Offer", "Order Now",
}

# --------------------------------------------------------------------------------------
# טענות. (regex, severity, הסבר). severity: FAIL / WARN. qa-allow מוריד FAIL ל-WARN עם נימוק.
# --------------------------------------------------------------------------------------
H = r"(?:^|(?<=[\s\"'(״׳\-–—/]))[ובלהשמכ]?"  # תחילית עברית אופציונלית
CLAIMS = [
    # הפלגה / סופרלטיב בלי הוכחה (חוק הגנת הצרכן ס' 7; Google: superlatives require 3rd-party verification)
    (H + r"הכי\s+(?:טוב|טובה|טובים|זול|זולה|משתלם|איכותי|מקצועי|גדול|מהיר|אמין)\S*", "FAIL",
     "סופרלטיב בלי הוכחה ('הכי ...'). הטעיה אפשרית (ס' 7 לחוק הגנת הצרכן); בגוגל דורש אימות צד ג' בדף הנחיתה"),
    (H + r"ה?[א-ת]{2,}\s+ביותר\b", "FAIL", "סופרלטיב ('... ביותר') בלי הוכחה"),
    (r"(?:מספר|מס['׳]|נמבר)\s*(?:1|אחת|אחד)\b|#1\b|\bnumber\s+one\b|\bno\.?\s*1\b", "FAIL", "'מספר 1' בלי מקור מאומת"),
    (r"\bbest\s+(?:in|ever|price|quality)\b|\bthe\s+best\b|\bworld[- ]class\b", "FAIL", "superlative claim without proof"),
    (H + r"מובטח(?:ת|ים|ות)?\b|" + H + r"מבטיחים\b|" + H + r"הבטחה\s+ל|\bguarantee[ds]?\b", "FAIL",
     "הבטחה לתוצאה. מותר רק אחריות/החזר אמיתיים עם תנאים (qa-allow + תנאים בדף)"),
    (r"100\s*%|100\s*אחוז|מאה\s+אחוז", "FAIL", "'100%' כטענה מוחלטת. מותר רק כנתון מדיד (100% כותנה) עם qa-allow"),
    (H + r"(?:ללא|בלי|אפס)\s+סיכון|\brisk[- ]free\b|\bno\s+risk\b", "FAIL", "'ללא סיכון' — טענה מוחלטת"),
    # טענות רפואיות / בריאות (Meta Health & Wellness; Google Unreliable claims)
    (H + r"מרפא\b|" + H + r"מרפאים\b|" + H + r"ריפוי\b|" + H + r"מונע\S*\s+(?:מחל|סרטן)|\bcures?\b|\bheals?\b",
     "FAIL", "טענה רפואית (ריפוי/מניעת מחלה)"),
    (r"מוכח\S*\s+(?:מדעית|קלינית)|נבדק\S*\s+קלינית|\b(?:clinically|scientifically)\s+proven\b", "FAIL",
     "'מוכח מדעית/קלינית' בלי מחקר שאפשר להציג"),
    (r"בלי\s+תופעות\s+לוואי|ללא\s+תופעות\s+לוואי|\bno\s+side\s+effects\b", "FAIL", "טענה רפואית מוחלטת"),
    (r"(?:לרדת|ירידה\s+של)\s+\d+\s*(?:ק\"?ג|קילו)|\blose\s+\d+\s*(?:kg|lbs?|pounds)\b", "FAIL", "הבטחת ירידה במשקל"),
    (r"התעשר\S*\s+מהר|הכנסה\s+פסיבית\s+(?:מובטחת|קבועה)|\bget\s+rich\b", "FAIL", "הבטחה פיננסית לא סבירה"),
    # Meta: מאפיינים אישיים (Personal attributes)
    (r"(?:האם\s+)?(?:אתה|את|אתם|אתן)\s+(?:סובל|סובלת|סובלים|שמן|שמנה|בחובות?|גרוש|גרושה|בדיכאון|חולה|רווק|רווקה)\S*"
     r"|\bare\s+you\s+(?:overweight|in\s+debt|depressed|diabetic|single|divorced)\b", "FAIL",
     "פנייה שמניחה מאפיין אישי של הקורא (מדיניות Meta: Personal attributes)"),
    # WARN — מותר רק אם אמיתי
    (H + r"חינם\b|" + H + r"בחינם\b|\bfree\b", "WARN", "'חינם' — ודא שבאמת בלי תנאי או עלות נסתרת"),
    (r"רק\s+היום|לזמן\s+מוגבל|(?:ה)?אחרונים\b|נשארו\s+רק|מסתיים\s+(?:היום|מחר|הערב)|\blast\s+chance\b|\blimited\s+time\b",
     "WARN", "דחיפות — חייבת להיות אמיתית ומתועדת (תאריך סיום/מלאי)"),
    (r"במקום\s*₪?\s*\d|מחיר\s+(?:מבצע|לפני)|\d+\s*%\s*הנחה|הנחה\s+של\s+\d+\s*%", "WARN",
     "מחיר 'לפני'/אחוז הנחה — ה'לפני' חייב להיות מחיר שנגבה בפועל"),
    (r"(?:דירוג|ציון)\s*\d(?:\.\d)?|\d(?:\.\d)?\s*(?:כוכבים|★)|★{3,}", "WARN", "דירוג/כוכבים — רק אם אמיתי ומתועד"),
    (r"לפני\s+ו?אחרי|\bbefore\s*(?:&|and|/)\s*after\b", "WARN", "'לפני/אחרי' — בתחום בריאות/מראה אסור ב-Meta"),
    (H + r"הכי\s+\S+", "WARN", "'הכי ...' — לוודא שיש הוכחה"),
]
AI_CLICHES = [
    r"בעולם\s+המשתנה", r"בעידן\s+(?:ה)?דיגיטלי", r"חדשני(?:ת|ים)?\s+ו(?:ה)?מתקדמ", r"פתרון\s+מהפכני",
    r"לשלב\s+הבא", r"חוויה\s+בלתי\s+נשכחת", r"מעבר\s+לכל\s+דמיון", r"הפתרון\s+המושלם", r"\bgame[- ]changer\b",
    r"in\s+today['’]s\s+fast[- ]paced", r"\belevate\s+your\b", r"\bunlock\s+the\s+power\b", r"\bseamless(?:ly)?\b",
]
CTA_WORDS = [
    # עברית: ציווי/שם פעולה
    "הירשמו", "הירשם", "הירשמי", "הרשמה", "להרשמה", "פתחו", "פתחי", "פתח", "פתיחת", "התקשרו", "התקשר", "חייגו", "שלחו",
    "שלח", "כתבו", "כתוב", "לחצו", "לחץ", "הזמינו", "הזמן", "להזמנה", "קנו", "לקנייה", "היכנסו", "כנסו", "צרו קשר",
    "צור קשר", "השאירו", "השאר", "תאמו", "לתיאום", "בואו", "בוא", "הגיעו", "דברו", "תשאלו", "שאלו", "הורידו", "נסו",
    "קבלו", "קבל", "בדקו", "הצטרפו", "הצטרף", "לפרטים", "וואטסאפ", "ווטסאפ", "WhatsApp", "התחילו", "שמרו", "שתפו",
    "תייגו", "צפו", "לצפייה", "תגיבו", "הגיבו", "ענו", "פנו", "לפנייה", "זמין", "זמינה", "מחכה לפנייה",
    # אנגלית
    "sign up", "register", "call", "shop", "book", "buy", "order", "learn more", "contact", "get", "join", "start",
    "download", "visit", "message", "apply",
]
CTA_RE = re.compile("|".join(r"(?:^|[\s\"'(״׳\-–—/:])[ו]?" + re.escape(w) for w in CTA_WORDS), re.I)
PLACEHOLDER_RE = re.compile(
    r"\[(?:לאשר|להשלים|לבדוק|חסר|TBD|TODO|todo|placeholder)[^\]]*\]|\[[^\]\n]{0,40}\.\.\.[^\]\n]{0,40}\]|\[\s*\]"
    r"|\{\{[^}]*\}\}|<<[^>]*>>|\bTODO\b|\bTBD\b|\bXXX+\b|lorem\s+ipsum|_{4,}|\[[א-ת][^\]\n]{0,60}\]"
)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?972[\s-]?|0)(?:[23489]|5\d|7\d)[\s-]?\d{3}[\s-]?\d{4}(?!\d)|\*\d{4}\b")
PRICE_RE = re.compile(r"(?:₪\s*\d|\d[\d,\.]*\s*(?:₪|ש\"ח|ש״ח|שקל|ש'ח|NIS|ILS))")
CONTACT_RE = re.compile(r"וואטסאפ|ווטסאפ|WhatsApp|טלפון|טל['׳]|\d{2,3}-?\d{7}|\d{3}-\d{3}-\d{4}|הודעה|צ['׳]אט|התקשר|שלחו|כתבו|בפרטי", re.I)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+|\s+[•·|]\s+")


@dataclass
class Unit:
    field: str
    text: str
    variant: str = ""
    line: int = 0

    @property
    def label(self) -> str:
        v = f" {self.variant}" if self.variant else ""
        return f"{self.field}{v}" + (f" (שורה {self.line})" if self.line else "")


@dataclass
class Report:
    rows: list = field(default_factory=list)  # (sev, label, msg)

    def add(self, sev: str, label: str, msg: str) -> None:
        self.rows.append((sev, label, msg))

    def count(self, sev: str) -> int:
        return sum(1 for r in self.rows if r[0] == sev)


def nchars(s: str) -> int:
    return len(unicodedata.normalize("NFC", s.strip()))


# ----------------------------------- parsing ------------------------------------------
FENCE_RE = re.compile(r"^```copy\s+([\w.\-]+)([^\n]*)$")
ALLOW_RE = re.compile(r"<!--\s*qa-allow:\s*(.+?)\s*\|\s*(.+?)\s*-->")


def parse_markdown(text: str):
    units, allows, outside = [], [], []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = FENCE_RE.match(lines[i].strip())
        if not m:
            outside.append((i + 1, lines[i]))
            for a in ALLOW_RE.finditer(lines[i]):
                allows.append({"term": a.group(1), "reason": a.group(2)})
            i += 1
            continue
        fld, opts = m.group(1), m.group(2)
        variant = ""
        vm = re.search(r"\bv=([\w\-א-ת]+)", opts)
        if vm:
            variant = vm.group(1)
        each = fld in LIST_FIELDS or "each-line" in opts
        start = i + 1
        body = []
        i += 1
        while i < len(lines) and lines[i].strip() != "```":
            body.append(lines[i])
            i += 1
        i += 1  # skip closing fence
        if each:
            for k, ln in enumerate(body):
                t = re.sub(r"^\s*(?:\d+[.)]\s+|[-*]\s+)", "", ln).rstrip()
                if t.strip():
                    units.append(Unit(fld, t, variant, start + k + 1))
        else:
            t = "\n".join(body).strip()
            if t:
                units.append(Unit(fld, t, variant, start + 1))
    return units, allows, outside


def parse_json(data):
    units, allows = [], []
    if isinstance(data, dict) and "units" in data:
        for u in data["units"]:
            units.append(Unit(u["field"], str(u["text"]), str(u.get("variant", ""))))
        allows = data.get("qa_allow", [])
    elif isinstance(data, dict):
        for k, v in data.items():
            if k == "qa_allow":
                allows = v
                continue
            for t in (v if isinstance(v, list) else [v]):
                units.append(Unit(k, str(t)))
    else:
        raise ValueError("JSON חייב להיות אובייקט")
    return units, allows, []


# ----------------------------------- checks -------------------------------------------
def base_field(f: str) -> str:
    if f in LIMITS:
        return f
    parts = f.split(".")
    while parts:
        cand = ".".join(parts)
        if cand in LIMITS:
            return cand
        parts.pop()
    return "post"


def check_unit(u: Unit, rep: Report, allows: list, draft: bool) -> None:
    bf = base_field(u.field)
    lim = LIMITS.get(bf, {})
    n = nchars(u.text)
    if u.field not in LIMITS and bf == "post" and u.field != "post":
        rep.add("WARN", u.label, f"שדה לא מוכר '{u.field}' — נבדק כפוסט כללי (אין מגבלת תווים)")
    hard, soft = lim.get("hard"), lim.get("soft")
    ph = bool(PLACEHOLDER_RE.search(u.text))
    if hard and n > hard:
        rep.add("WARN" if (draft and ph) else "FAIL", u.label, f"{n}/{hard} תווים — חורג ממגבלת הפלטפורמה ({lim['src']})")
    elif soft and n > soft:
        if bf in HOOK_FIELDS:  # הטקסט נחתך אחרי ~soft תווים: מה שחשוב הוא שההוק (השורה הראשונה) נכנס
            first = nchars(u.text.split("\n", 1)[0])
            if first > soft:
                rep.add("WARN", u.label, f"השורה הראשונה {first} תווים — ההוק נחתך לפני 'עוד' (~{soft}). לקצר אותה ({lim['src']})")
        else:
            rep.add("WARN", u.label, f"{n} תווים — מעל {soft} נחתך בתצוגה; המילים החשובות בהתחלה ({lim['src']})")

    # placeholders
    for m in PLACEHOLDER_RE.finditer(u.text):
        rep.add("WARN" if draft else "FAIL", u.label, f"שארית placeholder בקופי: '{m.group(0)}'")

    # claims
    low = u.text
    seen = set()
    for rx, sev, why in CLAIMS:
        for m in re.finditer(rx, low, re.I | re.M):
            hit = m.group(0).strip()
            key = (hit, why)
            if key in seen:
                continue
            seen.add(key)
            # WARN 'הכי' כפול ל-FAIL שכבר נתפס
            if sev == "WARN" and any(hit in s[0] or s[0] in hit for s in seen if s[1] != why and s != key):
                continue
            allow = next((a for a in allows if a["term"] and a["term"] in u.text and
                          (a["term"] in hit or hit in a["term"])), None)
            if allow and sev == "FAIL":
                rep.add("WARN", u.label, f"'{hit}' — הותר: {allow['reason']}")
            else:
                rep.add(sev, u.label, f"'{hit}' — {why}")
    for rx in AI_CLICHES:
        m = re.search(rx, u.text, re.I)
        if m:
            rep.add("FAIL", u.label, f"קלישאה שנשמעת כמו AI: '{m.group(0)}' — כתוב משהו ספציפי")

    # platform editorial
    if bf.startswith("google."):
        if EMOJI_RE.search(u.text):
            rep.add("FAIL", u.label, "אימוג'י אסור במודעות חיפוש של גוגל")
        if bf == "google.headline" and "!" in u.text:
            rep.add("FAIL", u.label, "סימן קריאה אסור בכותרת גוגל")
        if re.search(r"([!?.])\1", u.text):
            rep.add("FAIL", u.label, "פיסוק כפול ('!!', '??', '..') אסור בגוגל")
        if bf == "google.description" and u.text.count("!") > 1:
            rep.add("FAIL", u.label, "יותר מסימן קריאה אחד בתיאור גוגל")
        if PHONE_RE.search(u.text):
            rep.add("FAIL", u.label, "מספר טלפון בטקסט מודעת גוגל — נפסל. משתמשים בנכס שיחה (Call asset)")
        caps = [w for w in re.findall(r"\b[A-Z]{4,}\b", u.text) if w not in {"BASELINE", "HTML", "USB", "JSON", "IMEI", "LED", "HDMI", "SSD"}]
        if caps:
            rep.add("WARN", u.label, f"אותיות גדולות ברצף ({', '.join(caps)}) — גוגל פוסל אם זה לא שם מותג")
    if bf == "meta.cta" and u.text.strip() not in META_CTA_BUTTONS:
        rep.add("WARN", u.label, f"'{u.text.strip()}' לא ברשימת כפתורי ההנעה של Meta — בחר כפתור קיים")
    if "hashtags" in lim:
        tags = re.findall(r"#[\w֐-׿]+", u.text)
        if len(tags) > lim["hashtags"]:
            rep.add("FAIL", u.label, f"{len(tags)} האשטגים — אינסטגרם מגביל ל-{lim['hashtags']} (מ-12/2025)")
    if lim.get("kind") in {"ad", "organic", "direct", "listing"} and bf not in LIST_FIELDS and bf != "meta.cta":
        if u.text.count("!") > 2:
            rep.add("WARN", u.label, f"{u.text.count('!')} סימני קריאה — נשמע צועק/זול")
        if len(EMOJI_RE.findall(u.text)) > 4:
            rep.add("WARN", u.label, "יותר מ-4 אימוג'ים")

    # spam law (ס' 30א לחוק התקשורת)
    law = "WARN" if (draft and ph) else "FAIL"  # בתבנית לא ממולאת: אזהרה
    if bf in {"sms", "whatsapp.broadcast", "email.body"}:
        if bf != "email.body" and not re.match(r"\s*\"?פרסומת", u.text):
            rep.add(law, u.label, "הודעה שיווקית חייבת להתחיל במילה 'פרסומת' (ס' 30א)")
        if not re.search(r"הסר|להסרה|הסרה|STOP|unsubscribe", u.text, re.I):
            rep.add(law, u.label, "חסרה דרך הסרה מרשימת התפוצה (ס' 30א)")
        if not (PHONE_RE.search(u.text) or re.search(r"[\w.\-]+@[\w\-]+\.\w+", u.text)):
            rep.add(law, u.label, "חסרים פרטי המפרסם ודרך ליצירת קשר (שם + טלפון או מייל) (ס' 30א)")
    if bf == "email.subject" and not re.match(r"\s*\"?פרסומת", u.text):
        rep.add(law, u.label, "שורת נושא של מייל שיווקי חייבת להתחיל ב'פרסומת' (ס' 30א)")

    # readability
    if bf not in LIST_FIELDS and bf not in {"meta.cta", "meta.headline", "meta.description", "listing.title"}:
        sents = [s for s in SENTENCE_SPLIT.split(u.text) if s.strip()]
        for s in sents:
            w = len(s.split())
            if w > 30:
                rep.add("FAIL", u.label, f"משפט של {w} מילים (מעל 30): '{s.strip()[:50]}…' — לפרק")
            elif w > 20:
                rep.add("WARN", u.label, f"משפט של {w} מילים (מעל 20): '{s.strip()[:50]}…'")
        lines_ = [ln for ln in u.text.split("\n") if ln.strip()]
        long_par = [ln for ln in lines_ if nchars(ln) > 300]
        if long_par:
            rep.add("WARN", u.label, f"פסקה של {nchars(long_par[0])} תווים בלי ירידת שורה — קשה לקריאה בטלפון")


def check_groups(units: list, rep: Report, draft: bool = False) -> None:
    # CTA: לכל קבוצה (וריאנט) של מודעה/מודעת מכירה/הודעה ישירה חייבת להיות הנעה לפעולה
    groups: dict = {}
    for u in units:
        kind = LIMITS.get(base_field(u.field), {}).get("kind", "organic")
        platform = u.field.split(".")[0]
        if u.variant or base_field(u.field) in LIST_FIELDS:  # מודעת RSA אחת = כל הכותרות והתיאורים שלה
            key = (platform, u.variant)
        else:
            key = (u.field, id(u))
        groups.setdefault(key, []).append((u, kind))
    for key, items in groups.items():
        kinds = {k for _, k in items}
        text = "\n".join(u.text for u, _ in items)
        has_cta = bool(CTA_RE.search(text)) or any(base_field(u.field) == "meta.cta" for u, _ in items)
        label = items[0][0].label if isinstance(key[1], int) else f"{key[0]} {key[1]}".strip()
        sev = "WARN" if (draft and PLACEHOLDER_RE.search(text)) else "FAIL"  # תבנית לא ממולאת
        if kinds & {"ad", "listing", "direct"} and not has_cta:
            rep.add(sev, label, "אין הנעה לפעולה (פועל ברור: הירשמו / שלחו / התקשרו ...)")
        elif "organic" in kinds and not has_cta and not any(base_field(u.field).startswith("youtube") for u, _ in items):
            rep.add("WARN", label, "פוסט בלי הנעה לפעולה (שמרו / שתפו / כתבו לנו ...) — מותר, אבל בכוונה")
        if "listing" in kinds and any(base_field(u.field) == "listing.body" for u, _ in items):
            if not PRICE_RE.search(text):
                rep.add(sev, label, "מודעת מכירה בלי מחיר (₪)")
            if not CONTACT_RE.search(text):
                rep.add(sev, label, "מודעת מכירה בלי דרך ליצירת קשר")

    # Google RSA: כמות, ייחודיות
    for fld, lo, rec, hi in (("google.headline", 3, 10, 15), ("google.description", 2, 4, 4)):
        by_v: dict = {}
        for u in units:
            if base_field(u.field) == fld:
                by_v.setdefault(u.variant, []).append(u)
        for v, us in by_v.items():
            lbl = f"{fld} {v}".strip()
            if len(us) < lo:
                rep.add("FAIL", lbl, f"רק {len(us)} — מודעה רספונסיבית דורשת לפחות {lo}")
            elif len(us) < rec:
                rep.add("WARN", lbl, f"{len(us)} — מומלץ {rec}+ כדי שגוגל יוכל לשלב")
            if len(us) > hi:
                rep.add("FAIL", lbl, f"{len(us)} — המקסימום הוא {hi}")
            norm = [re.sub(r"\s+", " ", u.text.strip()) for u in us]
            dups = {t for t in norm if norm.count(t) > 1}
            for d in dups:
                rep.add("WARN" if (draft and PLACEHOLDER_RE.search(d)) else "FAIL", lbl, f"כפילות: '{d}' — גוגל דורש נכסים ייחודיים")

    # Meta: מספר זוויות
    vs = {u.variant for u in units if base_field(u.field) == "meta.primary"}
    if vs and len(vs) < 3:
        rep.add("WARN", "meta.primary", f"{len(vs)} וריאנטים בלבד — הסטנדרט 3 זוויות שונות לבדיקה")
    prim = [u for u in units if base_field(u.field) == "meta.primary"]
    texts = [re.sub(r"\s+", " ", u.text) for u in prim]
    for t in {t for t in texts if texts.count(t) > 1}:
        rep.add("WARN" if (draft and PLACEHOLDER_RE.search(t)) else "FAIL", "meta.primary", f"שני וריאנטים זהים: '{t[:40]}…'")


def check_outside(outside: list, rep: Report) -> None:
    hits = []
    for ln, txt in outside:
        for m in PLACEHOLDER_RE.finditer(txt):
            hits.append(f"ש' {ln}: {m.group(0)}")
    if hits:
        rep.add("WARN", "מחוץ לקופי", f"{len(hits)} פריטים פתוחים לאישור הלקוח: " + "; ".join(hits[:8])
                + (" …" if len(hits) > 8 else ""))


def counts_table(units: list) -> str:
    out = ["| שדה | תווים | מגבלה | טקסט |", "|---|---|---|---|"]
    for u in units:
        lim = LIMITS.get(base_field(u.field), {})
        cap = lim.get("hard") or lim.get("soft") or "—"
        t = u.text.replace("\n", " ⏎ ")
        out.append(f"| {u.field} {u.variant} | {nchars(u.text)} | {cap} | {t[:60]}{'…' if len(t) > 60 else ''} |")
    return "\n".join(out)


def run(path: str, draft: bool = False, strict: bool = False, counts: bool = False, quiet: bool = False) -> int:
    try:
        raw = open(path, encoding="utf-8").read()
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    try:
        if path.endswith(".json"):
            units, allows, outside = parse_json(json.loads(raw))
        else:
            units, allows, outside = parse_markdown(raw)
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        print(f"ERROR: קלט לא תקין: {e}", file=sys.stderr)
        return 2
    if counts:
        print(counts_table(units))
        return 0
    rep = Report()
    if not units:
        rep.add("WARN" if draft else "FAIL", "קובץ", "לא נמצאה אף יחידת קופי (בלוק ```copy <שדה>```)")
    for u in units:
        check_unit(u, rep, allows, draft)
    check_groups(units, rep, draft)
    check_outside(outside, rep)

    if not quiet:
        print(f"qa_copy: {path}  ({len(units)} יחידות קופי, מצב {'טיוטה' if draft else 'מסירה'})")
        print(counts_table(units))
        print()
        order = {"FAIL": 0, "WARN": 1}
        for sev, label, msg in sorted(rep.rows, key=lambda r: order[r[0]]):
            print(f"{sev:5} [{label}] {msg}")
    f, w = rep.count("FAIL"), rep.count("WARN")
    verdict = "FAIL" if f or (strict and w) else "PASS"
    print(f"\nסיכום: {verdict} — {f} FAIL, {w} WARN")
    return 1 if verdict == "FAIL" else 0


def main() -> None:
    ap = argparse.ArgumentParser(description="QA לקופי שיווקי (עברית/אנגלית)")
    ap.add_argument("file")
    ap.add_argument("--draft", action="store_true", help="תבנית/טיוטה: placeholder = WARN")
    ap.add_argument("--strict", action="store_true", help="גם WARN מכשיל")
    ap.add_argument("--counts", action="store_true", help="רק טבלת ספירת תווים")
    a = ap.parse_args()
    sys.exit(run(a.file, a.draft, a.strict, a.counts))


if __name__ == "__main__":
    main()
