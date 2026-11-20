#!/usr/bin/env python3
"""deck_build.py - RTL Hebrew pitch / presentation deck (16:9 .pptx) from a JSON spec, rendered to PDF.

Usage:
  python3 deck_build.py spec.json out.pptx [--pdf]

Rules baked in (business-strategy.md, "רף הסוכנות"):
  * one message per slide: the headline IS the message (a sentence, not a topic)
  * presented deck: every text >= 24pt, headlines 40pt  (spec "mode": "send" allows 16pt for read-alone decks)
  * brand colours from spec, Heebo font, fixed 12-column grid with 0.6in margins, RTL everywhere
  * speaker notes on every slide
  * placeholders [לאשר ...] render as amber text so unverified claims are impossible to miss

Slide kinds (spec "slides"[].kind):
  title     {title, subtitle, footer}
  statement {kicker, headline, points[<=3], stat?{value,label}}
  steps     {kicker, headline, steps[3-4]{title,text}}
  product   {kicker, headline, window_title, columns[]{title, cards[]{text, hot?}}, image?, note?}  (app mock)
  numbers   {kicker, headline, numbers[1-3]{value,label}, note? | risk?}
  formula   {kicker, headline, terms[{value,label}], result{value,label}, note?}
  tiers     {kicker, headline, tiers[3]{name,price,points[],featured?}, note?}
  table     {kicker, headline, columns[], rows[[...]], note?}
  ask       {kicker, headline, amount?, uses[{label,pct}], promise?, next?, contact?}  (bars only if pct are real numbers)
  team      {kicker, headline, team[{name, role, initials, edge}]}
  finance   {kicker, headline, columns[], rows[[...]], unit?{price_incl_vat, vat, after_fees, after_tax}}
  closing   {headline, next?, contact}
Every slide may have "notes" (sources and caveats go there, never as small print on the slide). Instructions to
the builder ("המחשה", "בלי מקור לא מציגים", "נבדק מול...") belong in notes - qa_text.py fails them on a slide.
Data points ({value,label}) take "status": "done" | "planned" and an optional "target"; a missing or planned
value renders as an outlined "data needed / יעד" card, never as a big number box.
Spec "status": "skeleton" marks the title slide "שלד לעבודה" and writes <deck>-data-to-collect.docx.
Spec "sources": [{"claim","source"}] and "supplied": [facts the client gave] are stored in the file.
Spec "sources": [{"claim", "source"}] is stored in the file; qa_text.py accepts those claims.
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hebrew_text import bidi_fix, split_rich  # noqa: E402

try:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.dml import MSO_LINE
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.oxml.ns import qn
    from pptx.util import Emu, Inches, Pt
except ImportError:
    sys.exit("python-pptx missing: pip install python-pptx")

W, H = 13.333, 7.5
M = 0.6                      # outer margin (in)
FONT = "Heebo"
AMBER = "F2B33D"
MIN_PT = 24
HEAD_PT = 36                 # slide headline (a full sentence; 36pt keeps most on one line at 16:9)


class Theme:
    def __init__(self, b):
        self.dark = b.get("dark", "0E1630")
        self.light = b.get("light", "F5F7FB")
        self.accent = b.get("accent", "3D6BFF")
        self.accent2 = b.get("accent2", "18B79A")
        self.ink = b.get("ink", "141A2E")
        self.muted = b.get("muted", "5A6478")
        self.card = b.get("card", "FFFFFF")


def C(h):
    return RGBColor.from_string(h.upper())


def rect(slide, x, y, w, h, fill, shape=MSO_SHAPE.RECTANGLE, line=None, radius=None):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid()
    s.fill.fore_color.rgb = C(fill)
    if line:
        s.line.color.rgb = C(line)
        s.line.width = Pt(1.25)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    if radius is not None and shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    return s


def _rtl_par(p, align="r"):
    pPr = p._p.get_or_add_pPr()
    pPr.set("rtl", "1")
    pPr.set("algn", align)


def _style_run(r, size, color, bold=False, ph=False):
    f = r.font
    f.size = Pt(size)
    f.bold = bold
    f.name = FONT
    f.color.rgb = C(AMBER if ph else color)
    rPr = r._r.get_or_add_rPr()
    rPr.set("lang", "he-IL")
    rPr.set("altLang", "en-US")
    for tag in ("a:cs", "a:ea"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", FONT)


def text(slide, x, y, w, h, content, size, color, bold=False, align="r", anchor="t", spacing=1.1, after=0):
    """content: str or list of str (paragraphs). Supports **bold** and [לאשר] placeholders."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}[anchor]
    paras = content if isinstance(content, list) else [content]
    for i, ptxt in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        _rtl_par(p, align)
        p.line_spacing = spacing
        p.space_after = Pt(after)
        for seg, b, ph in split_rich(bidi_fix(ptxt)):
            _style_run(p.add_run(), size, color, bold or b, ph)
            p.runs[-1].text = seg
    return tb


