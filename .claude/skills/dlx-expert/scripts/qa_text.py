#!/usr/bin/env python3
"""qa_text.py - content QA for documents and decks. Exits 1 on any FAIL (so it can gate a delivery).

Usage:
  python3 qa_text.py FILE [--type cv|quote|letter|pitch|deck|doc] [--pdf FILE.pdf] [--max-pages N]
                          [--min-pt 24] [--final]

FILE: .docx or .pptx (the source: QA reads structure, not pixels). Pass --pdf with the rendered PDF (or let
the script render it with LibreOffice) for page count and font embedding.

Checks (FAIL unless marked WARN):
  all     template leftovers ({{x}}, TODO, Lorem ipsum, <<x>>); placeholder [לאשר] (WARN, FAIL with --final =
          "this is going to the recipient now"); the retired marker [להשלים] (FAIL: one marker only);
          bidi patterns that render wrong (C++ -> ++C, "Stripe. 3", "X%", ranges without LRM, +972);
          READING ORDER of every rendered line (needs pymupdf): the glyphs are read back right-to-left with
          Latin/number runs kept LTR, and every line must appear in the source text - catches any bidi bug;
          strong claims ("הרוב", "מוכח", "כבר משלמים", "פי 3"...) without a source or [לאשר] (FAIL), soft claims
          ("תוך 5 שניות", "ב-20%") listed (WARN); AI clichés (WARN; CV clichés FAIL).
          Sources: the builders store spec "sources" [{"claim","source"}] in the file properties.
  docx    Hebrew paragraph without RTL (w:bidi); Hebrew run without complex-script size (WARN); table with Hebrew
          that is not visually RTL (WARN)
  quote   every line qty x unit = line total; subtotal = sum; VAT line = rate x net; total = net + VAT;
          VAT rate = 18% (Israel since 1.1.2025, re-verify yearly); exempt dealer (עוסק פטור) must NOT charge VAT;
          licensed dealer must show VAT; must state validity, what is not included, payment terms
  quote   (web project) must cover accessibility (נגישות), privacy (פרטיות), hosting (אחסון) and bug warranty
          (אחריות)
  letter  no self-incriminating phrasing ("טעות בתום לב", "לא שמתי לב"...); appeal must state the deadline basis
          (229); numbered fact paragraphs without an annex reference (WARN)
  cv      pages <= 2 (FAIL), 2 pages = WARN for under ~10 years experience; at least one number in bullets;
          text under 10pt (FAIL); bullets that do not open with a verb (WARN); page under 80% full (WARN)
  pptx    every run >= --min-pt (default 24; shapes named footer-* exempt); text overflowing its box (measured
          with the real font metrics); > 45 words on a slide (WARN); missing speaker notes (WARN);
          pitch: > 15 slides FAIL, < 8 WARN
  pdf     fonts not embedded; fallback fonts (DejaVu/Liberation) instead of the design fonts (WARN);
          last page less than 40% full in a multi-page document (FAIL: rebalance, don't leave a half-empty page)
"""
import argparse
import glob
import math
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json  # noqa: E402
from hebrew_text import (HARD_LEFTOVER, HEB, OLD_MARKER, PLACEHOLDER, bidi_problems, find_claims,  # noqa: E402
                         find_dummies, has_hebrew, CURRENT_RANGE, CASE_LAW)

VAT_RATE = 18  # Israel, from 1.1.2025 (רשות המסים). Verified 11/2026 - re-check every January.
AI_CLICHES = ["בעולם המשתנה", "חשוב לציין", "לסיכום ניתן לומר", "הנני לפנות", "בעידן של היום", "מהווה פתרון",
              "פתרון מקצה לקצה", "חוויה בלתי נשכחת", "ללא ספק", "יתרה מזאת"]
CV_CLICHES = ["אוהב/ת לקחת", "אוהבת לקחת", "אוהב לקחת", "יכולת למידה גבוהה", "יחסי אנוש מצוינים", "ראש גדול",
              "מוטיבציה גבוהה", "תודעת שירות גבוהה", "עבודה בצוות וגם עצמאית", "יכולת עבודה תחת לחץ", "תקתקנית"]
SELF_INCRIM = ["טעות בתום לב", "לא שמתי לב", "אני מודה", "הודיתי", "חניתי באיסור", "ידעתי שאסור", "רק לכמה דקות",
               "לא ראיתי שאסור"]
HEB_VERB = re.compile(r"^(?:[\u05d0-\u05ea]{2,}תי|[\u05d0-\u05ea]{2,}נו|אחראית|אחראי)(?=\s|$)")
SOURCES = []
SUPPLIED = []
LTR_DOC = False
SLIDE_INSTRUCTIONS = ["המחשה", "בלי מקור", "אין עדיין נתונים", "נבדק מול", "לפני הפגישה", "לא מציגים", "להחליף ב",
                      "לבדוק מול", "TBD"]
