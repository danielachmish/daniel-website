#!/usr/bin/env python3
"""qa_xlsx.py <workbook.xlsx> [out_dir] [--allow 0,1] [--data-sheets "גיליון נתונים,Data"] [--target excel2019] [--no-render]

Mandatory spreadsheet QA before delivery. Recalculates a COPY headless in LibreOffice (the client's file is
never touched), then checks the computed values, not just the formulas:

  FAIL  any #REF! #DIV/0! #VALUE! #NAME? #N/A #NUM! #NULL! after recalculation, or a formula with no value
  FAIL  hard-coded numbers inside formulas (FAST: every constant lives in a labelled input cell); --allow sets
        the permitted literals (default 0 and 1)
  FAIL  a SUM total that does not equal the sum of the values it covers (recomputed in Python)
  FAIL  a model check (named range QA_Checks, or a sheet called בדיקות/Checks) that is not TRUE
  FAIL  a broken named range (#REF in its definition)
  FAIL  a typed number outside the inputs that is not styled as an input (a hidden hard-code), or a formula
        cell styled like an input, or two different input styles
  FAIL  a Hebrew sheet that is not right-to-left
  WARN  protected sheet with locked input cells / unprotected sheet with formulas; input without data validation
  WARN  formulas that point at empty cells; volatile OFFSET/INDIRECT; functions missing in --target Excel version

Writes <out_dir>/recalculated.xlsx and qa_xlsx_report.txt, and (unless --no-render) a PDF + PNG of every page
via LibreOffice/pdftoppm, which you must OPEN and LOOK at (RTL, cut columns, ####, readable dashboard).
Exit code 1 if any FAIL.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import openpyxl
    from openpyxl.utils import get_column_letter, range_boundaries
except ImportError:
    sys.exit("openpyxl missing: pip install openpyxl")

ERRORS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!", "Err:", "#ERR")
NEW_FUNCS = ["XLOOKUP", "XMATCH", "FILTER", "UNIQUE", "SORT", "SORTBY", "SEQUENCE", "LET", "LAMBDA", "RANDARRAY",
             "TEXTSPLIT", "VSTACK", "HSTACK", "TAKE", "DROP", "CHOOSECOLS", "CHOOSEROWS", "TOCOL", "TOROW"]
HEB = re.compile(r"[֐-׿]")
MACRO = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE script:module PUBLIC "-//OpenOffice.org//DTD OfficeDocument 1.0//EN" "module.dtd">
<script:module xmlns:script="http://openoffice.org/2000/script" script:name="Module1" script:language="StarBasic">
Sub RecalcSave
  ThisComponent.calculateAll()
  ThisComponent.store()
  ThisComponent.close(True)
End Sub
</script:module>"""

results = []
def P(m): results.append(("PASS", m))
def W(m): results.append(("WARN", m))
def F(m): results.append(("FAIL", m))


def args():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        sys.exit(__doc__)
    opts = {"allow": {0.0, 1.0}, "data": set(), "target": None, "render": True}
    pos = []
    i = 0
    while i < len(a):
        if a[i] == "--allow":
            opts["allow"] = {float(x) for x in a[i + 1].split(",") if x.strip()}; i += 2
        elif a[i] == "--data-sheets":
            opts["data"] = {x.strip() for x in a[i + 1].split(",")}; i += 2
        elif a[i] == "--target":
            opts["target"] = a[i + 1].lower(); i += 2
        elif a[i] == "--no-render":
            opts["render"] = False; i += 1
        else:
            pos.append(a[i]); i += 1
    src = Path(pos[0]).resolve()
    out = Path(pos[1] if len(pos) > 1 else "./qa_xlsx_out").resolve()
    return src, out, opts