def notes(slide, s):
    if s.get("notes"):
        slide.notes_slide.notes_text_frame.text = s["notes"]


def bg(slide, color):
    f = slide.background.fill
    f.solid()
    f.fore_color.rgb = C(color)


def header(slide, t, s, n, total, dark=False):
    ink = "FFFFFF" if dark else t.ink
    if s.get("kicker"):
        text(slide, M, 0.45, W - 2 * M, 0.5, s["kicker"], MIN_PT, t.accent if not dark else t.accent2, bold=True)
    text(slide, M, 0.95, W - 2 * M, 1.6, s["headline"], HEAD_PT, ink, bold=True, spacing=1.0)
    # footer: page number on the end side, brand on the start side
    # no small print on a presented slide: no page number, no footnotes (sources go to the speaker notes)
    rect(slide, W - M - 0.9, H - 0.42, 0.9, 0.06, t.accent)


# ---------------------------------------------------------------- slide kinds
SKELETON = False


def k_title(sl, t, s, n, total):
    bg(sl, t.dark)
    rect(sl, W - M - 1.2, 1.55, 1.2, 0.12, t.accent2)
    text(sl, M, 1.85, W - 2 * M, 1.4, s["title"], 72, "FFFFFF", bold=True, align="r")
    text(sl, M + 2.0, 3.35, W - 2 * M - 2.0, 1.6, s["subtitle"], 32, "D9E0F0", spacing=1.05)
    footer = ("שלד לעבודה · " if SKELETON else "") + s.get("footer", "")
    if footer.strip(" ·"):
        text(sl, M, H - 1.1, W - 2 * M, 0.5, footer.strip(" ·"), MIN_PT, "9AA6C2")


def missing(item):
    """A data point with no real value yet: placeholder, empty, or research that is only planned."""
    v = str(item.get("value", ""))
    return item.get("status") == "planned" or not v.strip() or "[לאשר" in v


