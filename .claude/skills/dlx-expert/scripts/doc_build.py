#!/usr/bin/env python3
"""doc_build.py - professional RTL Hebrew Word documents from a JSON spec, rendered to PDF.

Usage:
  python3 doc_build.py spec.json out.docx|out_dir/ [--pdf] [--safe-fonts]

Spec "type": cv | quote | letter   (examples: templates/documents/examples/*.json)
  --pdf          also render out.pdf next to the docx with LibreOffice (needs soffice + the fonts installed:
                 bash templates/documents/install_fonts.sh) AND fit it: a CV scales up to fill its page (body
                 never under 10.5pt), other documents never end on a half-empty page (needs pymupdf)
  out_dir/       a directory instead of a file name = professional file name from the spec
                 (הצעת-מחיר-<מס'>-<לקוח>-<עסק>, קורות-חיים-<שם>, <הנדון>-<שולח>)
  spec "sources": [{"claim": "...", "source": "..."}] is stored in the file; qa_text.py accepts those claims
  --safe-fonts   use Arial everywhere (opens identically on any Windows/Mac Word without installing fonts;
                 use when the client will EDIT the .docx. The PDF is the main deliverable either way)

Design system: Heebo (headings) + Assistant (body), A4, one brand colour + dark ink + muted grey,
8pt spacing grid. Every paragraph is RTL (w:bidi), every run carries complex-script size/bold/font
(Word uses szCs/bCs/cs for Hebrew - setting only sz is the #1 reason Hebrew comes out the wrong size),
tables are visually RTL (w:bidiVisual), and all text goes through hebrew_text.bidi_fix().
Placeholders [לאשר ...] / [להשלים ...] are highlighted in amber so nobody sends them by accident.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hebrew_text import bidi_fix, has_hebrew, ils, split_rich  # noqa: E402

try:
    from docx import Document
    from docx.enum.section import WD_SECTION  # noqa: F401
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT  # noqa: F401
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor
except ImportError:
    sys.exit("python-docx missing: pip install python-docx")

# ---------------------------------------------------------------- design tokens
FONT_HEAD, FONT_BODY = "Heebo", "Assistant"
INK, MUTED, RULE, PANEL = "1B1F24", "5B6470", "D5DAE1", "F3F5F8"
AMBER_BG = "FFE7A3"  # placeholder highlight
BRAND = "1F4E79"
SCALE = 1.0          # set by the fit loop in main(): grows/shrinks every size and gap together
RTL = True           # False for the English CV version (spec "lang": "en")


def rgb(h):
    return RGBColor.from_string(h.upper())


# ---------------------------------------------------------------- low-level RTL helpers
def _pPr_bidi(p):
    pPr = p._p.get_or_add_pPr()
    if pPr.find(qn("w:bidi")) is None:
        el = OxmlElement("w:bidi")
        pPr.insert_element_before(el, "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
                                  "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
                                  "w:textDirection", "w:textAlignment", "w:textboxTightWrap",
                                  "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")


def style_run(run, size=10.5, bold=False, color=INK, font=None, highlight=False, rtl=None):
    font = font or FONT_BODY
    size = round(size * SCALE * 2) / 2
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = rgb(color)
    rPr = run._r.get_or_add_rPr()
    rf = rPr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rPr.insert(0, rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), font)
    # complex-script twins (Hebrew uses these)
    for tag, val in (("w:bCs", bold), ):
        el = rPr.find(qn(tag))
        if val and el is None:
            el = OxmlElement(tag)
            b = rPr.find(qn("w:b"))
            (b.addnext(el) if b is not None else rPr.append(el))
    szcs = rPr.find(qn("w:szCs"))
    if szcs is None:
        szcs = OxmlElement("w:szCs")
        sz = rPr.find(qn("w:sz"))
        (sz.addnext(szcs) if sz is not None else rPr.append(szcs))
    szcs.set(qn("w:val"), str(int(round(size * 2))))
    if (has_hebrew(run.text) if rtl is None else rtl):
        if rPr.find(qn("w:rtl")) is None:
            rPr.append(OxmlElement("w:rtl"))
    lang = rPr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rPr.append(lang)
    lang.set(qn("w:val"), "en-US")
    lang.set(qn("w:bidi"), "he-IL")
    if highlight:
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), AMBER_BG)
        rPr.append(shd)
    return run


def para(container, text="", size=10.5, bold=False, color=INK, font=None, align=None, before=0, after=4,
         line=1.15, keep_next=False):
    p = container.add_paragraph()
    if RTL:
        _pPr_bidi(p)
    pf = p.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(before * SCALE), Pt(after * SCALE), line
    if keep_next:
        pf.keep_with_next = True
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == "end":  # visual left in an RTL paragraph
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    elif align == "justify":
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if text:
        add_rich(p, text, size=size, bold=bold, color=color, font=font)
    return p


def no_runt(text):
    """Bind the last two words with a no-break space so a paragraph never ends on a one-word line."""
    if len(text) < 60:
        return text
    i = text.rstrip().rfind(" ")
    return text[:i] + "\u00a0" + text[i + 1:] if i > 0 else text


_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9.,/@+#&'_\-\u200e%]*(?:[ ][A-Za-z0-9][A-Za-z0-9.,/@+#&'_\-\u200e%]*)*")


def script_chunks(seg):
    """Split text at script boundaries like Word does: Latin runs (no w:rtl) vs Hebrew/neutral runs (w:rtl).
    Keeps Word's own run structure (w:rtl only on Hebrew text), so Word and LibreOffice resolve neutrals the
    same way. Sentence punctuation at the end of a Latin run stays with the Hebrew text."""
    out, pos = [], 0
    for m in _LATIN_RUN.finditer(seg):
        a, b = m.start(), m.end()
        tok = seg[a:b]
        while tok and tok[-1] in ".,:;" and not re.search(r"[A-Za-z]\.[A-Za-z]+\.$", tok):
            tok, b = tok[:-1], b - 1
        if a > pos:
            out.append((seg[pos:a], True))
        out.append((tok, False))
        pos = b
    if pos < len(seg):
        out.append((seg[pos:], True))
    return [(t, r) for t, r in out if t]


def add_rich(p, text, size=10.5, bold=False, color=INK, font=None):
    for seg, b, ph in split_rich(bidi_fix(no_runt(text))):
        for chunk, rtl in (script_chunks(seg) if has_hebrew(text) else [(seg, False)]):
            style_run(p.add_run(chunk), size=size, bold=bold or b, color=color, font=font, highlight=ph,
                      rtl=rtl and has_hebrew(text))
    return p


def border(p, side="bottom", color=BRAND, sz=8, space=2):
    pPr = p._p.get_or_add_pPr()
    bdr = pPr.find(qn("w:pBdr"))
    if bdr is None:
        bdr = OxmlElement("w:pBdr")
        pPr.insert_element_before(bdr, "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
                                  "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
                                  "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
                                  "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
                                  "w:textDirection", "w:textAlignment", "w:outlineLvl", "w:rPr")
    el = OxmlElement(f"w:{side}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(sz))
    el.set(qn("w:space"), str(space))
    el.set(qn("w:color"), color)
    bdr.append(el)


def table_rtl(t):
    tblPr = t._tbl.tblPr
    el = OxmlElement("w:bidiVisual")
    tblPr.insert_element_before(el, "w:tblStyleRowBandSize", "w:tblStyleColBandSize", "w:tblW", "w:jc",
                                "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout",
                                "w:tblCellMar", "w:tblLook")


def table_borders(t, color=RULE, inside_h=True, outer=False):
    tblPr = t._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{side}")
        on = (side == "insideH" and inside_h) or (outer and side in ("top", "bottom"))
        el.set(qn("w:val"), "single" if on else "nil")
        if on:
            el.set(qn("w:sz"), "4")
            el.set(qn("w:color"), color)
        b.append(el)
    tblPr.append(b)


def rows_keep(t, header=True):
    """Rows never split across pages (w:cantSplit); the header row repeats on a new page (w:tblHeader)."""
    for i, row in enumerate(t.rows):
        trPr = row._tr.get_or_add_trPr()
        trPr.append(OxmlElement("w:cantSplit"))
        if header and i == 0:
            trPr.append(OxmlElement("w:tblHeader"))


def cell_fill(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tcPr.append(shd)


def cell_margins(t, top=60, bottom=60, start=100, end=100):
    tblPr = t._tbl.tblPr
    m = OxmlElement("w:tblCellMar")
    for side, v in (("top", top), ("bottom", bottom), ("right", start), ("left", end)):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:w"), str(v))
        el.set(qn("w:type"), "dxa")
        m.append(el)
    tblPr.append(m)


def cell_text(cell, text, size=10, bold=False, color=INK, font=None, align=None, after=0):
    cell.paragraphs[0]._p.getparent().remove(cell.paragraphs[0]._p)
    lines = text if isinstance(text, list) else [text]
    for ln in lines:
        para(cell, ln, size=size, bold=bold, color=color, font=font, align=align, after=after)
    return cell


def col_widths(t, widths_cm):
    """Fixed column widths. LibreOffice reads w:tblGrid, Word reads tcW - set both, plus tblW and fixed layout."""
    t.autofit = False
    tbl = t._tbl
    grid = tbl.tblGrid
    for i, gc in enumerate(grid.findall(qn("w:gridCol"))):
        gc.set(qn("w:w"), str(int(widths_cm[i] * 567)))
    tblPr = tbl.tblPr
    tw = tblPr.find(qn("w:tblW"))
    if tw is None:
        tw = OxmlElement("w:tblW")
        tblPr.append(tw)
    tw.set(qn("w:w"), str(int(sum(widths_cm) * 567)))
    tw.set(qn("w:type"), "dxa")
    lay = OxmlElement("w:tblLayout")
    lay.set(qn("w:type"), "fixed")
    tblPr.append(lay)
    for row in t.rows:
        for i, w in enumerate(widths_cm):
            row.cells[i].width = Cm(w)


def new_doc(margins_cm=(2.0, 2.0, 2.0, 2.0)):
    d = Document()
    s = d.sections[0]
    s.page_height, s.page_width = Cm(29.7), Cm(21.0)
    s.top_margin, s.bottom_margin, s.right_margin, s.left_margin = [Cm(x) for x in margins_cm]
    if RTL:
        s._sectPr.append(OxmlElement("w:bidi"))
    # Normal style: RTL + fonts + cs size, so empty paragraphs and table cells inherit them too
    st = d.styles["Normal"]
    st.font.name, st.font.size = FONT_BODY, Pt(10.5)
    rPr = st.element.get_or_add_rPr()
    rf = rPr.find(qn("w:rFonts"))
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), FONT_BODY)
    szcs = OxmlElement("w:szCs")
    szcs.set(qn("w:val"), "21")
    rPr.append(szcs)
    if RTL:
        st.element.get_or_add_pPr().append(OxmlElement("w:bidi"))
    d.core_properties.language = "he-IL" if RTL else "en-US"
    return d


def footer_note(d, text, color=MUTED):
    f = d.sections[0].footer
    p = f.paragraphs[0]
    _pPr_bidi(p)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_rich(p, text, size=8, color=color)


def section_title(d, text, brand, size=11.5, before=10):
    p = para(d, text, size=size, bold=True, color=brand, font=FONT_HEAD, before=before, after=4, keep_next=True)
    border(p, "bottom", color=brand, sz=6, space=1)
    return p


TEXT_W_CV = 21.0 - 2 * 1.7


def bullets(d, items, brand, size=10.5, after=1.5, indent=0.4, keep=True):
    for k, ln in enumerate(items):
        bp = para(d, "", size=size, after=after, line=1.2, keep_next=keep and k < len(items) - 1)
        if RTL:
            bp.paragraph_format.right_indent = Cm(indent)   # RTL: "right" is the start side
        else:
            bp.paragraph_format.left_indent = Cm(indent)
        bp.paragraph_format.first_line_indent = Cm(-indent)
        style_run(bp.add_run("•  "), size=size, color=brand, bold=True)
        add_rich(bp, ln, size=size)


def set_sources(d, spec):
    """Store the spec's sources and the facts the CLIENT supplied in the file, so qa_text.py can tell a sourced
    claim or a supplied phone/address from an invented one."""
    meta = {k: spec[k] for k in ("sources", "supplied") if spec.get(k)}
    if meta:
        d.core_properties.comments = json.dumps(meta, ensure_ascii=False)


DEFAULT_CANCEL = ("ביטול: כל צד יכול לבטל בהודעה בכתב. משלמים על אבני הדרך שהושלמו ועל העבודה שבוצעה עד יום "
                  "הביטול, ומה שנמסר עד אז שייך לכם. ביטול לפני תחילת העבודה: המקדמה מוחזרת במלואה.")
LEGAL_DISCLAIMER = ("זה לא ייעוץ משפטי. המכתב הוא טיוטה שהוכנה לפי המידע שמסרת. לפני הגשה, ובמיוחד כשיש סכום גבוה, "
                    "נקודות, או כשהבקשה נדחית ושוקלים בקשה להישפט, כדאי להתייעץ עם עו\"ד בתחום (או לפנות לסיוע "
                    "המשפטי של משרד המשפטים אם יש זכאות).")


# ---------------------------------------------------------------- CV (1 page, ATS-safe: single column, no tables)
def build_cv(spec, out):
    """Single column; dates sit on the org line in the text flow (no tab stops, so ATS parsers keep role, org
    and dates together); body 10.5pt minimum; the fit loop in main() scales it up to fill the page."""
    brand = spec.get("brand", {}).get("color", BRAND)
    if spec.get("tech") and not any(re.search(r"github|linkedin", c, re.I) for c in spec["contact"]):
        sys.exit("CV for a tech role: GitHub and/or LinkedIn links are required inputs. Ask the client first.")
    d = new_doc(margins_cm=(1.5, 1.4, 1.7, 1.7))
    para(d, spec["name"], size=24, bold=True, color=INK, font=FONT_HEAD, after=0, line=1.0)
    para(d, spec["title"], size=13, bold=True, color=brand, font=FONT_HEAD, after=3)
    p = para(d, " · ".join(spec["contact"]), size=10, color=MUTED, after=6)
    border(p, "bottom", color=RULE, sz=4, space=4)
    if spec.get("summary"):
        para(d, spec["summary"], size=11, color=INK, before=4, after=2, line=1.25)
    for sec in spec["sections"]:
        section_title(d, sec["title"], brand, size=12.5)
        for it in sec.get("items", []):
            para(d, f"**{it['role']}**", size=11, color=INK, before=4, after=0, keep_next=True)
            meta = " · ".join(x for x in (it.get("org"), it.get("dates"), it.get("location")) if x)
            if meta:
                para(d, meta, size=10.5, color=MUTED, after=1.5, keep_next=bool(it.get("bullets") or it.get("sub")))
            if it.get("sub"):
                para(d, it["sub"], size=10.5, color=INK, after=1.5, keep_next=bool(it.get("bullets")))
            bullets(d, it.get("bullets", []), brand, size=10.5, indent=0.35)
        for ln in sec.get("lines", []):
            lp = para(d, "", size=10.5, after=2, line=1.2)
            if ln.get("label"):
                style_run(lp.add_run(bidi_fix(ln["label"]) + ": "), size=10.5, bold=True, color=INK)
            add_rich(lp, ln["text"], size=10.5)
        if sec.get("text"):
            para(d, sec["text"], size=10.5, after=2)
    set_sources(d, spec)
    d.save(out)


# ---------------------------------------------------------------- Price quote
def quote_totals(spec):
    rows = []
    for it in spec["items"]:
        line = round(it["qty"] * it["unit_price"], 2)
        rows.append((it, line))
    sub = round(sum(r[1] for r in rows), 2)
    disc = round(spec.get("discount", {}).get("amount", 0), 2)
    net = round(sub - disc, 2)
    exempt = spec["dealer"].get("kind") == "exempt"
    rate = 0 if exempt else spec.get("vat_rate", 18)
    vat = round(net * rate / 100, 2)
    return rows, sub, disc, net, rate, vat, round(net + vat, 2), exempt


def panel(d, label, lines, brand, size=10.5):
    """A shaded one-cell box with a small label: used for the measurable goal and the proof slots."""
    t = d.add_table(rows=1, cols=1)
    table_rtl(t)
    table_borders(t, inside_h=False)
    cell_margins(t, top=90, bottom=90, start=160, end=160)
    col_widths(t, [17.4])
    c = t.rows[0].cells[0]
    cell_fill(c, PANEL)
    cell_text(c, label, size=9.5, bold=True, color=brand)
    for ln in lines:
        para(c, ln, size=size, after=1, line=1.2)
    para(d, "", after=2)


def build_quote(spec, out):
    """Sections: header, parties, title + value, measurable goal, proof slots, line items, totals, accessibility &
    privacy (priced or explicitly excluded), not included, timeline, payment, warranty & hosting, terms,
    acceptance. Every web quote must answer accessibility, privacy, hosting and bug warranty (qa_text.py)."""
    brand = spec.get("brand", {}).get("color", BRAND)
    dl, cl = spec["dealer"], spec["client"]
    d = new_doc(margins_cm=(1.6, 1.8, 1.8, 1.8))
    rows, sub, disc, net, rate, vat, total, exempt = quote_totals(spec)

    t = d.add_table(rows=1, cols=2)
    table_rtl(t)
    table_borders(t, inside_h=False)
    col_widths(t, [10.4, 7.0])
    c0, c1 = t.rows[0].cells
    cell_text(c0, dl["name"], size=20, bold=True, color=brand, font=FONT_HEAD)
    para(c0, dl.get("tagline", ""), size=10, color=MUTED, after=0)
    cell_text(c1, "הצעת מחיר", size=20, bold=True, color=INK, font=FONT_HEAD, align="end")
    para(c1, f"מס' {spec['number']}  ·  {spec['date']}", size=10, color=MUTED, align="end", after=0)
    para(c1, f"בתוקף עד {spec['valid_until']}", size=10, color=MUTED, align="end", after=0)
    p = para(d, "", after=8)
    border(p, "bottom", color=brand, sz=12, space=1)

    t = d.add_table(rows=1, cols=2)
    table_rtl(t)
    table_borders(t, inside_h=False)
    cell_margins(t, top=80, bottom=80, start=140, end=140)
    col_widths(t, [8.7, 8.7])
    a, b = t.rows[0].cells
    cell_fill(a, PANEL)
    cell_fill(b, PANEL)
    kind = "עוסק פטור" if exempt else ("עוסק מורשה" if dl.get("kind") == "licensed" else "חברה בע\"מ")
    cell_text(a, "מאת", size=9, bold=True, color=MUTED)
    for ln in [f"**{dl['name']}**", f"{kind} {dl['id']}"] + dl.get("lines", []):
        para(a, ln, size=10, after=0)
    cell_text(b, "לכבוד", size=9, bold=True, color=MUTED)
    for ln in [f"**{cl['name']}**"] + cl.get("lines", []):
        para(b, ln, size=10, after=0)

    para(d, spec["title"], size=15, bold=True, font=FONT_HEAD, before=12, after=3)
    for ptxt in spec.get("intro", []):
        para(d, ptxt, size=10.5, after=4, line=1.25)
    if spec.get("goal"):
        panel(d, "היעד שנמדוד", spec["goal"] if isinstance(spec["goal"], list) else [spec["goal"]], brand)
    if spec.get("proof"):
        panel(d, "עבודות דומות", spec["proof"], brand, size=10)
    elif spec.get("guarantee"):   # no portfolio to show: a concrete commitment instead of empty proof slots
        panel(d, "ההתחייבות שלנו", spec["guarantee"] if isinstance(spec["guarantee"], list) else [spec["guarantee"]],
              brand, size=10.5)
    if spec.get("packages"):  # optional anchor: lean vs full, so the client compares options, not "yes/no"
        panel(d, "שתי דרכים לעשות את זה", [f"**{pk['name']}: {pk['price']}.** {pk['what']}" for pk in spec["packages"]],
              brand, size=10.5)

    section_title(d, "מה כלול", brand, before=8)
    hdr = ["#", "תיאור", "כמות", "מחיר יחידה", "סה\"כ"]
    t = d.add_table(rows=1, cols=5)
    table_rtl(t)
    table_borders(t, color=RULE)
    cell_margins(t)
    widths = [0.8, 9.6, 1.4, 2.8, 2.8]
    for i, h in enumerate(hdr):
        c = t.rows[0].cells[i]
        cell_fill(c, brand)
        cell_text(c, h, size=10, bold=True, color="FFFFFF", align=None if i == 1 else "center")
    for n, (it, line) in enumerate(rows, 1):
        r = t.add_row().cells
        cell_text(r[0], str(n), size=10, color=MUTED, align="center")
        cell_text(r[1], f"**{it['desc']}**", size=10.5)
        if it.get("detail"):
            para(r[1], it["detail"], size=9.5, color=MUTED, after=0)
        cell_text(r[2], f"{it['qty']:g}", size=10.5, align="center")
        cell_text(r[3], ils(it["unit_price"]), size=10.5, align="center")
        cell_text(r[4], ils(line), size=10.5, bold=True, align="center")
    col_widths(t, widths)
    rows_keep(t)

    tot = [("סה\"כ לפני מע\"מ" if not exempt else "סה\"כ", sub)]
    if disc:
        tot.append((spec["discount"].get("label", "הנחה"), -disc))
        tot.append(("סה\"כ אחרי הנחה", net))
    if not exempt:
        tot.append((f"מע\"מ {rate:g}%", vat))
    tot.append(("סה\"כ לתשלום", total))
    t = d.add_table(rows=0, cols=3)
    table_rtl(t)
    table_borders(t, inside_h=False)
    cell_margins(t)
    vat_note = ("העסק רשום כעוסק פטור, ולכן לא נגבה מע\"מ." if exempt else
                f"המחירים בשקלים. מע\"מ לפי השיעור החוקי ביום הוצאת החשבונית (כיום {rate:g}%).")
    for i, (lab, val) in enumerate(tot):
        r = t.add_row().cells
        last = i == len(tot) - 1
        # the VAT note lives inside the totals table, so it can never be orphaned on the next page
        cell_text(r[0], vat_note if last else "", size=9.5 if last else 4, color=MUTED)
        for c in r:
            for pp in c.paragraphs:
                pp.paragraph_format.keep_with_next = not last
        if last:
            cell_fill(r[1], brand)
            cell_fill(r[2], brand)
        col = "FFFFFF" if last else INK
        cell_text(r[1], lab, size=11.5 if last else 10.5, bold=last, color=col)
        cell_text(r[2], ils(val), size=11.5 if last else 10.5, bold=True, color=col, align="center")
    col_widths(t, [10.8, 3.8, 2.8])
    rows_keep(t, header=False)

    terms = list(spec.get("terms", []))
    if not any("ביטול" in x for x in terms):
        terms.append(DEFAULT_CANCEL)
    spec = dict(spec, terms=terms)
    for key, title in (("compliance", "נגישות, פרטיות ועוגיות"), ("client_provides", "מה אתם מספקים"),
                       ("excluded", "מה לא כלול"), ("timeline", "לוח זמנים"), ("payment", "תנאי תשלום"),
                       ("warranty", "אחריות, אחסון, דומיין ותחזוקה"), ("terms", "תנאים")):
        if spec.get(key):
            section_title(d, title, brand)
            bullets(d, spec[key], brand, size=10.5)

    section_title(d, "אישור ההצעה", brand, before=12)
    para(d, "קראתי את ההצעה ואני מאשר/ת אותה, כולל תנאי התשלום.", size=10.5, after=2, keep_next=True)
    if spec.get("accept_how"):
        para(d, spec["accept_how"], size=10.5, bold=True, color=brand, after=10, keep_next=True)
    else:
        para(d, "", after=8, keep_next=True)
    t = d.add_table(rows=2, cols=3)
    table_rtl(t)
    table_borders(t, inside_h=False)
    for i, lab in enumerate(["שם מלא", "תאריך", "חתימה"]):
        c = t.rows[0].cells[i]
        cell_text(c, " ", size=10)
        border(c.paragraphs[0], "bottom", color=MUTED, sz=4)
        cell_text(t.rows[1].cells[i], lab, size=9, color=MUTED, align="center")
    footer_note(d, " · ".join(x for x in [dl["name"], dl.get("phone", ""), dl.get("email", "")] if x))
    set_sources(d, spec)
    d.save(out)


# ---------------------------------------------------------------- Formal letter / appeal
def build_letter(spec, out):
    """Facts are numbered and each one points to its annex ({"text", "annex": "א"}); the legal basis and the
    deadline line come from the spec (never from memory); a signature block closes the letter. If the spec has
    "submission", a separate checklist for the CLIENT (not sent) is written next to the letter."""
    brand = spec.get("brand", {}).get("color", "2B2F36")
    s = spec["sender"]
    d = new_doc(margins_cm=(2.0, 2.0, 2.3, 2.3))
    para(d, s["name"], size=13, bold=True, font=FONT_HEAD, after=0)
    p = para(d, " · ".join(s.get("lines", [])), size=10, color=MUTED, after=10)
    border(p, "bottom", color=RULE, sz=4, space=6)
    para(d, spec["date"], size=10.5, align="end", after=10)
    delivery = spec.get("submission", {}).get("channel_label") or spec.get("delivery")
    if delivery:   # one source of truth: the same channel the client checklist tells them to use
        para(d, delivery, size=10, bold=True, color=MUTED, after=6)
    for i, ln in enumerate(spec["to"]):
        para(d, ln, size=10.5, bold=(i == 1), after=0)
    para(d, "", after=8)
    sp = para(d, f"הנדון: {spec['subject']}", size=12, bold=True, font=FONT_HEAD, align="center", after=2)
    for r in spec.get("refs", []):
        para(d, r, size=10, color=MUTED, align="center", after=0)
    border(sp, "bottom", color=brand, sz=6, space=2)
    para(d, "", after=6)
    para(d, spec.get("opening", "שלום רב,"), size=11, after=6)
    if spec.get("summary"):
        para(d, spec["summary"], size=11, bold=True, after=8, line=1.3)
    # annexes are lettered in the order they are first cited (א' is the first one the reader meets)
    atts = spec.get("attachments", [])
    if atts and isinstance(atts[0], dict):
        cited = []
        for blk in spec["body"]:
            if isinstance(blk, dict) and blk.get("annex") and blk["annex"] not in cited:
                cited.append(blk["annex"])
        order = cited + [a["id"] for a in atts if a["id"] not in cited]
        by_id = {a["id"]: a["text"] for a in atts}
        letter_of = {aid: chr(0x05D0 + i) for i, aid in enumerate(order)}
        atts = [by_id[aid] for aid in order]
    else:
        letter_of = {}
    if not spec.get("legal_basis") or PLACEHOLDER_RE.sub("", spec["legal_basis"]).strip() == "":
        print("WARN: no researched legal basis - search the regulation/bylaw/ruling before sending (documents-writing.md)")
    n = 0
    for blk in spec["body"]:
        if isinstance(blk, dict) and blk.get("heading"):
            para(d, blk["heading"], size=11, bold=True, font=FONT_HEAD, before=6, after=3, keep_next=True)
            continue
        text = blk["text"] if isinstance(blk, dict) else blk
        if isinstance(blk, dict) and blk.get("annex"):
            text = text.rstrip(".") + f" (נספח {letter_of.get(blk['annex'], blk['annex'])}')."
        n += 1
        bp = para(d, "", size=11, after=5, line=1.3)  # ragged: justified Hebrew opens wide gaps
        bp.paragraph_format.right_indent = Cm(0.6)
        bp.paragraph_format.first_line_indent = Cm(-0.6)
        style_run(bp.add_run(f"{n}.\t"), size=11, bold=True, color=brand)
        add_rich(bp, text, size=11)
    if spec.get("legal_basis"):
        para(d, spec["legal_basis"], size=11, before=2, after=5, line=1.3)
    if spec.get("request"):
        rp = para(d, spec["request"], size=11.5, bold=True, before=6, after=6, line=1.3)
        border(rp, "right", color=brand, sz=18, space=8)
    if spec.get("deadline_line"):
        para(d, spec["deadline_line"], size=10, color=MUTED, after=8, line=1.25)
    if atts:
        para(d, "נספחים:", size=10.5, bold=True, before=4, after=2, keep_next=True)
        for i, a in enumerate(atts):
            para(d, f"{chr(0x05D0 + i)}'.  {a}", size=10.5, after=1, keep_next=i < len(atts) - 1)
    # Hebrew letter convention: the closing block sits on the end (visual left) side, signature line above name
    para(d, spec.get("closing", "בכבוד רב,"), size=11, before=14, after=22, keep_next=True, align="end")
    sig = para(d, " ", size=11, after=1, keep_next=True, align="end")
    sig.paragraph_format.left_indent = Cm(10.0)
    border(sig, "bottom", color=MUTED, sz=4)
    para(d, s["name"], size=11, bold=True, after=0, keep_next=True, align="end")
    for k, ln in enumerate(spec.get("signature_lines", [])):
        para(d, ln, size=10, color=MUTED, after=0, align="end", keep_next=k < len(spec["signature_lines"]) - 1)
    set_sources(d, spec)
    d.save(out)
    if spec.get("submission"):
        build_checklist(spec, os.path.splitext(out)[0] + "-checklist.docx")


def build_checklist(spec, out):
    """The client's own page: deadline with its source, channel, proof of sending, follow-up date. Not sent."""
    brand = spec.get("brand", {}).get("color", "2B2F36")
    sub = spec["submission"]
    d = new_doc(margins_cm=(2.0, 2.0, 2.3, 2.3))
    para(d, "רשימת הגשה: לשימושך בלבד, לא לשלוח", size=16, bold=True, font=FONT_HEAD, after=2)
    para(d, f"הנדון: {spec['subject']}", size=11, color=MUTED, after=10)
    for title, key in (("המועד ומקורו", "deadline"), ("איך מגישים", "channel"), ("הוכחת שליחה", "proof"),
                       ("מעקב", "follow_up"), ("אם הבקשה נדחית", "if_rejected"), ("לפני ששולחים", "before_sending")):
        if sub.get(key):
            section_title(d, title, brand)  # noqa
            items = sub[key] if isinstance(sub[key], list) else [sub[key]]
            if key == "channel" and sub.get("channel_label"):
                items = [f"**{sub['channel_label']}** (כמו שכתוב במכתב)."] + items
            boxes = [("☐  " + x) for x in items] if key in ("before_sending", "proof") else items
            for k, x in enumerate(boxes):
                para(d, x, size=11, after=3, line=1.25, keep_next=k < len(boxes) - 1)
    # every legal document's checklist carries the disclaimer and the lawyer referral (qa_text.py checks it)
    section_title(d, "חשוב לדעת", brand)
    for k, x in enumerate([LEGAL_DISCLAIMER] + sub.get("legal_notes", [])):
        para(d, x, size=11, after=3, line=1.25, keep_next=k < len(sub.get("legal_notes", [])))
    if sub.get("sources"):
        section_title(d, "מקורות", brand)
        for x in sub["sources"]:
            para(d, x, size=10, color=MUTED, after=2)
    d.save(out)