def recalc(src, out):
    """Recalculate a copy in LibreOffice with a throwaway profile and a calculateAll() macro."""
    if not shutil.which("soffice"):
        return None, "LibreOffice (soffice) not installed: values were NOT recalculated"
    out.mkdir(parents=True, exist_ok=True)
    dst = out / "recalculated.xlsx"
    shutil.copyfile(src, dst)
    with tempfile.TemporaryDirectory(prefix="qa_xlsx_lo_") as prof:
        url = Path(prof).as_uri()
        subprocess.run(["soffice", "--headless", "--terminate_after_init", f"-env:UserInstallation={url}"],
                       capture_output=True, timeout=120)
        mdir = Path(prof) / "user" / "basic" / "Standard"
        if not mdir.exists():
            return None, "LibreOffice profile not created: values were NOT recalculated"
        (mdir / "Module1.xba").write_text(MACRO)
        before = dst.stat().st_mtime_ns
        r = subprocess.run(["timeout", "180", "soffice", "--headless", "--norestore", f"-env:UserInstallation={url}",
                            "vnd.sun.star.script:Standard.Module1.RecalcSave?language=Basic&location=application", str(dst)],
                           capture_output=True, text=True)
        if dst.stat().st_mtime_ns == before:
            return None, f"LibreOffice did not save the recalculated copy (rc={r.returncode} {r.stderr.strip()[:200]})"
    return dst, None


def strip_formula(f):
    s = re.sub(r'"[^"]*"', '""', f)                       # string literals
    s = re.sub(r"'[^']*'!", "", s)                         # quoted sheet names
    s = re.sub(r"\b[A-Za-z_][\w.]*!", "", s)               # plain sheet names
    s = re.sub(r"\$?[A-Za-z]{1,3}\$?\d+", " REF ", s)      # A1 / $A$1 refs
    s = re.sub(r"\$?\b\d+:\$?\d+\b", " REF ", s)          # whole-row refs 3:3
    s = re.sub(r"[A-Za-z_\\][\w.]*", " NAME ", s)          # functions and defined names
    return s


def literals(f):
    s = strip_formula(f)
    return [m.group(0) for m in re.finditer(r"(?<![\w.])\d+(?:\.\d+)?(?:[eE][+-]?\d+)?%?", s)]


def num(x):
    return float(x[:-1]) / 100 if x.endswith("%") else float(x)


def style_sig(c):
    fill = c.fill.fgColor.rgb if c.fill and c.fill.fill_type == "solid" else None
    font = c.font.color.rgb if c.font and c.font.color is not None and c.font.color.type == "rgb" else None
    return (str(fill), str(font))


def refs_in(f, here):
    """Yield (sheet, coord) for simple single-cell refs (ranges are skipped)."""
    s = re.sub(r'"[^"]*"', '""', f)
    for m in re.finditer(r"(?:'((?:[^']|'')+)'|([A-Za-z_][\w.]*))?!?(\$?[A-Z]{1,3}\$?\d+)(?![\d:(])", s):
        full = m.group(0)
        if ":" in s[max(0, m.start() - 1):m.start()]:
            continue
        sheet = (m.group(1) or m.group(2)) if "!" in full else here
        if sheet and "!" not in full:
            sheet = here
        yield (sheet.replace("''", "'") if sheet else here), m.group(3).replace("$", "")