COMPETITOR_CLAIM = re.compile(r"מתחר|רק אנחנו|אנחנו את|טובים יותר|היחידים|לעומת")
TRACKING = re.compile(r"פיקסל|Pixel|Google Analytics|Tag Manager|Hotjar|TikTok Pixel", re.I)
FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", "documents", "fonts")

results = []


def log(level, msg):
    results.append((level, msg))


def num(s):
    s = s.replace("‎", "").replace("‏", "").replace(",", "")
    m = re.findall(r"-?\d+(?:\.\d+)?", s)
    return float(m[0]) if m else None


# ---------------------------------------------------------------- generic text checks
def norm(s):
    return re.sub(r"[×=÷\s\u00a0\u2060\u200e\u200f\u202a-\u202e\u2066-\u2069()\[\]{}\"'״׳“”‘’•]", "", s)


def check_text(paras, kind=None):
    full = "\n".join(paras)
    for m in OLD_MARKER.finditer(full):
        log("FAIL", f"סימון ישן '{m.group(0)}': משתמשים רק ב-[לאשר: ...]")
    sourced = " ".join(x.get("claim", "") for x in SOURCES)
    strong, soft = [], []
    for p in paras:
        for lvl, snip in find_claims(p):
            if snip in sourced:
                continue
            (strong if lvl == "strong" else soft).append(f"'{snip}' ב: {p.strip()[:50]}")
    for c in strong:
        log("FAIL", f"טענה בלי מקור (להוסיף מקור ל-sources או לסמן [לאשר]): {c}")
    if soft:
        log("WARN", f"{len(soft)} טענות עם מספר/תוצאה: לוודא שכל אחת מהלקוח או ממקור: " + " | ".join(soft[:5]))
    supplied = " ".join(SUPPLIED)
    for p in paras:
        for k, snip in find_dummies(p):
            if snip not in supplied:
                log("FAIL", f"{k} בלי סימון: '{snip}'. פרט שלא נמסר מהלקוח = [לאשר: ...], או להוסיף ל-supplied")
    for p in paras:
        if CURRENT_RANGE.search(p):
            log("FAIL", f"טווח שמסתיים ב'היום': '{p.strip()[:50]}'. כותבים 'מ-2025 (נוכחי)', בלי טווח")
    primary = " ".join(x.get("source", "") for x in SOURCES if x.get("primary"))
    for m in CASE_LAW.finditer(full):
        if m.group(0) not in " ".join(x.get("claim", "") for x in SOURCES if x.get("primary")):
            log("FAIL", f"פסיקה בלי אימות במקור ראשוני ('{m.group(0)}'): מאתר הרשות השופטת או מנבו, עם "
                        "\"primary\": true ב-sources. לא נבדק? מוחקים, לא מסמנים")
    if TRACKING.search(full) and not re.search(r"עוגיות|קוקיז|cookies", full, re.I):
        log("FAIL", "יש כלי מעקב (פיקסל / Analytics) בלי שורת הסכמה לעוגיות (באנר עוגיות ומדיניות)")
    if kind == "cv":
        for c in CV_CLICHES:
            if c in full:
                log("FAIL", f"קלישאה בקורות חיים: '{c}'. להחליף בהישג עם מספר")
    for m in HARD_LEFTOVER.finditer(full):
        log("FAIL", f"שארית תבנית: '{m.group(0)}'")
    ph = PLACEHOLDER.findall(full)
    if ph:
        lvl = "FAIL" if ARGS.final else "WARN"
        log(lvl, f"{len(ph)} מקומות לאישור/השלמה (מסומנים בצהוב): " + ", ".join(sorted(set(ph))[:6]))
    for p in paras:
        for k, snip in bidi_problems(p):
            log("FAIL", f"כיווניות: {k}: '{snip}'")
    for c in AI_CLICHES:
        if c in full:
            log("WARN", f"ביטוי שחוק/AI: '{c}'")


# ---------------------------------------------------------------- docx
def docx_paras(doc):
    out = [p for p in doc.paragraphs]
    for sec in doc.sections:
        for hf in (sec.header, sec.footer):
            out.extend(hf.paragraphs)
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                out.extend(c.paragraphs)
    return out


