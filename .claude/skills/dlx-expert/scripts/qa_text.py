#!/usr/bin/env python3
"""qa_text.py - content QA for documents and decks. Exits 1 on any FAIL (so it can gate a delivery).

Usage:
  python3 qa_text.py FILE [--type cv|quote|letter|pitch|deck|doc] [--pdf FILE.pdf] [--max-pages N]
                          [--min-pt 24] [--final]

FILE: .docx or .pptx (the source: QA reads structure, not pixels). Pass --pdf with the rendered PDF (or let
the script render it with LibreOffice) for page count and font embedding.

Checks (FAIL unless marked WARN):
  all     template leftovers ({{x}}, TODO, Lorem ipsum, <<x>>); placeholders [לאשר]/[להשלים] (WARN, FAIL with
          --final = "this is going to the recipient now"); bidi bugs that render wrong (C++ -> ++C, B.Sc. ->
          .B.Sc, +972 jumping); year ranges mixing hyphen and en dash (reading order flips); AI clichés (WARN)
  docx    Hebrew paragraph without RTL (w:bidi); Hebrew run without complex-script size (WARN); table with Hebrew
          that is not visually RTL (WARN)
  quote   every line qty x unit = line total; subtotal = sum; VAT line = rate x net; total = net + VAT;
          VAT rate = 18% (Israel since 1.1.2025, re-verify yearly); exempt dealer (עוסק פטור) must NOT charge VAT;
          licensed dealer must show VAT; must state validity, what is not included, payment terms
  cv      pages <= 2 (FAIL), 2 pages = WARN for under ~10 years experience; at least one number in bullets
  pptx    every run >= --min-pt (default 24; shapes named footer-* exempt); text overflowing its box (measured
          with the real font metrics); > 45 words on a slide (WARN); missing speaker notes (WARN);
          pitch: > 15 slides FAIL, < 8 WARN
  pdf     fonts not embedded; fallback fonts (DejaVu/Liberation) instead of the design fonts (WARN)
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
from hebrew_text import HARD_LEFTOVER, HEB, PLACEHOLDER, bidi_problems, has_hebrew  # noqa: E402

VAT_RATE = 18  # Israel, from 1.1.2025 (רשות המסים). Verified 11/2026 - re-check every January.
AI_CLICHES = ["בעולם המשתנה", "חשוב לציין", "לסיכום ניתן לומר", "הנני לפנות", "בעידן של היום", "מהווה פתרון",
              "פתרון מקצה לקצה", "חוויה בלתי נשכחת", "ללא ספק", "יתרה מזאת"]
FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", "documents", "fonts")

results = []


def log(level, msg):
    results.append((level, msg))


def num(s):
    s = s.replace("‎", "").replace("‏", "").replace(",", "")
    m = re.findall(r"-?\d+(?:\.\d+)?", s)
    return float(m[0]) if m else None


# ---------------------------------------------------------------- generic text checks
def check_text(paras):
    full = "\n".join(paras)
    for m in HARD_LEFTOVER.finditer(full):
        log("FAIL", f"שארית תבנית: '{m.group(0)}'")
    ph = PLACEHOLDER.findall(full)
    if ph:
        lvl = "FAIL" if ARGS.final else "WARN"
        log(lvl, f"{len(ph)} מקומות לאישור/השלמה (מסומנים בצהוב): " + ", ".join(sorted(set(ph))[:6]))
    hy, en = 0, 0
    for p in paras:
        for kind, snip in bidi_problems(p):
            log("WARN" if kind.startswith("טווח") else "FAIL", f"כיווניות: {kind}: '{snip}'")
        if has_hebrew(p):
            hy += len(re.findall(r"(?:19|20)\d\d-(?:19|20)\d\d", p))
            en += len(re.findall(r"(?:19|20)\d\d‎?[–—]‎?(?:19|20)\d\d", p))
    if hy and en:
        log("FAIL", f"טווחי שנים מעורבים: {hy} עם מקף ו-{en} עם קו מפריד. סדר הקריאה מתהפך בין שורות")
    for c in AI_CLICHES:
        if c in full:
            log("WARN", f"ביטוי שחוק/AI: '{c}'")


# ---------------------------------------------------------------- docx
def docx_paras(doc):
    out = [p for p in doc.paragraphs]
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
    if no_rtl:
        log("FAIL", f"{no_rtl} פסקאות בעברית בלי כיוון RTL (w:bidi): יישור ונקודות יתהפכו ב-Word")
    if no_cs:
        log("WARN", f"{no_cs} קטעי עברית בלי גודל complex-script (szCs): ב-Word העברית תצא בגודל אחר")
    for i, t in enumerate(doc.tables):
        if any(has_hebrew(c.text) for row in t.rows for c in row.cells):
            if t._tbl.tblPr.find(qn("w:bidiVisual")) is None:
                log("WARN", f"טבלה {i + 1} בעברית בלי bidiVisual: העמודה הראשונה תהיה משמאל")
    check_text(texts)
    return doc, texts


def check_quote(doc, texts):
    full = "\n".join(texts)
    exempt = "עוסק פטור" in full
    items_ok, n_items, lines_sum = True, 0, 0.0
    totals = {}
    for t in doc.tables:
        rows = [[c.text.strip() for c in r.cells] for r in t.rows]
        if not rows:
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

    def width(self, s, size, bold):
        f = self.fonts.get(bold)
        if not f:
            return len(s) * 0.55 * size
        cmap, hmtx, upm, _ = f
        w = 0
        for ch in s:
            g = cmap.get(ord(ch))
            w += hmtx[g][0] if g in hmtx else (0 if ord(ch) in (0x200e, 0x200f, 0x202a, 0x202c) else upm * 0.55)
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
        if words > 45:
            wordy.append((si, words))
        if not (sl.has_notes_slide and sl.notes_slide.notes_text_frame.text.strip()):
            nonotes.append(si)
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
    check_text(texts)


# ---------------------------------------------------------------- pdf
def render_pdf(path):
    out = tempfile.mkdtemp()
    prof = tempfile.mkdtemp()
    subprocess.run(["soffice", f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", "pdf",
                    "--outdir", out, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    g = glob.glob(os.path.join(out, "*.pdf"))
    return g[0] if g else None


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
        if kind == "quote":
            check_quote(doc, texts)
        if kind == "cv":
            check_cv(texts, pages)
    elif ext == "pptx":
        check_pptx(ARGS.file, kind or "deck")
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
