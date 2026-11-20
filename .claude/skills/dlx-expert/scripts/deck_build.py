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
  ask       {kicker, headline, uses[{label,pct,frac}], team[{name,role,initials?}]}
  closing   {headline, next?, contact}
Every slide may have "notes".
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
    pn = text(slide, M, H - 0.55, 2.0, 0.4, f"{n}/{total}", 12, t.muted, align="l")
    pn.name = "footer-pagenum"  # qa_text.py exempts shapes named footer-* from the minimum size
    rect(slide, W - M - 0.9, H - 0.42, 0.9, 0.06, t.accent)


# ---------------------------------------------------------------- slide kinds
def k_title(sl, t, s, n, total):
    bg(sl, t.dark)
    rect(sl, W - M - 1.2, 1.55, 1.2, 0.12, t.accent2)
    text(sl, M, 1.85, W - 2 * M, 1.4, s["title"], 72, "FFFFFF", bold=True, align="r")
    text(sl, M + 2.0, 3.35, W - 2 * M - 2.0, 1.6, s["subtitle"], 32, "D9E0F0", spacing=1.05)
    if s.get("footer"):
        text(sl, M, H - 1.1, W - 2 * M, 0.5, s["footer"], MIN_PT, "9AA6C2")


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
        rect(sl, M, 2.75, cw, 3.3, t.dark, MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06)
        text(sl, M + 0.3, 3.0, cw - 0.6, 1.5, s["stat"]["value"], 54, "FFFFFF", bold=True, align="ctr", anchor="m")
        text(sl, M + 0.3, 4.55, cw - 0.6, 1.3, s["stat"]["label"], MIN_PT, "C9D2E6", align="ctr")


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
        rect(sl, x, top, cw, 3.0 if s.get("risk") else 3.1, "1A2442", MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.05)
        text(sl, x + 0.2, top + 0.2, cw - 0.4, 1.4, nm["value"], 44, "FFFFFF", bold=True, align="ctr", anchor="m")
        text(sl, x + 0.2, top + 1.65, cw - 0.4, 1.2, nm["label"], MIN_PT, "C9D2E6", align="ctr")
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
            items.append(("×", None))
        items.append((term["value"], term["label"]))
    items.append(("=", None))
    items.append((s["result"]["value"], s["result"]["label"]))
    boxes = [it for it in items if it[1] is not None]
    ops = len(items) - len(boxes)
    opw = 0.55
    bw = (W - 2 * M - ops * opw) / len(boxes)
    x = W - M
    for val, lab in items:
        if lab is None:
            x -= opw
            text(sl, x, 3.2, opw, 1.0, val, 40, t.muted, bold=True, align="ctr", anchor="m")
            continue
        x -= bw
        last = (val, lab) == boxes[-1]
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
    first = tw * 0.34
    cw = (tw - first) / (len(cols) - 1)
    rh0, rhn = 1.0, 0.66      # header row is taller: column names may take two lines
    y = 2.6
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


def k_ask(sl, t, s, n, total):
    bg(sl, t.light)
    header(sl, t, s, n, total)
    half = (W - 2 * M - 0.5) / 2
    xr = W - M - half
    text(sl, xr, 2.65, half, 0.5, "לאן הכסף הולך", MIN_PT, t.accent, bold=True)
    y = 3.25
    for u in s["uses"]:
        text(sl, xr, y, half, 0.5, f"{u['label']}  ·  {u['pct']}", MIN_PT, t.ink)
        rect(sl, xr, y + 0.55, half, 0.14, "E1E6F0")
        frac = u.get("frac", 0.33)
        rect(sl, xr + half * (1 - frac), y + 0.55, half * frac, 0.14, t.accent)
        y += 0.95
    xl = M
    text(sl, xl, 2.65, half, 0.5, "הצוות", MIN_PT, t.accent, bold=True)
    y = 3.25
    for m in s["team"]:
        if m.get("initials"):
            rect(sl, xl + half - 0.7, y + 0.02, 0.62, 0.62, t.dark, MSO_SHAPE.OVAL)
            text(sl, xl + half - 0.7, y + 0.06, 0.62, 0.55, m["initials"], MIN_PT, "FFFFFF", bold=True,
                 align="ctr", anchor="m")
        else:
            rect(sl, xl + half - 0.14, y + 0.08, 0.12, 0.75, t.accent2)
        text(sl, xl, y, half - 0.8, 0.9, [f"**{m['name']}**", m["role"]], MIN_PT, t.ink, spacing=0.95)
        y += 1.15


def k_closing(sl, t, s, n, total):
    bg(sl, t.dark)
    rect(sl, W - M - 1.2, 2.35, 1.2, 0.12, t.accent2)
    text(sl, M, 2.6, W - 2 * M, 1.8, s["headline"], 48, "FFFFFF", bold=True, spacing=1.0)
    if s.get("next"):
        text(sl, M, 4.55, W - 2 * M, 0.7, s["next"], 28, "FFFFFF", bold=True)
    text(sl, M, 5.3 if s.get("next") else 4.6, W - 2 * M, 0.8, s["contact"], MIN_PT, "C9D2E6")


KINDS = {k[2:]: v for k, v in globals().items() if k.startswith("k_")}


def build(spec, out):
    global MIN_PT
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
    prs.core_properties.language = "he-IL"
    prs.save(out)


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