# ---------------------------------------------------------------- main
def to_pdf(docx_path):
    outdir = os.path.dirname(os.path.abspath(docx_path))
    prof = tempfile.mkdtemp()
    subprocess.run(["soffice", f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", "pdf",
                    "--outdir", outdir, docx_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pdf = os.path.splitext(docx_path)[0] + ".pdf"
    if not os.path.exists(pdf):
        sys.exit("LibreOffice conversion failed")
    return pdf


def pdf_layout(pdf):
    """(pages, fill of last page 0..1) using pymupdf; (pages, None) without it."""
    pages = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdf], capture_output=True,
                                                             text=True).stdout).group(1))
    try:
        import pymupdf
    except ImportError:
        return pages, None
    pg = pymupdf.open(pdf)[-1]
    ys = [b[3] for b in pg.get_text("blocks") if b[4].strip() and b[3] < pg.rect.height * 0.94]
    return pages, (max(ys) / pg.rect.height if ys else 0.0)


def suggested_name(spec):
    clean = lambda x: re.sub(r"[\s/\\\\:\"'*?<>|]+", "-", PLACEHOLDER_RE.sub("", x)).strip("-")
    if spec["type"] == "quote":
        return f"הצעת-מחיר-{clean(spec['number'])}-{clean(spec['client']['name'])}-{clean(spec['dealer']['name'])}"
    if spec["type"] == "cv":
        return (f"CV-{clean(spec['name'])}" if spec.get("lang") == "en" else f"קורות-חיים-{clean(spec['name'])}")
    return f"{clean(spec['subject'])}-{clean(spec['sender']['name'])}"