def check_docx(path):
    from docx import Document
    from docx.oxml.ns import qn
    doc = Document(path)
    normal_bidi = doc.styles["Normal"].element.find(qn("w:pPr"))
    normal_bidi = normal_bidi is not None and normal_bidi.find(qn("w:bidi")) is not None
    paras = docx_paras(doc)
    texts = [p.text for p in paras]
    global LTR_DOC
    LTR_DOC = (doc.core_properties.language or "").startswith("en")
    no_rtl, no_cs = 0, 0
    for p in paras:
        if not has_hebrew(p.text):
            continue
        pPr = p._p.pPr
        if not normal_bidi and (pPr is None or pPr.find(qn("w:bidi")) is None):
            no_rtl += 1
        for r in p.runs:
            rPr = r._r.rPr
            if has_hebrew(r.text) and rPr is not None and rPr.find(qn("w:sz")) is not None \
                    and rPr.find(qn("w:szCs")) is None:
                no_cs += 1
    if no_rtl and not LTR_DOC:
        log("FAIL", f"{no_rtl} פסקאות בעברית בלי כיוון RTL (w:bidi): יישור ונקודות יתהפכו ב-Word")
    if no_cs:
        log("WARN", f"{no_cs} קטעי עברית בלי גודל complex-script (szCs): ב-Word העברית תצא בגודל אחר")
    for i, t in enumerate(doc.tables):
        if any(has_hebrew(c.text) for row in t.rows for c in row.cells):
            if t._tbl.tblPr.find(qn("w:bidiVisual")) is None:
                log("WARN", f"טבלה {i + 1} בעברית בלי bidiVisual: העמודה הראשונה תהיה משמאל")
    load_sources(doc.core_properties.comments)
    return doc, texts


def load_sources(comments):
    try:
        meta = json.loads(comments or "{}")
        SOURCES.extend(meta.get("sources", []))
        SUPPLIED.extend(meta.get("supplied", []))
    except (ValueError, AttributeError):
        pass


def check_docx_kind(doc, texts, kind):
    """Type-specific structure checks on the Word source."""
    from docx.oxml.ns import qn  # noqa: F401
    full = "\n".join(texts)
    if kind == "cv":
        small = [(r.font.size.pt, r.text[:20]) for p in docx_paras(doc) for r in p.runs
                 if r.text.strip() and r.font.size is not None and r.font.size.pt < 10]
        for sz, t in small[:5]:
            log("FAIL", f"טקסט {sz:g}pt בקורות חיים (מינימום 10, גוף 10.5): '{t}'")
        for t in texts:
            t2 = t.strip()
            if t2.startswith("•"):
                first = t2.lstrip("• \u200f\u200e").split()[0] if t2.lstrip("• ").split() else ""
                en_verb = LTR_DOC and re.match(r"^(?:[A-Z][a-z]+ed|Built|Set|Taught|Led|Ran|Wrote|Made|Grew|Cut|Won|"
                                               r"Drove|Shipped|Owned)$", first)
                if not HEB_VERB.match(first) and not en_verb:
                    log("WARN", f"שורת הישג שלא נפתחת בפועל ('{first}'): '{t2[:40]}'")
    if kind == "quote" and re.search(r"אתר|דף נחיתה|אפליקציה|חנות", full):
        for need, label in (("נגישות", "נגישות (ת\"י 5568 והצהרת נגישות)"), ("פרטיות", "פרטיות (מדיניות והסכמה בטופס)"),
                            ("אחסון", "מי אחראי על אחסון ותחזוקה"), ("אחריות", "תקופת אחריות לתיקון תקלות")):
            if need not in full:
                log("FAIL", f"הצעה לפרויקט ווב בלי שורת {label}: מתמחר או כותב במפורש 'לא כלול'")
    if kind == "letter":
        for ph in SELF_INCRIM:
            if ph in full:
                log("FAIL", f"ניסוח מפליל במכתב: '{ph}'. כותבים עובדות, לא הודאה")
        numbered = [t for t in texts if re.match(r"^\s*\d+\.\s", t)]
        no_annex = [t for t in numbered if "נספח" not in t and re.search(r"\d|צילום|תמונה|אישור", t)]
        for t in no_annex:
            log("WARN", f"טענה עובדתית בלי הפניה לנספח: '{t.strip()[:50]}'")
        cited = []
        for m in re.finditer(r"נספח ([\u05d0-\u05ea])'", full):
            if m.group(1) not in cited:
                cited.append(m.group(1))
        if cited and cited != sorted(cited):
            log("FAIL", f"הנספחים לא ממוספרים לפי סדר האזכור הראשון: {' '.join(cited)}")
        if re.search(r"דוח|דו\"ח|קנס|תביעה|חוזה|הסכם|תלונה|ערעור", full):
            ck = os.path.splitext(ARGS.file)[0] + "-checklist.docx"
            if not os.path.exists(ck):
                log("FAIL", "מסמך משפטי בלי רשימת הגשה ללקוח (-checklist.docx) עם הסתייגות והפניה לעו\"ד")
            else:
                from docx import Document as _D
                ckt = "\n".join(p.text for p in _D(ck).paragraphs)
                if "לא ייעוץ משפטי" not in ckt or "עו\"ד" not in ckt:
                    log("FAIL", "ברשימת ההגשה אין הסתייגות ('זה לא ייעוץ משפטי') והפניה לעו\"ד")
                else:
                    log("PASS", "רשימת הגשה עם הסתייגות משפטית והפניה לעו\"ד")
        if re.search(r"דוח|דו\"ח|קנס", full) and "229" not in full:
            log("FAIL", "ערעור על דוח בלי שורת מועד ומקור (סעיף 229 לחסד\"פ / המועד שבדוח)")