def main():
    src, out, opts = args()
    if not src.exists():
        sys.exit(f"no such file: {src}")
    out.mkdir(parents=True, exist_ok=True)
    print(f"QA {src}")
    wf = openpyxl.load_workbook(src)                       # formulas
    rc, err = recalc(src, out)
    if err:
        F(err)
        wv = None
    else:
        wv = openpyxl.load_workbook(rc, data_only=True)   # computed values
        P(f"recalculated headless in LibreOffice -> {rc}")

    n_formulas = 0
    hard = []
    errs = []
    empty_val = []
    volatile = []
    newfn = []
    dangling = []
    const_cells = []      # (sheet, coord, sig, cell)
    formula_sigs = {}
    sum_mismatch = []
    sum_checked = 0

    for ws in wf.worksheets:
        vs = wv[ws.title] if wv else None
        hebrew = False
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str) and HEB.search(v):
                    hebrew = True
                if isinstance(v, str) and v.startswith("="):
                    n_formulas += 1
                    f = v
                    bad = [x for x in literals(f) if num(x) not in opts["allow"]]
                    if bad:
                        hard.append(f"{ws.title}!{c.coordinate} {f[:80]}  <- {', '.join(sorted(set(bad)))}")
                    up = f.upper()
                    if re.search(r"\b(OFFSET|INDIRECT)\(", up):
                        volatile.append(f"{ws.title}!{c.coordinate}")
                    if opts["target"] in ("excel2019", "excel2016", "excel2013"):
                        used = [fn for fn in NEW_FUNCS if re.search(rf"\b(_xlfn\.)?{fn}\(", up)]
                        if used:
                            newfn.append(f"{ws.title}!{c.coordinate} {','.join(used)}")
                    formula_sigs.setdefault(style_sig(c), []).append(f"{ws.title}!{c.coordinate}")
                    for sh, coord in refs_in(f, ws.title):
                        if sh in wf.sheetnames:
                            if wf[sh][coord].value is None:
                                dangling.append(f"{ws.title}!{c.coordinate} -> {sh}!{coord}")
                    if vs is not None:
                        cv = vs[c.coordinate].value
                        if cv is None:
                            empty_val.append(f"{ws.title}!{c.coordinate}")
                        elif isinstance(cv, str) and cv.startswith(ERRORS):
                            errs.append(f"{ws.title}!{c.coordinate}={cv}  ({f[:70]})")
                        m = re.fullmatch(r"=SUM\(\$?([A-Z]{1,3})\$?(\d+):\$?([A-Z]{1,3})\$?(\d+)\)", f.replace(" ", ""), re.I)
                        if m and isinstance(cv, (int, float)):
                            c1, r1, c2, r2 = range_boundaries(f"{m.group(1)}{m.group(2)}:{m.group(3)}{m.group(4)}")
                            tot = 0.0
                            for rr in range(r1, r2 + 1):
                                for cc in range(c1, c2 + 1):
                                    x = vs.cell(row=rr, column=cc).value
                                    if isinstance(x, (int, float)) and not isinstance(x, bool):
                                        tot += x
                            sum_checked += 1
                            # a total that stops one cell short of its block (the classic "forgot December")
                            nxt = []
                            if r1 == r2:
                                nxt = [(r1, c2 + 1), (r1, c1 - 1)]
                            elif c1 == c2:
                                nxt = [(r2 + 1, c1), (r1 - 1, c1)]
                            for (nr, nc) in nxt:
                                if nr < 1 or nc < 1 or (nr, nc) == (c.row, c.column):
                                    continue
                                nb = ws.cell(row=nr, column=nc).value
                                hdr_like = isinstance(nb, str) and not nb.startswith("=")
                                if nb is not None and not hdr_like and nc != c.column:
                                    sum_mismatch.append(f"{ws.title}!{c.coordinate} {f} stops short: "
                                                        f"{get_column_letter(nc)}{nr} next to the range is not included")
                            if abs(tot - cv) > max(0.01, abs(tot) * 1e-9):
                                sum_mismatch.append(f"{ws.title}!{c.coordinate} shows {cv} but cells sum to {tot}")
                elif isinstance(v, (int, float)) and not isinstance(v, bool) and ws.title not in opts["data"]:
                    const_cells.append((ws.title, c.coordinate, style_sig(c), c))
                elif isinstance(v, str) and v.startswith(ERRORS):
                    errs.append(f"{ws.title}!{c.coordinate}={v} (typed)")
        if hebrew:
            (P if ws.sheet_view.rightToLeft else F)(f"sheet '{ws.title}' has Hebrew and is {'RTL' if ws.sheet_view.rightToLeft else 'NOT right-to-left'}")

    P(f"{n_formulas} formulas scanned")
    (F(f"{len(errs)} error value(s): " + " | ".join(errs[:8])) if errs else P("no #REF!/#DIV/0!/#VALUE!/#NAME?/#N/A after recalculation")) if wv else None
    if wv and empty_val:
        F(f"{len(empty_val)} formula(s) with no computed value: {', '.join(empty_val[:8])}")
    (F(f"{len(hard)} formula(s) with hard-coded numbers (move each to a labelled input): " + " | ".join(hard[:8]))
     if hard else P(f"no hard-coded numbers inside formulas (allowed literals: {sorted(opts['allow'])})"))
    if wv:
        (F(f"{len(sum_mismatch)} SUM total(s) do not match their cells: " + " | ".join(sum_mismatch[:5]))
         if sum_mismatch else P(f"{sum_checked} SUM totals cross-checked against the cells they cover"))

    # ---- named ranges & model checks ----
    names = dict(wf.defined_names.items())
    all_f = " ".join(c.value for ws in wf.worksheets for r in ws.iter_rows() for c in r
                     if isinstance(c.value, str) and c.value.startswith("="))
    def single_cell(d):
        try:
            dest = list(d.destinations)
            return len(dest) == 1 and ":" not in dest[0][1]
        except Exception:
            return False
    unused = [n for n, d in names.items() if not n.startswith(("QA_", "_xlnm")) and single_cell(d)
              and not re.search(rf"(?<![\w.]){re.escape(n)}(?![\w.(])", all_f)]
    if unused:
        W(f"{len(unused)} named input(s)/row(s) never used by any formula (dead assumption or a formula that forgot it): {', '.join(unused[:10])}")
    broken = [n for n, d in names.items() if "#REF" in (d.attr_text or "")]
    (F(f"broken named ranges: {', '.join(broken)}") if broken else P(f"{len(names)} named ranges, none broken"))
    check_cells = []
    if "QA_Checks" in names:
        for sh, coord in names["QA_Checks"].destinations:
            c1, r1, c2, r2 = range_boundaries(coord.replace("$", ""))
            for r in range(r1, r2 + 1):
                for cc in range(c1, c2 + 1):
                    check_cells.append((sh, r, cc))
    else:
        for ws in wf.worksheets:
            if ws.title.strip().lower() in ("בדיקות", "checks", "check", "בדיקה"):
                for row in ws.iter_rows():
                    for c in row:
                        if isinstance(c.value, str) and c.value.startswith("="):
                            check_cells.append((ws.title, c.row, c.column))
    if not check_cells:
        W("no model checks found (named range QA_Checks or a sheet named בדיקות/Checks). FAST models build checks with the model")
    elif wv:
        bad = []
        for sh, r, cc in check_cells:
            val = wv[sh].cell(row=r, column=cc).value
            if val is not True:
                label = wf[sh].cell(row=r, column=1).value
                bad.append(f"{sh}!{get_column_letter(cc)}{r}={val} ({label})")
        (F(f"{len(bad)} model check(s) not TRUE: " + " | ".join(bad[:6])) if bad else P(f"all {len(check_cells)} model checks TRUE"))

    # ---- inputs styled distinctly ----
    if const_cells:
        sigs = {}
        for t in const_cells:
            sigs.setdefault(t[2], []).append(t)
        main_sig, main_cells = max(sigs.items(), key=lambda kv: len(kv[1]))
        others = [t for s, ts in sigs.items() if s != main_sig for t in ts]
        if main_sig == ("None", "None") or main_sig[0] in ("None", "00000000"):
            F(f"typed numbers ({len(const_cells)}) have no distinct input style (fill). Inputs must look different from calculations")
        else:
            P(f"{len(main_cells)} input cells share one input style (fill {main_sig[0]}, font {main_sig[1]})")
        if others:
            F(f"{len(others)} typed number(s) not styled as inputs (hidden hard-codes or a second input style): "
              + ", ".join(f"{s}!{c}" for s, c, _, _ in others[:10]))
        clash = formula_sigs.get(main_sig, [])
        if clash and main_sig[0] not in ("None", "00000000"):
            F(f"{len(clash)} formula cell(s) styled exactly like inputs (user will type over them): {', '.join(clash[:8])}")
        in_sheets = sorted({t[0] for t in main_cells})
        if len(in_sheets) > 1:
            W(f"input cells spread over {len(in_sheets)} sheets ({', '.join(in_sheets)}): FAST keeps assumptions in one place")
        # protection / validation
        dv_cells = {}
        for ws in wf.worksheets:
            for dv in ws.data_validations.dataValidation:
                for rng in str(dv.sqref).split():
                    c1, r1, c2, r2 = range_boundaries(rng)
                    for r in range(r1, r2 + 1):
                        for cc in range(c1, c2 + 1):
                            dv_cells[(ws.title, r, cc)] = True
        novalid = [f"{s}!{c}" for s, c, _, cell in main_cells if (s, cell.row, cell.column) not in dv_cells]
        (W(f"{len(novalid)} input cell(s) without data validation: {', '.join(novalid[:8])}") if novalid
         else P("every input cell has data validation"))
        locked_inputs = [f"{s}!{c}" for s, c, _, cell in main_cells if wf[s].protection.sheet and cell.protection.locked]
        (W(f"{len(locked_inputs)} input cell(s) locked on a protected sheet (client cannot type): {', '.join(locked_inputs[:8])}")
         if locked_inputs else P("input cells are unlocked"))
    else:
        W("no typed numbers found: is there an inputs area at all?")
    unprot = [ws.title for ws in wf.worksheets if not ws.protection.sheet and any(
        isinstance(c.value, str) and c.value.startswith("=") for r in ws.iter_rows() for c in r)]
    (W(f"sheets with formulas but no protection (formulas can be overwritten): {', '.join(unprot)}") if unprot
     else P("every sheet with formulas is protected"))
    if dangling:
        W(f"{len(dangling)} formula reference(s) to EMPTY cells (often a wrong row/column): " + " | ".join(dangling[:6]))
    else:
        P("no formula points at an empty cell")
    if volatile:
        W(f"volatile OFFSET/INDIRECT in {len(volatile)} cell(s) (fragile, slow; FAST discourages): {', '.join(volatile[:6])}")
    if newfn:
        F(f"functions missing in {opts['target']}: " + " | ".join(newfn[:6]))

    # ---- render for eyes ----
    if opts["render"] and rc and shutil.which("soffice"):
        # render the ORIGINAL file (LibreOffice computes it on load); the re-saved copy can lose chart caches
        with tempfile.TemporaryDirectory(prefix="qa_xlsx_pdf_") as prof:
            subprocess.run(["soffice", "--headless", f"-env:UserInstallation={Path(prof).as_uri()}", "--convert-to", "pdf",
                            "--outdir", str(out), str(src)], capture_output=True, timeout=180)
        pdf = out / (src.stem + ".pdf")
        if pdf.exists() and shutil.which("pdftoppm"):
            subprocess.run(["pdftoppm", "-r", "70", "-png", str(pdf), str(out / "page")], capture_output=True)
            pages = sorted(out.glob("page-*.png"))
            P(f"rendered {len(pages)} page(s): {out}/page-*.png  <- OPEN AND LOOK (RTL, #### cut numbers, dashboard)")
        else:
            W("could not render PDF/PNG pages (LibreOffice or pdftoppm missing)")

    lines = [f"{s:5} {m}" for s, m in results]
    nf = sum(1 for s, _ in results if s == "FAIL")
    nw = sum(1 for s, _ in results if s == "WARN")
    report = "\n".join(lines) + f"\n\n{nf} FAIL, {nw} WARN\n"
    (out / "qa_xlsx_report.txt").write_text(report, encoding="utf-8")
    print("\n=== SUMMARY ===\n" + report)
    print("NEXT: check 3 numbers by hand against the inputs, add a row / change an input and confirm the outputs and")
    print("checks move as expected, and LOOK at the rendered pages. A script cannot judge whether the model is right.")
    sys.exit(1 if nf else 0)


if __name__ == "__main__":
    main()