PLACEHOLDER_RE = re.compile(r"\[[^\]]*\]")
def build(spec, out, scale):
    global SCALE
    SCALE = scale
    {"cv": build_cv, "quote": build_quote, "letter": build_letter}[spec["type"]](spec, out)


def fit(spec, out):
    """Render and adjust SCALE: a CV grows (from 10.5pt body upward) to fill its one page; a multi-page document
    never ends on a half-empty page: first try to pull the tail back (down to 0.95), else grow to fill it."""
    def run(sc):
        build(spec, out, sc)
        return pdf_layout(to_pdf(out))
    if spec["type"] == "cv":
        best = 1.0
        for sc in (1.0, 1.04, 1.08, 1.12, 1.16, 1.2):
            pages, fill = run(sc)
            if pages > 1:
                break
            best = sc
            if fill is not None and fill > 0.9:
                break
        pages, fill = run(best)
        return best, pages, fill
    pages, fill = run(1.0)
    if pages > 1 and fill is not None and fill < 0.4:
        for sc in (0.97, 0.95):            # never below 95%: body text stays readable
            p2, f2 = run(sc)
            if p2 < pages:
                return sc, p2, f2
        for sc in (1.03, 1.06, 1.09, 1.12):
            p2, f2 = run(sc)
            if p2 > pages:
                break
            if f2 is not None and f2 >= 0.45:
                return sc, p2, f2
        pages, fill = run(1.0)
    return 1.0, pages, fill