def check_quote(doc, texts):
    full = "\n".join(texts)
    exempt = "עוסק פטור" in full
    items_ok, n_items, lines_sum = True, 0, 0.0
    totals = {}
    for t in doc.tables:
        rows = [[c.text.strip() for c in r.cells] for r in t.rows]
        if not rows or len(rows[0]) < 2:      # one-cell panels (goal, proof, packages) are not totals
            continue
        hdr = rows[0]
        if any("כמות" in h for h in hdr) and any("סה\"כ" in h for h in hdr):
            qi = next(i for i, h in enumerate(hdr) if "כמות" in h)
            ui = next(i for i, h in enumerate(hdr) if "מחיר" in h)
            li = max(i for i, h in enumerate(hdr) if "סה\"כ" in h)
            for r in rows[1:]:
                q, u, ln = num(r[qi]), num(r[ui]), num(r[li])
                if None in (q, u, ln):
                    continue
                n_items += 1
                lines_sum += ln
                if abs(q * u - ln) > 0.5:
                    items_ok = False
                    log("FAIL", f"שורה '{r[1].splitlines()[0][:30]}': {q:g} × {u:,.2f} = {q * u:,.2f}, אבל כתוב {ln:,.2f}")
        for r in rows:
            joined = " ".join(r)
            v = num(r[-1]) if r else None
            if v is None:
                continue
            if "לפני מע\"מ" in joined or re.search(r"^\s*סה\"כ\s*$", r[-2] if len(r) > 1 else ""):
                totals["sub"] = v
            elif "אחרי הנחה" in joined:
                totals["net"] = v
            elif "הנחה" in joined:
                totals["disc"] = abs(v)
            elif re.search(r"מע\"מ\s*\d", joined):
                totals["vat"] = v
                totals["rate"] = num(re.search(r"מע\"מ\s*(\d+(?:\.\d+)?)", joined).group(1))
            elif "לתשלום" in joined:
                totals["total"] = v
    if not n_items:
        log("FAIL", "לא נמצאה טבלת פריטים (כותרות: כמות / מחיר / סה\"כ). אי אפשר לבדוק חשבון")
        return
    if items_ok:
        log("PASS", f"{n_items} שורות פריטים: כמות × מחיר = סה\"כ בכל שורה")
    sub = totals.get("sub")
    if sub is None:
        log("FAIL", "אין שורת סה\"כ לפני מע\"מ / סה\"כ")
        return
    if abs(sub - lines_sum) > 0.5:
        log("FAIL", f"סכום השורות {lines_sum:,.2f} ≠ סה\"כ {sub:,.2f}")
    net = totals.get("net", sub - totals.get("disc", 0))
    if exempt:
        if "vat" in totals:
            log("FAIL", "עוסק פטור עם שורת מע\"מ: עוסק פטור לא גובה מע\"מ")
        expect_total = net
    else:
        if "vat" not in totals:
            log("FAIL", "אין שורת מע\"מ (ואין ציון 'עוסק פטור'). לקוח לא יודע אם המחיר כולל מע\"מ")
            return
        rate = totals["rate"]
        if rate != VAT_RATE:
            log("FAIL", f"שיעור מע\"מ {rate:g}% ולא {VAT_RATE}% (בתוקף מ-1.1.2025; אם השתנה, לעדכן VAT_RATE)")
        if abs(net * rate / 100 - totals["vat"]) > 1:
            log("FAIL", f"מע\"מ שגוי: {rate:g}% מ-{net:,.2f} = {net * rate / 100:,.2f}, כתוב {totals['vat']:,.2f}")
        else:
            log("PASS", f"מע\"מ {rate:g}% מחושב נכון: {totals['vat']:,.2f}")
        expect_total = net + totals["vat"]
    if "total" not in totals:
        log("FAIL", "אין שורת 'סה\"כ לתשלום'")
    elif abs(totals["total"] - expect_total) > 1:
        log("FAIL", f"סה\"כ לתשלום {totals['total']:,.2f}, אמור להיות {expect_total:,.2f}")
    else:
        log("PASS", f"סה\"כ לתשלום {totals['total']:,.2f} תואם")
    for need, label in (("תוקף", "תוקף ההצעה"), ("לא כלול", "מה לא כלול"), ("תשלום", "תנאי תשלום")):
        if need not in full:
            log("FAIL", f"חסר בהצעה: {label}")


