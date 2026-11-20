#!/usr/bin/env python3
"""doc_build.py - professional RTL Hebrew Word documents from a JSON spec, rendered to PDF.

Usage:
  python3 doc_build.py spec.json out.docx [--pdf] [--safe-fonts]

Spec "type": cv | quote | letter   (examples: templates/documents/examples/*.json)
  --pdf          also render out.pdf next to the docx with LibreOffice (needs soffice + the fonts installed:
                 bash templates/documents/install_fonts.sh)
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


def style_run(run, size=10.5, bold=False, color=INK, font=None, highlight=False):
    font = font or FONT_BODY
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
    if has_hebrew(run.text):
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
    _pPr_bidi(p)
    pf = p.paragraph_format
    pf.space_before, pf.space_after, pf.line_spacing = Pt(before), Pt(after), line
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


def add_rich(p, text, size=10.5, bold=False, color=INK, font=None):
    for seg, b, ph in split_rich(bidi_fix(no_runt(text))):
        style_run(p.add_run(seg), size=size, bold=bold or b, color=color, font=font, highlight=ph)
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
    sp = s._sectPr
    b = OxmlElement("w:bidi")
    sp.append(b)
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
    pPr = st.element.get_or_add_pPr()
    pPr.append(OxmlElement("w:bidi"))
    d.core_properties.language = "he-IL"
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

# ---------------------------------------------------------------- CV (1 page, ATS-safe: single column, no text in tables)
def build_cv(spec, out):
    brand = spec.get("brand", {}).get("color", BRAND)
    d = new_doc(margins_cm=(1.5, 1.5, 1.7, 1.7))
    para(d, spec["name"], size=24, bold=True, color=INK, font=FONT_HEAD, after=0, line=1.0)
    para(d, spec["title"], size=12.5, bold=True, color=brand, font=FONT_HEAD, after=3)
    p = para(d, " · ".join(spec["contact"]), size=9.5, color=MUTED, after=6)
    border(p, "bottom", color=RULE, sz=4, space=4)
    if spec.get("summary"):
        para(d, spec["summary"], size=10.5, color=INK, before=4, after=2, line=1.2)
    for sec in spec["sections"]:
        section_title(d, sec["title"], brand)
        for it in sec.get("items", []):
            head = f"**{it['role']}**"
            if it.get("org"):
                head += f" · {it['org']}"
            hp = para(d, head, size=10.5, color=INK, before=4, after=1, keep_next=True)
            if it.get("dates"):
                # dates flush to the far (left) edge: an RTL paragraph measures tabs from the right margin
                hp.paragraph_format.tab_stops.add_tab_stop(Cm(TEXT_W_CV), WD_TAB_ALIGNMENT.RIGHT)
                style_run(hp.add_run("\t" + bidi_fix(it["dates"])), size=10, color=MUTED)
            if it.get("sub"):
                para(d, it["sub"], size=9.5, color=MUTED, after=1, keep_next=True)
            for b in it.get("bullets", []):
                bp = para(d, "", size=10.5, after=1.5, line=1.2)
                bp.paragraph_format.right_indent = Cm(0.35)       # RTL: "right" is the start side
                bp.paragraph_format.first_line_indent = Cm(-0.35)
                style_run(bp.add_run("•  "), size=10.5, color=brand, bold=True)
                add_rich(bp, b, size=10.5)
        for ln in sec.get("lines", []):
            lp = para(d, "", size=10.5, after=2, line=1.2)
            if ln.get("label"):
                style_run(lp.add_run(bidi_fix(ln["label"]) + ": "), size=10.5, bold=True, color=INK)
            add_rich(lp, ln["text"], size=10.5)
        if sec.get("text"):
            para(d, sec["text"], size=10, after=2)
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


def build_quote(spec, out):
    brand = spec.get("brand", {}).get("color", BRAND)
    dl, cl = spec["dealer"], spec["client"]
    d = new_doc(margins_cm=(1.6, 1.8, 1.8, 1.8))
    rows, sub, disc, net, rate, vat, total, exempt = quote_totals(spec)

    # header band: business name (start) | document id (end)
    t = d.add_table(rows=1, cols=2)
    table_rtl(t)
    table_borders(t, inside_h=False)
    col_widths(t, [10.4, 7.0])
    c0, c1 = t.rows[0].cells
    cell_text(c0, dl["name"], size=20, bold=True, color=brand, font=FONT_HEAD)
    para(c0, dl.get("tagline", ""), size=9.5, color=MUTED, after=0)
    cell_text(c1, "הצעת מחיר", size=20, bold=True, color=INK, font=FONT_HEAD, align="end")
    para(c1, f"מס' {spec['number']}  ·  {spec['date']}", size=9.5, color=MUTED, align="end", after=0)
    para(c1, f"בתוקף עד {spec['valid_until']}", size=9.5, color=MUTED, align="end", after=0)
    p = para(d, "", after=8)
    border(p, "bottom", color=brand, sz=12, space=1)

    # parties
    t = d.add_table(rows=1, cols=2)
    table_rtl(t)
    table_borders(t, inside_h=False)
    cell_margins(t, top=80, bottom=80, start=140, end=140)
    col_widths(t, [8.7, 8.7])
    a, b = t.rows[0].cells
    cell_fill(a, PANEL)
    cell_fill(b, PANEL)
    kind = "עוסק פטור" if exempt else ("עוסק מורשה" if dl.get("kind") == "licensed" else "חברה בע\"מ")
    cell_text(a, "מאת", size=8.5, bold=True, color=MUTED)
    for ln in [f"**{dl['name']}**", f"{kind} {dl['id']}"] + dl.get("lines", []):
        para(a, ln, size=9.5, after=0)
    cell_text(b, "לכבוד", size=8.5, bold=True, color=MUTED)
    for ln in [f"**{cl['name']}**"] + cl.get("lines", []):
        para(b, ln, size=9.5, after=0)

    # title + value paragraph
    para(d, spec["title"], size=15, bold=True, font=FONT_HEAD, before=12, after=3)
    for ptxt in spec.get("intro", []):
        para(d, ptxt, size=10.5, after=4, line=1.25)

    # line items
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
        cell_text(c, h, size=9.5, bold=True, color="FFFFFF", align=None if i == 1 else "center")
    for n, (it, line) in enumerate(rows, 1):
        r = t.add_row().cells
        cell_text(r[0], str(n), size=9.5, color=MUTED, align="center")
        cell_text(r[1], f"**{it['desc']}**", size=10)
        if it.get("detail"):
            para(r[1], it["detail"], size=9, color=MUTED, after=0)
        cell_text(r[2], f"{it['qty']:g}", size=10, align="center")
        cell_text(r[3], ils(it["unit_price"]), size=10, align="center")
        cell_text(r[4], ils(line), size=10, bold=True, align="center")
    col_widths(t, widths)

    # totals (aligned to the end side)
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
    for i, (lab, val) in enumerate(tot):
        r = t.add_row().cells
        last = i == len(tot) - 1
        cell_text(r[0], "", size=4)
        if last:
            cell_fill(r[1], brand)
            cell_fill(r[2], brand)
        col = "FFFFFF" if last else INK
        cell_text(r[1], lab, size=11 if last else 10, bold=last, color=col)
        cell_text(r[2], ils(val), size=11 if last else 10, bold=True, color=col, align="center")
    col_widths(t, [11.8, 2.8, 2.8])
    if exempt:
        para(d, "העסק רשום כעוסק פטור, ולכן לא נגבה מע\"מ.", size=9, color=MUTED, before=3)
    else:
        para(d, f"המחירים בשקלים. מע\"מ לפי השיעור החוקי ביום הוצאת החשבונית (כיום {rate:g}%).",
             size=9, color=MUTED, before=3)

    for key, title in (("excluded", "מה לא כלול"), ("timeline", "לוח זמנים"), ("payment", "תנאי תשלום"),
                       ("terms", "תנאים")):
        if spec.get(key):
            section_title(d, title, brand)
            for k, ln in enumerate(spec[key]):
                # short sections stay on one page: every bullet but the last keeps with the next
                bp = para(d, "", size=10, after=1.5, line=1.2, keep_next=k < len(spec[key]) - 1)
                bp.paragraph_format.right_indent = Cm(0.4)
                bp.paragraph_format.first_line_indent = Cm(-0.4)
                style_run(bp.add_run("•  "), size=10, color=brand, bold=True)
                add_rich(bp, ln, size=10)

    # acceptance block
    section_title(d, "אישור ההצעה", brand, before=12)
    para(d, "קראתי את ההצעה ואני מאשר/ת אותה, כולל תנאי התשלום.", size=10, after=2, keep_next=True)
    if spec.get("accept_how"):
        para(d, spec["accept_how"], size=10, bold=True, color=brand, after=10, keep_next=True)
    else:
        para(d, "", after=8, keep_next=True)
    t = d.add_table(rows=2, cols=3)
    table_rtl(t)
    table_borders(t, inside_h=False)
    for i, lab in enumerate(["שם מלא", "תאריך", "חתימה"]):
        c = t.rows[0].cells[i]
        cell_text(c, " ", size=10)
        border(c.paragraphs[0], "bottom", color=MUTED, sz=4)
        cell_text(t.rows[1].cells[i], lab, size=8.5, color=MUTED, align="center")
    footer_note(d, " · ".join(x for x in [dl["name"], dl.get("phone", ""), dl.get("email", "")] if x))
    d.save(out)


# ---------------------------------------------------------------- Formal letter / appeal
def build_letter(spec, out):
    brand = spec.get("brand", {}).get("color", "2B2F36")
    s = spec["sender"]
    d = new_doc(margins_cm=(2.0, 2.0, 2.3, 2.3))
    para(d, s["name"], size=13, bold=True, font=FONT_HEAD, after=0)
    p = para(d, " · ".join(s.get("lines", [])), size=9.5, color=MUTED, after=10)
    border(p, "bottom", color=RULE, sz=4, space=6)
    para(d, spec["date"], size=10.5, align="end", after=10)
    if spec.get("delivery"):
        para(d, spec["delivery"], size=10, bold=True, color=MUTED, after=6)
    for i, ln in enumerate(spec["to"]):
        para(d, ln, size=10.5, bold=(i == 1), after=0)
    para(d, "", after=8)
    sp = para(d, f"הנדון: {spec['subject']}", size=12, bold=True, font=FONT_HEAD, align="center", after=2)
    for r in spec.get("refs", []):
        para(d, r, size=10, color=MUTED, align="center", after=0)
    border(sp, "bottom", color=brand, sz=6, space=2)
    para(d, "", after=6)
    para(d, spec.get("opening", "שלום רב,"), size=11, after=6)
    if spec.get("summary"):  # the first line does the work: the request and the decisive reason, in one sentence
        para(d, spec["summary"], size=11, bold=True, after=8, line=1.3)
    n = 0
    for blk in spec["body"]:
        if isinstance(blk, dict) and blk.get("heading"):
            para(d, blk["heading"], size=11, bold=True, font=FONT_HEAD, before=6, after=3, keep_next=True)
            continue
        n += 1
        bp = para(d, "", size=11, after=5, line=1.3)  # ragged: justified Hebrew opens wide gaps
        bp.paragraph_format.right_indent = Cm(0.6)
        bp.paragraph_format.first_line_indent = Cm(-0.6)
        style_run(bp.add_run(f"{n}.\t"), size=11, bold=True, color=brand)
        add_rich(bp, blk, size=11)
    if spec.get("request"):
        rp = para(d, spec["request"], size=11.5, bold=True, before=6, after=8, line=1.3)
        border(rp, "right", color=brand, sz=18, space=8)
    if spec.get("attachments"):
        para(d, "נספחים:", size=10.5, bold=True, before=4, after=2, keep_next=True)
        for i, a in enumerate(spec["attachments"]):
            para(d, f"{chr(0x05D0 + i)}.  {a}", size=10.5, after=1)
    para(d, spec.get("closing", "בכבוד רב,"), size=11, before=14, after=24)
    para(d, s["name"], size=11, bold=True, after=0)
    for ln in spec.get("signature_lines", []):
        para(d, ln, size=10, color=MUTED, after=0)
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


def main():
    global FONT_HEAD, FONT_BODY
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit(__doc__)
    if "--safe-fonts" in sys.argv:
        FONT_HEAD = FONT_BODY = "Arial"
    spec = json.load(open(args[0], encoding="utf-8"))
    {"cv": build_cv, "quote": build_quote, "letter": build_letter}[spec["type"]](spec, args[1])
    print("DOCX:", args[1])
    if spec["type"] == "quote":
        rows, sub, disc, net, rate, vat, total, exempt = quote_totals(spec)
        print(f"Totals: subtotal={sub:,.2f} discount={disc:,.2f} vat({rate}%)={vat:,.2f} total={total:,.2f}")
    if "--pdf" in sys.argv:
        print("PDF: ", to_pdf(args[1]))


if __name__ == "__main__":
    main()