def fit_checklist(spec, path):
    """The client checklist gets the same rule: one page if it can, never a nearly empty last page."""
    global SCALE
    best = None
    for sc in (1.0, 0.95, 0.9, 1.05, 1.1):
        SCALE = sc
        build_checklist(spec, path)
        pages, fill = pdf_layout(to_pdf(path))
        if pages == 1 or (fill is not None and fill >= 0.4):
            best = sc
            break
    if best is None:
        SCALE = 1.0
        build_checklist(spec, path)
        to_pdf(path)
    SCALE = 1.0


def main():
    global FONT_HEAD, FONT_BODY
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit(__doc__)
    if "--safe-fonts" in sys.argv:
        FONT_HEAD = FONT_BODY = "Arial"
    spec = json.load(open(args[0], encoding="utf-8"))
    global RTL
    RTL = spec.get("lang", "he") != "en"
    out = args[1]
    if os.path.isdir(out):
        out = os.path.join(out, suggested_name(spec) + ".docx")
    if "--pdf" in sys.argv:
        sc, pages, fill = fit(spec, out)
        if spec["type"] == "letter" and spec.get("submission"):
            fit_checklist(spec, os.path.splitext(out)[0] + "-checklist.docx")
        print(f"DOCX: {out}\nPDF:  {os.path.splitext(out)[0]}.pdf  (scale {sc:.2f}, {pages} pages, last page "
              f"{'?' if fill is None else f'{fill:.0%}'} full)")
    else:
        build(spec, out, 1.0)
        print("DOCX:", out)
    print("Suggested delivery name:", suggested_name(spec) + ".pdf")
    if spec["type"] == "quote":
        rows, sub, disc, net, rate, vat, total, exempt = quote_totals(spec)
        print(f"Totals: subtotal={sub:,.2f} discount={disc:,.2f} vat({rate}%)={vat:,.2f} total={total:,.2f}")


if __name__ == "__main__":
    main()