def check_cv(texts, pages):
    if pages:
        if pages > 2:
            log("FAIL", f"קורות חיים של {pages} עמודים (מקסימום 2)")
        elif pages == 2:
            log("WARN", "קורות חיים של 2 עמודים: מתאים רק לניסיון של כ-10 שנים ומעלה")
        else:
            log("PASS", "קורות חיים בעמוד אחד")
    bullets_with_num = sum(1 for t in texts if re.search(r"\d", t) and len(t) > 40)
    if bullets_with_num < 2:
        log("FAIL", "פחות מ-2 שורות הישג עם מספר (תוצאה, היקף, אחוז)")
    if re.search(r"ת\"ז|תעודת זהות|מצב משפחתי|נשוי|נשואה|רווק", "\n".join(texts)):
        log("WARN", "פרט אישי שלא מקובל בקורות חיים בישראל (ת\"ז / מצב משפחתי)")


# ---------------------------------------------------------------- pptx
class Meter:
    """Measures text width with the real font (fontTools); falls back to 0.55em per char."""

    def __init__(self):
        self.fonts = {}
        try:
            from fontTools.ttLib import TTFont
            for bold in (False, True):
                f = os.path.join(FONTS_DIR, f"Heebo-{'Bold' if bold else 'Regular'}.ttf")
                if os.path.exists(f):
                    tt = TTFont(f)
                    self.fonts[bold] = (tt.getBestCmap(), tt["hmtx"].metrics, tt["head"].unitsPerEm,
                                        (tt["hhea"].ascent - tt["hhea"].descent + tt["hhea"].lineGap)
                                        / tt["head"].unitsPerEm)
        except ImportError:
            pass

    def missing(self, s):
        """Characters the design font cannot draw: they fall back to another font (wider, different look)."""
        f = self.fonts.get(False)
        if not f:
            return set()
        return {ch for ch in s if ord(ch) not in f[0] and ord(ch) > 0x20 and not 0x200b <= ord(ch) <= 0x206f}

    def width(self, s, size, bold):
        f = self.fonts.get(bold)
        if not f:
            return len(s) * 0.55 * size
        cmap, hmtx, upm, _ = f
        w = 0
        for ch in s:
            g = cmap.get(ord(ch))
            w += hmtx[g][0] if g in hmtx else (0 if 0x200b <= ord(ch) <= 0x206f else upm * 0.55)
        return w / upm * size

    def line_h(self, size, bold):
        # PowerPoint and LibreOffice set single line spacing at ~1.2 x size for text boxes (measured on Heebo
        # renders: 40pt headline -> 48pt line pitch), not the font's hhea height (1.47 for Heebo)
        return size * 1.2