def value_card(sl, t, x, y, w, h, item, dark, big=44):
    """Hero number card. A missing value never renders as a big number box: it becomes an outlined card that
    says what data is needed (or the target, for planned research), so the slide doesn't imply a number."""
    if missing(item):
        box = rect(sl, x, y, w, h, t.dark if dark else t.light, MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05,
                   line="5A6B94" if dark else "B9C1D3")
        box.line.dash_style = MSO_LINE.DASH
        head = ("יעד: " + item["target"]) if item.get("target") else (
            "מתוכנן" if item.get("status") == "planned" else "נתון לאיסוף")
        text(sl, x + 0.2, y + 0.3, w - 0.4, 0.9, head, 28, t.accent2 if item.get("target") else (
            "9AA6C2" if dark else t.muted), bold=True, align="ctr", anchor="m")
        text(sl, x + 0.2, y + 1.25, w - 0.4, h - 1.4, item["label"], MIN_PT, "C9D2E6" if dark else t.ink, align="ctr")
        return
    rect(sl, x, y, w, h, "1A2442" if dark else t.dark, MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
    text(sl, x + 0.2, y + 0.2, w - 0.4, 1.4, item["value"], big, "FFFFFF", bold=True, align="ctr", anchor="m")
    text(sl, x + 0.2, y + 1.65, w - 0.4, h - 1.8, item["label"], MIN_PT, "C9D2E6", align="ctr")


def k_statement(sl, t, s, n, total):
    bg(sl, t.light)
    header(sl, t, s, n, total)
    has_stat = bool(s.get("stat"))
    colw = (W - 2 * M) * (0.58 if has_stat else 1.0)
    y = 2.75
    for p in s.get("points", [])[:3]:
        rect(sl, W - M - 0.12, y + 0.14, 0.12, 0.42, t.accent)
        text(sl, W - M - colw, y, colw - 0.35, 1.0, p, 26, t.ink, spacing=1.05)
        y += 1.2
    if has_stat:
        cw = (W - 2 * M) * 0.36
        value_card(sl, t, M, 2.75, cw, 3.3, s["stat"], dark=False, big=54)


def k_steps(sl, t, s, n, total):
    bg(sl, t.light)
    header(sl, t, s, n, total)
    steps = s["steps"]
    gap = 0.3
    cw = (W - 2 * M - gap * (len(steps) - 1)) / len(steps)
    for i, st in enumerate(steps):  # first step on the right (RTL)
        x = W - M - cw - i * (cw + gap)
        rect(sl, x, 2.65, cw, 3.95, t.card, MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
        rect(sl, x, 2.65, cw, 0.1, t.accent if i < len(steps) - 1 else t.accent2)
        text(sl, x + 0.25, 2.85, cw - 0.5, 0.75, f"0{i + 1}", 36, t.accent if i < len(steps) - 1 else t.accent2, bold=True)
        text(sl, x + 0.25, 3.55, cw - 0.5, 0.85, st["title"], 28, t.ink, bold=True, spacing=1.0)
        text(sl, x + 0.25, 4.4, cw - 0.5, 2.1, st["text"], MIN_PT, t.muted, spacing=1.05)


def k_product(sl, t, s, n, total):
    """Product mock built from shapes: an app window with a pipeline board. Columns = the flow stages (RTL).
    It is an ILLUSTRATION - the note says so until a real screenshot replaces it (spec "image": path)."""
    bg(sl, t.light)
    header(sl, t, s, n, total)
    x0, y0, w, h = M, 2.45, W - 2 * M, 3.75
    if s.get("image") and os.path.exists(s["image"]):
        sl.shapes.add_picture(s["image"], Inches(x0), Inches(y0), Inches(w), Inches(h))
    else:
        rect(sl, x0, y0, w, h, t.card, MSO_SHAPE.ROUNDED_RECTANGLE, line="D8DDE8", radius=0.03)
        rect(sl, x0, y0, w, 0.55, t.dark, MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.25)
        rect(sl, x0, y0 + 0.3, w, 0.25, t.dark)
        for i, c in enumerate(("FF5F57", "FEBC2E", "28C840")):
            rect(sl, x0 + 0.25 + i * 0.28, y0 + 0.19, 0.17, 0.17, c, MSO_SHAPE.OVAL)
        text(sl, x0 + 1.3, y0 + 0.02, w - 1.6, 0.5, s.get("window_title", ""), MIN_PT, "FFFFFF", bold=True,
             anchor="m")
        cols = s["columns"]
        gap = 0.18
        cw = (w - 0.5 - gap * (len(cols) - 1)) / len(cols)
        for i, col in enumerate(cols):
            cx = x0 + w - 0.25 - cw - i * (cw + gap)
            last = i == len(cols) - 1
            rect(sl, cx, y0 + 0.75, cw, h - 0.95, "EEF1F7", MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.04)
            text(sl, cx + 0.15, y0 + 0.82, cw - 0.3, 0.5, col["title"], MIN_PT,
                 t.accent2 if last else t.accent, bold=True)
            cy = y0 + 1.4
            for j, card in enumerate(col.get("cards", [])):
                hot = card.get("hot")
                rect(sl, cx + 0.12, cy, cw - 0.24, 0.85, t.card, MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08,
                     line=(t.accent2 if last else t.accent) if hot else "DDE2EC")
                text(sl, cx + 0.22, cy + 0.04, cw - 0.44, 0.78, card["text"], MIN_PT, t.ink, anchor="m",
                     spacing=0.95)
                cy += 0.98
    if s.get("note"):
        text(sl, M, 6.3, W - 2 * M - 1.2, 0.5, s["note"], MIN_PT, t.muted)


def k_numbers(sl, t, s, n, total):
    bg(sl, t.dark)
    header(sl, t, s, n, total, dark=True)
    nums = s["numbers"]
    gap = 0.35
    cw = (W - 2 * M - gap * (len(nums) - 1)) / len(nums)
    for i, nm in enumerate(nums):
        x = W - M - cw - i * (cw + gap)
        top = 2.4 if s.get("risk") else 2.9
        value_card(sl, t, x, top, cw, 3.0 if s.get("risk") else 3.1, nm, dark=True)
    if s.get("risk"):
        rect(sl, M, 5.65, W - 2 * M, 1.15, "1A2442", MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.12)
        rect(sl, W - M - 0.12, 5.85, 0.12, 0.75, AMBER)
        text(sl, M + 0.25, 5.68, W - 2 * M - 0.6, 1.1, s["risk"], MIN_PT, "FFFFFF", anchor="m", spacing=1.0)
    elif s.get("note"):
        text(sl, M, 6.1, W - 2 * M, 0.6, s["note"], MIN_PT, "9AA6C2")


def k_formula(sl, t, s, n, total):
    bg(sl, t.light)
    header(sl, t, s, n, total)
    items = []
    for i, term in enumerate(s["terms"]):
        if i:
            items.append(("×", None, None))
        items.append((term["value"], term["label"], term))
    items.append(("=", None, None))
    items.append((s["result"]["value"], s["result"]["label"], s["result"]))
    boxes = [it for it in items if it[1] is not None]  # (value, label, item)
    ops = len(items) - len(boxes)
    opw = 0.55
    bw = (W - 2 * M - ops * opw) / len(boxes)
    x = W - M
    for val, lab, item in items:
        if lab is None:
            x -= opw
            text(sl, x, 3.2, opw, 1.0, val, 40, t.muted, bold=True, align="ctr", anchor="m")
            continue
        x -= bw
        last = (val, lab, item) == boxes[-1]
        if missing(item):   # the formula still shows HOW the market is computed, without implying the numbers
            box = rect(sl, x + 0.05, 2.8, bw - 0.1, 2.3, t.light, MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06,
                       line="B9C1D3")
            box.line.dash_style = MSO_LINE.DASH
            text(sl, x + 0.15, 2.9, bw - 0.3, 1.2, lab, MIN_PT, t.ink, align="ctr", anchor="m")
            text(sl, x + 0.15, 4.1, bw - 0.3, 0.95, item.get("source_hint", "נתון לאיסוף"), MIN_PT, t.muted,
                 align="ctr")
            continue
        rect(sl, x + 0.05, 2.8, bw - 0.1, 2.3, t.dark if last else t.card, MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
        text(sl, x + 0.15, 2.95, bw - 0.3, 1.1, val, 30, "FFFFFF" if last else t.ink, bold=True, align="ctr",
             anchor="m")
        text(sl, x + 0.15, 4.05, bw - 0.3, 1.0, lab, MIN_PT, "C9D2E6" if last else t.muted, align="ctr")
    if s.get("note"):
        text(sl, M, 5.45, W - 2 * M, 1.2, s["note"], MIN_PT, t.muted)


def k_tiers(sl, t, s, n, total):
    bg(sl, t.light)
    header(sl, t, s, n, total)
    tiers = s["tiers"]
    gap = 0.3
    cw = (W - 2 * M - gap * (len(tiers) - 1)) / len(tiers)
    for i, tr in enumerate(tiers):
        x = W - M - cw - i * (cw + gap)
        feat = tr.get("featured")
        rect(sl, x, 2.5, cw, 3.3, t.dark if feat else t.card, MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05,
             line=None if feat else "D8DDE8")
        ink = "FFFFFF" if feat else t.ink
        text(sl, x + 0.3, 2.68, cw - 0.6, 0.6, tr["name"], 28, t.accent2 if feat else t.accent, bold=True)
        text(sl, x + 0.3, 3.25, cw - 0.6, 0.8, tr["price"], 32, ink, bold=True)
        text(sl, x + 0.3, 4.1, cw - 0.6, 1.65, tr["points"], MIN_PT, "C9D2E6" if feat else t.muted, spacing=1.0,
             after=4)
    if s.get("note"):
        rect(sl, W - M - 0.12, 6.05, 0.12, 0.42, t.accent2)
        text(sl, M, 6.0, W - 2 * M - 0.35, 0.6, s["note"], MIN_PT, t.ink)


def k_table(sl, t, s, n, total):
    bg(sl, t.light)
    header(sl, t, s, n, total)
    cols, rows = s["columns"], s["rows"]
    tw = W - 2 * M
    first = tw * (0.34 if len(cols) <= 5 else 0.27)
    cw = (tw - first) / (len(cols) - 1)
    # header row is taller by default: column names may take two lines
    rh0, rhn = s.get("header_h", 1.0), s.get("row_h", 0.66)
    y = s.get("top", 2.6)
    for ri, row in enumerate([cols] + rows):
        rh = rh0 if ri == 0 else rhn
        x = W - M
        for ci, val in enumerate(row):
            w = first if ci == 0 else cw
            x -= w
            if ri == 0:
                fill = t.dark if ci == 1 else ("E6EAF3" if ci else None)
            else:
                fill = "E8EEFF" if ci == 1 else (t.card if ri % 2 else "F0F2F7")
            if fill:
                rect(sl, x + 0.03, y, w - 0.06, rh - 0.06, fill)
            color = "FFFFFF" if (ri == 0 and ci == 1) else (t.ink if ci <= 1 or ri == 0 else t.muted)
            text(sl, x + 0.1, y, w - 0.2, rh - 0.06, val, MIN_PT, color, bold=(ri == 0 or ci == 0),
                 align="r" if ci == 0 else "ctr", anchor="m")
        y += rh
    if s.get("note"):
        text(sl, M, y + 0.1, tw, 0.6, s["note"], MIN_PT, t.muted)


def _num(v):
    try:
        return float(str(v).replace("%", "").strip())
    except ValueError:
        return None


def k_ask(sl, t, s, n, total):
    """The ask: amount, runway, milestone (headline), use of funds, then the promise, next step and contact.
    Bars are drawn ONLY from real numbers: a placeholder percentage gets no bar, so the slide never implies a
    split nobody decided."""
    bg(sl, t.light)
    header(sl, t, s, n, total)
    half = (W - 2 * M - 0.5) / 2
    xr = W - M - half
    y0 = 2.55
    if s.get("amount"):
        text(sl, xr, y0, half, 0.55, f"**סכום הגיוס:** {s['amount']}", 28, t.ink)
        y0 += 0.75
    text(sl, xr, y0, half, 0.5, "לאן הכסף הולך", MIN_PT, t.accent, bold=True)
    y = y0 + 0.6
    nums = [_num(u.get("pct")) for u in s["uses"]]
    real = all(v is not None for v in nums) and abs(sum(nums) - 100) < 0.5
    for u, v in zip(s["uses"], nums):
        text(sl, xr, y, half, 0.5, f"{u['label']}  ·  {u['pct']}", MIN_PT, t.ink)
        if real:
            rect(sl, xr, y + 0.55, half, 0.14, "E1E6F0")
            rect(sl, xr + half * (1 - v / 100), y + 0.55, half * v / 100, 0.14, t.accent)
        y += 0.95 if real else 0.7
    xl = M
    if s.get("promise"):
        rect(sl, xl, 2.55, half, 3.0, t.dark, MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
        prom = s["promise"] if isinstance(s["promise"], list) else [s["promise"]]
        text(sl, xl + 0.35, 2.75, half - 0.7, 1.3, prom, 28, "FFFFFF", bold=True, spacing=1.0)
        if s.get("next"):
            text(sl, xl + 0.35, 4.05, half - 0.7, 1.0, s["next"], MIN_PT, t.accent2, bold=True)
        if s.get("contact"):
            text(sl, xl + 0.35, 4.95, half - 0.7, 0.55, s["contact"], MIN_PT, "C9D2E6")


def k_team(sl, t, s, n, total):
    """Team: one row per person - name, role, and the ONE fact that makes them right for this (unfair advantage)."""
    bg(sl, t.light)
    header(sl, t, s, n, total)
    y = 2.6
    for m in s["team"]:
        rect(sl, M, y, W - 2 * M, 1.15, t.card, MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.08, line="D8DDE8")
        rect(sl, W - M - 1.0, y + 0.22, 0.72, 0.72, t.dark, MSO_SHAPE.OVAL)
        text(sl, W - M - 1.0, y + 0.26, 0.72, 0.62, m.get("initials", ""), MIN_PT, "FFFFFF", bold=True,
             align="ctr", anchor="m")
        text(sl, W - M - 5.0, y + 0.1, 3.8, 0.95, [f"**{m['name']}**", m["role"]], MIN_PT, t.ink, spacing=0.95)
        text(sl, M + 0.3, y + 0.1, W - 2 * M - 5.6, 0.95, m.get("edge", ""), MIN_PT, t.muted, anchor="m")
        y += 1.35


def k_finance(sl, t, s, n, total):
    """Financials: a 3-year table (customers, revenue, costs, cash flow, break-even) and a per-sale profitability
    strip that DOES the VAT arithmetic (price incl. VAT / 1.18) and leaves fees and tax as inputs."""
    k_table(sl, t, dict(s, note=None, header_h=0.62, row_h=0.6, top=2.45), n, total)
    if s.get("unit"):
        u = s["unit"]
        y = 2.45 + 0.62 + 0.6 * len(s["rows"]) + 0.35
        rect(sl, M, y, W - 2 * M, 0.85, t.dark, MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.15)
        price = _num(u.get("price_incl_vat"))
        vat = _num(u.get("vat", 18)) or 18
        net = f"{price / (1 + vat / 100):,.0f} ₪" if price else "[לאשר]"
        steps = [f"{u.get('price_incl_vat')} ₪ ללקוח", f"{net} בלי מע\"מ",
                 f"סליקה: {u.get('after_fees', '[לאשר]')}", f"מס: {u.get('after_tax', '[לאשר]')}"]
        # "·" not an arrow: Heebo has no arrow glyphs (a fallback font would appear in the PDF)
        label = "דוגמת חישוב: " if u.get("example", True) else ""
        text(sl, M + 0.25, y + 0.05, W - 2 * M - 0.5, 0.75, label + "  ·  ".join(steps), MIN_PT, "FFFFFF", anchor="m")


def k_closing(sl, t, s, n, total):
    bg(sl, t.dark)
    rect(sl, W - M - 1.2, 2.35, 1.2, 0.12, t.accent2)
    text(sl, M, 2.6, W - 2 * M, 1.8, s["headline"], 48, "FFFFFF", bold=True, spacing=1.0)
    if s.get("next"):
        text(sl, M, 4.55, W - 2 * M, 0.7, s["next"], 28, "FFFFFF", bold=True)
    text(sl, M, 5.3 if s.get("next") else 4.6, W - 2 * M, 0.8, s["contact"], MIN_PT, "C9D2E6")


KINDS = {k[2:]: v for k, v in globals().items() if k.startswith("k_")}


FIELD_NAMES = {"amount": "סכום הגיוס", "after_fees": "שיעור עמלת סליקה", "after_tax": "שיעור המס",
               "footer": "סבב וחודש", "pct": "אחוז מהגיוס", "price": "מחיר", "contact": "פרטי קשר"}


def collect_list(spec):
    """Every data point the deck still needs, slide by slide: [לאשר] markers and missing hero numbers."""
    import re as _re
    rows = []
    for n, sl in enumerate(spec["slides"], 1):
        found = []
        def walk(o, label=None):
            if isinstance(o, dict):
                if "label" in o and "value" in o and missing(o):
                    found.append(f"{o['label']}" + (f" (יעד: {o['target']})" if o.get("target") else ""))
                    return
                for k, v in o.items():
                    if k != "notes":
                        walk(v, FIELD_NAMES.get(k, label))
            elif isinstance(o, list):
                for v in o:
                    walk(v)
            elif isinstance(o, str):
                for m in _re.findall(r"\[לאשר[^\]]*\]", o):
                    what = m.strip("[]").replace("לאשר", "", 1).strip(" :")
                    found.append(what or label or _re.sub(r"\[לאשר[^\]]*\]", "___", o)[:60])
        if sl.get("rows"):          # table cells: name them by row and column, not by the bare marker
            cols = sl.get("columns", [])
            for row in sl["rows"]:
                for j, cell in enumerate(row):
                    if "[לאשר" in str(cell):
                        found.append(f"{row[0]} · {cols[j] if j < len(cols) else ''}".strip(" ·"))
            walk({k: v for k, v in sl.items() if k != "rows"})
        else:
            walk(sl)
        title = sl.get("headline") or sl.get("title", "")
        title = title if isinstance(title, str) else " ".join(title)
        for f in dict.fromkeys(found):
            rows.append((n, sl.get("kicker", title), f))
    return rows + [("-", "כללי", c) for c in spec.get("collect", [])]


def write_collect(spec, out):
    """Skeleton decks ship with a data-to-collect document (Word, RTL) next to the PPTX."""
    import doc_build as D
    d = D.new_doc()
    D.para(d, f"{spec.get('title', 'מצגת')}: נתונים לאיסוף", size=16, bold=True, font=D.FONT_HEAD, after=2)
    D.para(d, "המצגת היא שלד לעבודה: המבנה, המסרים והעיצוב מוכנים, והמספרים עוד לא. כל שורה כאן היא נתון שצריך "
              "להביא, עם מקור, לפני שמציגים למשקיע.", size=11, color=D.MUTED, after=8, line=1.25)
    rows = collect_list(spec)
    t = d.add_table(rows=1, cols=3)
    D.table_rtl(t)
    D.table_borders(t)
    D.cell_margins(t)
    for i, h in enumerate(["שקף", "נושא", "מה צריך להביא"]):
        D.cell_fill(t.rows[0].cells[i], "0E1630")
        D.cell_text(t.rows[0].cells[i], h, size=10.5, bold=True, color="FFFFFF")
    for n, topic, what in rows:
        r = t.add_row().cells
        D.cell_text(r[0], str(n), size=10.5, align="center")
        D.cell_text(r[1], topic, size=10.5)
        D.cell_text(r[2], what, size=10.5)
    D.col_widths(t, [1.5, 4.0, 11.9])
    path = os.path.splitext(out)[0] + "-data-to-collect.docx"
    d.save(path)
    return path, len(rows)


def build(spec, out):
    global MIN_PT, SKELETON
    SKELETON = spec.get("status") == "skeleton"
    if spec.get("mode") == "send":
        MIN_PT = 16
    t = Theme(spec.get("brand", {}))
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    blank = prs.slide_layouts[6]
    total = len(spec["slides"])
    for n, s in enumerate(spec["slides"], 1):
        sl = prs.slides.add_slide(blank)
        KINDS[s["kind"]](sl, t, s, n, total)
        notes(sl, s)
    prs.core_properties.title = spec.get("title", "")
    meta = {k: spec[k] for k in ("sources", "supplied") if spec.get(k)}
    if meta:
        prs.core_properties.comments = json.dumps(meta, ensure_ascii=False)
    prs.core_properties.language = "he-IL"
    prs.save(out)
    if spec.get("status") == "skeleton":
        path, k = write_collect(spec, out)
        print(f"Skeleton: {k} data points to collect -> {path}")


def to_pdf(path):
    outdir = os.path.dirname(os.path.abspath(path))
    prof = tempfile.mkdtemp()
    subprocess.run(["soffice", f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", "pdf",
                    "--outdir", outdir, path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.splitext(path)[0] + ".pdf"


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    if len(a) != 2:
        sys.exit(__doc__)
    build(json.load(open(a[0], encoding="utf-8")), a[1])
    print("PPTX:", a[1])
    if "--pdf" in sys.argv:
        print("PDF: ", to_pdf(a[1]))