def check_pptx(path, kind):
    from pptx import Presentation
    from pptx.util import Emu
    prs = Presentation(path)
    meter = Meter()
    texts, small, over, wordy, nonotes, nortl, orphans = [], [], [], [], [], 0, []
    n = len(prs.slides)
    for si, sl in enumerate(prs.slides, 1):
        words = 0
        for sh in sl.shapes:
            if not sh.has_text_frame:
                continue
            tf = sh.text_frame
            exempt = (sh.name or "").startswith("footer")
            avail_w = Emu(sh.width).pt - Emu(tf.margin_left or 91440).pt - Emu(tf.margin_right or 91440).pt
            need_h = Emu(tf.margin_top or 45720).pt + Emu(tf.margin_bottom or 45720).pt
            for p in tf.paragraphs:
                t = "".join(r.text for r in p.runs)
                texts.append(t)
                words += len(t.split())
                if has_hebrew(t) and p._p.pPr is not None and p._p.pPr.get("rtl") != "1":
                    nortl += 1
                sizes = [r.font.size.pt for r in p.runs if r.font.size is not None] or [18.0]
                size = max(sizes)
                bold = any(r.font.bold for r in p.runs)
                if not exempt:
                    for r in p.runs:
                        if r.text.strip() and (r.font.size is None or r.font.size.pt < ARGS.min_pt):
                            small.append((si, r.font.size.pt if r.font.size else None, r.text[:25]))
                # greedy word wrap with real metrics
                lines, cur, last_words = 1, 0.0, 0
                space = meter.width(" ", size, bold)
                for w in t.split():
                    ww = meter.width(w, size, bold)
                    if cur and cur + space + ww > avail_w:
                        lines += 1
                        cur, last_words = ww, 1
                    else:
                        cur += (space if cur else 0) + ww
                        last_words += 1
                if size >= 32 and lines > 1 and last_words == 1:
                    orphans.append((si, t[-25:]))
                ls = p.line_spacing if isinstance(p.line_spacing, float) else 1.0
                need_h += lines * meter.line_h(size, bold) * ls + (p.space_after.pt if p.space_after else 0)
            box_h = Emu(sh.height).pt
            if need_h > box_h * 1.08 and any(r.text.strip() for p in tf.paragraphs for r in p.runs):
                over.append((si, "".join(r.text for r in tf.paragraphs[0].runs)[:30], need_h, box_h))
        slide_text = " ".join(p.text for sh in sl.shapes if sh.has_text_frame for p in sh.text_frame.paragraphs)
        for ph in SLIDE_INSTRUCTIONS:
            if ph in slide_text:
                log("FAIL", f"שקף {si}: הוראת עבודה על השקף ('{ph}'). מקומה בהערות הדובר")
        heads = [p.text for sh in sl.shapes if sh.has_text_frame for p in sh.text_frame.paragraphs
                 if any(r.font.size is not None and r.font.size.pt >= 32 for r in p.runs)]
        for h in heads:
            if "[לאשר" in h:
                log("FAIL", f"שקף {si}: [לאשר] בכותרת ('{h[:40]}'). כותרת היא מסר; נתון חסר עובר לגוף השקף")
            if COMPETITOR_CLAIM.search(h) and "[לאשר" in slide_text:
                log("FAIL", f"שקף {si}: טענה על מתחרים בכותרת ('{h[:40]}') כשתאי ההשוואה לא נבדקו")
        if words > 45:
            wordy.append((si, words))
        if not (sl.has_notes_slide and sl.notes_slide.notes_text_frame.text.strip()):
            nonotes.append(si)
    miss = sorted({ch for t in texts for ch in meter.missing(t)})
    if miss:
        log("FAIL", f"תווים שאין בגופן Heebo (יוצגו בגופן חלופי ויחרגו מהמדידה): {' '.join(miss)}")
    for si, sz, t in small[:12]:
        log("FAIL", f"שקף {si}: טקסט {sz}pt (מינימום {ARGS.min_pt:g}): '{t}'")
    if not small:
        log("PASS", f"כל הטקסט בכל {n} השקפים ≥ {ARGS.min_pt:g}pt")
    for si, t, need, have in over:
        log("FAIL", f"שקף {si}: טקסט חורג מהתיבה ('{t}...'): צריך {need:.0f}pt גובה, יש {have:.0f}pt")
    if not over:
        log("PASS", "אין טקסט שחורג מהתיבה (נמדד במטריקות של הגופן)")
    for si, w in wordy:
        log("WARN", f"שקף {si}: {w} מילים. מצגת להצגה: עד כ-30-45")
    for si, t in orphans:
        log("WARN", f"שקף {si}: מילה יתומה בשורה האחרונה של הכותרת ('...{t}'). לקצר או לשבור אחרת")
    if nonotes:
        log("WARN", f"אין הערות דובר בשקפים: {nonotes}")
    if nortl:
        log("FAIL", f"{nortl} פסקאות בעברית בלי rtl=\"1\"")
    if kind == "pitch":
        if n > 15:
            log("FAIL", f"מצגת משקיעים של {n} שקפים (מקסימום 15, יעד 10-12)")
        elif n < 8:
            log("WARN", f"רק {n} שקפים: חסרים כנראה חלקים (בעיה, פתרון, שוק, מודל, תנועה, צוות, גיוס)")
    load_sources(prs.core_properties.comments)
    check_text(texts, kind)


# ---------------------------------------------------------------- pdf
def render_pdf(path):
    out = tempfile.mkdtemp()
    prof = tempfile.mkdtemp()
    subprocess.run(["soffice", f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", "pdf",
                    "--outdir", out, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    g = glob.glob(os.path.join(out, "*.pdf"))
    return g[0] if g else None


_LTR_TOKEN = re.compile(r"\d[\d/:]*–\x00[\u05d0-\u05ea]+|[$€]?[A-Za-z0-9@](?:[A-Za-z0-9@.,:/+#%&'_\-–]*[A-Za-z0-9%+#.])?,?")


def reading_order(visual):
    """Turn a line's glyphs in VISUAL left-to-right order back into Hebrew reading order. Latin/number tokens
    are read left-to-right; consecutive tokens joined by single spaces form one LTR unit unless a token ends a
    sentence (. : ; ! ?). Everything else is read right-to-left."""
    # an LTR-isolated range that ends in a Hebrew word ("2025–היום") is one left-to-right unit
    visual = re.sub(r"(\d[\d/:]*–)(םויה|םויכ|הווהה?)", lambda m: m.group(1) + "\x00" + m.group(2)[::-1], visual)
    units, pos, cur, last_end = [], 0, None, -1
    for m in _LTR_TOKEN.finditer(visual):
        gap = visual[last_end:m.start()] if cur is not None else None
        if cur is not None and gap == " " and not cur[-1] in ".:;!?":
            cur += " " + m.group(0)
        else:
            if cur is not None:
                units.append(cur)
                units.extend(visual[last_end:m.start()])
            else:
                units.extend(visual[pos:m.start()])
            cur = m.group(0)
        last_end = m.end()
    if cur is not None:
        units.append(cur)
        units.extend(visual[last_end:])
    else:
        units.extend(visual)
    return "".join(reversed(units)).replace("\x00", "")


def check_visual(pdf, source_texts):
    """Every rendered line, read back in Hebrew order, must be found in the source text. A bidi bug changes
    the reading order ("ו-3 ... Stripe.") and the line no longer matches."""
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
        except ImportError:
            log("WARN", "pymupdf לא מותקן: סדר הקריאה ברינדור לא נבדק (pip install pymupdf)")
            return
    src = norm("".join(source_texts))
    bad, checked = [], 0
    doc = pymupdf.open(pdf)
    for pi, page in enumerate(doc, 1):
        rows = {}
        for b in page.get_text("rawdict")["blocks"]:
            for ln in b.get("lines", []):
                for sp in ln["spans"]:
                    for c in sp["chars"]:
                        y = round((c["bbox"][1] + c["bbox"][3]) / 2 / 2.5)
                        rows.setdefault(y, []).append((c["bbox"][0], c["bbox"][2], c["c"], sp["size"]))
        for y in sorted(rows):
            chars = sorted(rows[y])
            # split the visual row into segments at wide gaps (table columns, tab stops)
            segs, cur, prev_x1 = [], [], None
            for x0, x1, ch, size in chars:
                if prev_x1 is not None and x0 - prev_x1 > size * 0.65:   # table cells sit ~0.7em apart
                    segs.append(cur)
                    cur = []
                cur.append(ch)
                prev_x1 = x1
            segs.append(cur)
            for seg in segs:
                vis = "".join(seg).replace("\u00a0", " ").replace("\u2060", "")
                if has_hebrew(vis) and re.search(r"(?:^|\s)[ובכלמהש]{1,3}-$", reading_order(vis).strip()):
                    bad.append((pi, "שורה שנגמרת בקידומת ומקף: " + reading_order(vis).strip()[-30:]))
                if not has_hebrew(vis) or not re.search(r"[A-Za-z0-9]", vis):
                    continue
                checked += 1
                ro = norm(reading_order(vis))
                if ro and ro not in src:
                    bad.append((pi, reading_order(vis).strip()))

    for pi, t in bad[:8]:
        hint = " (טווח שנשבר בין שורות: בתא צר כותבים 'עד 4' במקום '1–4')" if re.search(r"\d\s*–\)?$|\(–\d", t) else ""
        log("FAIL", f"סדר קריאה שבור ברינדור (עמוד {pi}): '{t[:70]}'{hint}")
    dirs = {"ltr": [], "rtl": []}
    tok = r"(?:\d{1,2}/)?(?:19|20)\d\d|\d{1,2}:\d\d"
    for pi, page in enumerate(doc, 1):
        for line in page.get_text("rawdict")["blocks"]:
            pass
        rows = {}
        for b in page.get_text("rawdict")["blocks"]:
            for ln in b.get("lines", []):
                for sp in ln["spans"]:
                    for c in sp["chars"]:
                        rows.setdefault(round((c["bbox"][1] + c["bbox"][3]) / 5), []).append((c["bbox"][0], c["c"]))
        for y in sorted(rows):
            vis = "".join(c for _, c in sorted(rows[y]))
            for m in re.finditer(rf"({tok})\s*[–-]\s*({tok})", vis):
                key = lambda x: (int(x.split("/")[-1]) * 100 + (int(x.split("/")[0]) if "/" in x else 0)
                                 if ":" not in x else int(x.replace(":", "")))
                a, b = key(m.group(1)), key(m.group(2))
                if a != b:
                    dirs["ltr" if a < b else "rtl"].append((pi, m.group(0)))
            for m in re.finditer(rf"({tok})\s*[–-]\s*םויה", vis):
                dirs["ltr"].append((pi, m.group(0)))
            for m in re.finditer(rf"םויה\s*[–-]\s*({tok})", vis):
                dirs["rtl"].append((pi, "היום–" + m.group(1)))
    if dirs["ltr"] and dirs["rtl"]:
        log("FAIL", f"טווחים בשני כיוונים במסמך: {len(dirs['ltr'])} משמאל לימין, {len(dirs['rtl'])} מימין לשמאל, "
                    f"למשל '{dirs['rtl'][0][1]}' (עמוד {dirs['rtl'][0][0]})")
    elif dirs["rtl"]:
        log("FAIL", f"טווחים מוצגים מימין לשמאל ({dirs['rtl'][0][1]}), בניגוד למוסכמה (משמאל לימין)")
    elif dirs["ltr"]:
        log("PASS", f"כל {len(dirs['ltr'])} הטווחים מוצגים באותו כיוון (משמאל לימין)")
    if checked and not bad:
        log("PASS", f"סדר הקריאה תקין ב-{checked} שורות מעורבות (עברית + לועזית/מספרים)")


def page_fill(pdf):
    """Fraction of the last page's height that holds text (top margin to last line)."""
    try:
        import pymupdf
    except ImportError:
        return None
    doc = pymupdf.open(pdf)
    pg = doc[-1]
    ys = [b[3] for b in pg.get_text("blocks") if b[4].strip() and b[3] < pg.rect.height * 0.94]
    return (max(ys) / pg.rect.height) if ys else 0.0


def check_pdf(pdf):
    pages = None
    try:
        info = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout
        pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
        fonts = subprocess.run(["pdffonts", pdf], capture_output=True, text=True).stdout.splitlines()[2:]
        bad = [l.split()[0] for l in fonts if len(l.split()) >= 6 and l.split()[-5] == "no"]
        if bad:
            log("FAIL", f"גופנים לא מוטמעים ב-PDF: {bad[:4]}")
        fb = sorted({l.split()[0].split("+")[-1] for l in fonts if re.search(r"DejaVu|Liberation", l)})
        if fb:
            log("WARN", f"גופן חלופי ב-PDF ({', '.join(fb)}): גופן העיצוב לא מותקן? bash templates/documents/install_fonts.sh")
    except (FileNotFoundError, AttributeError):
        log("WARN", "pdfinfo/pdffonts לא זמינים: לא נבדקו עמודים וגופנים")
    return pages


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--type", default=None)
    ap.add_argument("--pdf")
    ap.add_argument("--max-pages", type=int)
    ap.add_argument("--min-pt", type=float, default=24)
    ap.add_argument("--final", action="store_true")
    ARGS = ap.parse_args()
    ext = ARGS.file.lower().rsplit(".", 1)[-1]
    kind = ARGS.type
    pdf = ARGS.pdf
    if ext in ("docx", "pptx") and not pdf:
        pdf = render_pdf(ARGS.file)
    pages = check_pdf(pdf) if pdf else None
    if ext == "docx":
        doc, texts = check_docx(ARGS.file)
        full = "\n".join(texts)
        kind = kind or ("quote" if "הצעת מחיר" in full else "doc")
        check_text(texts, kind)
        check_docx_kind(doc, texts, kind)
        if kind == "quote":
            check_quote(doc, texts)
        if kind == "cv":
            check_cv(texts, pages)
        if pdf and not LTR_DOC:          # an English (LTR) document: Hebrew reading-order rules don't apply
            check_visual(pdf, texts)
            fill = page_fill(pdf)
            if fill is not None and pages and pages > 1 and fill < 0.4:
                log("FAIL", f"העמוד האחרון מלא רק {fill:.0%}: לאזן (לדחוס או להעביר תוכן), לא להשאיר עמוד חצי ריק")
            if fill is not None and kind == "cv" and pages == 1 and fill < 0.8:
                log("WARN", f"קורות החיים ממלאים {fill:.0%} מהעמוד: להגדיל גופן/מרווחים (doc_build עושה fit אוטומטי)")
    elif ext == "pptx":
        check_pptx(ARGS.file, kind or "deck")
        if pdf:
            from pptx import Presentation
            check_visual(pdf, [p.text for sl in Presentation(ARGS.file).slides for sh in sl.shapes
                               if sh.has_text_frame for p in sh.text_frame.paragraphs])
    else:
        sys.exit("qa_text.py works on the SOURCE file (.docx / .pptx). For a PDF only, run qa_doc.sh.")
    if ARGS.max_pages and pages and pages > ARGS.max_pages:
        log("FAIL", f"{pages} עמודים, מעל המגבלה ({ARGS.max_pages})")
    print(f"=== qa_text: {ARGS.file}  (type={kind}, pages={pages}) ===")
    seen = {}
    for l, m in results:  # collapse repeats: "message (x12)"
        seen[(l, m)] = seen.get((l, m), 0) + 1
    for lvl in ("FAIL", "WARN", "PASS"):
        for (l, m), c in seen.items():
            if l == lvl:
                print(f"{lvl:4}  {m}" + (f"  (x{c})" if c > 1 else ""))
    nf = sum(1 for l, _ in results if l == "FAIL")
    print(f"--- {nf} FAIL, {sum(1 for l, _ in results if l == 'WARN')} WARN")
    sys.exit(1 if nf else 0)


if __name__ == "__main__":
    main()
