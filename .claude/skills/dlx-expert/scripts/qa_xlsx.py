#!/usr/bin/env python3
"""qa_xlsx.py <workbook.xlsx> [out_dir] [--allow 0,1] [--data-sheets "גיליון נתונים,Data"] [--target excel2019] [--mutate N] [--mutate-warn] [--no-render]

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
  FAIL  a formula that breaks its row's pattern (FAST: one formula per row; only a roll-forward row's opening periods differ)
  FAIL  a constant hidden in a named range; input without data validation; locked input; unprotected formula sheet
  FAIL  mutation test: a calculation row where a typed-over number is noticed by NO model check (default: every row;
        --mutate N samples N rows, --mutate 0 skips; --mutate-warn downgrades to WARN for a client file you only fix)
  WARN  IFERROR/IFNA that can hide errors; some mutations not noticed by the checks
  WARN  formulas that point at empty cells; volatile OFFSET/INDIRECT; functions missing in --target Excel version

Writes <out_dir>/recalculated.xlsx and qa_xlsx_report.txt, and (unless --no-render) a PDF + PNG of every page
via LibreOffice/pdftoppm, which you must OPEN and LOOK at (RTL, cut columns, ####, readable dashboard).
Exit code 1 if any FAIL.

NOT covered (check by hand, and say so): a value PASTED into an input bypasses data validation in Excel (the model's own
range checks are what catch it); conditional-format number formats; a named range that points at the wrong but valid
cell (only duplicates are flagged); whether the business logic itself is right (that is the 3 hand checks + the critic).
"""
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import openpyxl
    from openpyxl.formula import Tokenizer
    from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries
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
    opts = {"allow": {0.0, 1.0}, "data": set(), "target": None, "render": True, "mutate": -1, "mutate_warn": False}
    pos = []
    i = 0
    while i < len(a):
        if a[i] == "--allow":
            opts["allow"] = {float(x) for x in a[i + 1].split(",") if x.strip()}; i += 2
        elif a[i] == "--data-sheets":
            opts["data"] = {x.strip() for x in a[i + 1].split(",")}; i += 2
        elif a[i] == "--target":
            opts["target"] = a[i + 1].lower(); i += 2
        elif a[i] == "--mutate":
            opts["mutate"] = int(a[i + 1]); i += 2
        elif a[i] == "--mutate-warn":
            opts["mutate_warn"] = True; i += 1
        elif a[i] == "--no-render":
            opts["render"] = False; i += 1
        else:
            pos.append(a[i]); i += 1
    src = Path(pos[0]).resolve()
    out = Path(pos[1] if len(pos) > 1 else "./qa_xlsx_out").resolve()
    return src, out, opts


class LO:
    """One throwaway LibreOffice profile with a calculateAll()+store() macro, reused for every recalculation."""
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="qa_xlsx_lo_")
        self.url = Path(self.tmp.name).as_uri()
        subprocess.run(["soffice", "--headless", "--terminate_after_init", f"-env:UserInstallation={self.url}"],
                       capture_output=True, timeout=120)
        mdir = Path(self.tmp.name) / "user" / "basic" / "Standard"
        self.ok = mdir.exists()
        if self.ok:
            (mdir / "Module1.xba").write_text(MACRO)

    def recalc(self, path):
        before = path.stat().st_mtime_ns
        r = subprocess.run(["timeout", "180", "soffice", "--headless", "--norestore", f"-env:UserInstallation={self.url}",
                            "vnd.sun.star.script:Standard.Module1.RecalcSave?language=Basic&location=application", str(path)],
                           capture_output=True, text=True)
        return path.stat().st_mtime_ns != before, r


def recalc(src, out, lo):
    """Recalculate a COPY of the workbook (the client's file is never touched)."""
    if lo is None or not lo.ok:
        return None, "LibreOffice (soffice) missing or profile not created: values were NOT recalculated"
    out.mkdir(parents=True, exist_ok=True)
    dst = out / "recalculated.xlsx"
    shutil.copyfile(src, dst)
    saved, r = lo.recalc(dst)
    if not saved:
        return None, f"LibreOffice did not save the recalculated copy (rc={r.returncode} {r.stderr.strip()[:200]})"
    return dst, None


A1 = re.compile(r"^(\$?)([A-Za-z]{1,3})(\$?)(\d+)$")


def r1c1(formula, row, col):
    """Formula with every A1 reference rewritten relative to (row, col): the FAST 'one formula per row' fingerprint."""
    try:
        toks = Tokenizer(formula).items
    except Exception:
        return formula
    out = []
    for t in toks:
        if t.type == "OPERAND" and t.subtype == "RANGE":
            v = t.value
            sheet = ""
            if "!" in v:
                sheet, v = v.rsplit("!", 1)
                sheet += "!"
            parts = []
            for ref in v.split(":"):
                m = A1.match(ref)
                if not m:
                    parts.append(ref)
                    continue
                c = column_index_from_string(m.group(2).upper())
                r = int(m.group(4))
                rs = f"R{r}" if m.group(3) else f"R[{r - row}]"
                cs = f"C{c}" if m.group(1) else f"C[{c - col}]"
                parts.append(rs + cs)
            out.append(sheet + ":".join(parts))
        else:
            out.append(t.value)
    return "".join(out)


def same_row_refs(formula, row):
    """(n_cells, n_refs) of references that point into the formula's own row on the same sheet."""
    cells, refs = 0, 0
    try:
        toks = Tokenizer(formula).items
    except Exception:
        return 0, 0
    for t in toks:
        if t.type == "OPERAND" and t.subtype == "RANGE" and "!" not in t.value:
            ends = [A1.match(x) for x in t.value.split(":")]
            if ends and all(ends):
                rows = [int(e.group(4)) for e in ends]
                if all(r == row for r in rows):
                    refs += 1
                    cs = [column_index_from_string(e.group(2).upper()) for e in ends]
                    cells += abs(cs[-1] - cs[0]) + 1
    return cells, refs


def strip_formula(f):
    s = re.sub(r'"[^"]*"', '""', f)                       # string literals
    s = re.sub(r"'[^']*'!", "", s)                         # quoted sheet names
    s = re.sub(r"\b[A-Za-z_][\w.]*!", "", s)               # plain sheet names
    s = re.sub(r"\$?[A-Za-z]{1,3}\$?\d+", " REF ", s)      # A1 / $A$1 refs
    s = re.sub(r"\$?\b\d+:\$?\d+\b", " REF ", s)          # whole-row refs 3:3
    s = re.sub(r"[A-Za-z_\\][\w.]*", " NAME ", s)          # functions and defined names
    return s


def short_sums(ws, c, f):
    """Every SUM(range) over one row or one column whose next cell (a number or formula, not referenced elsewhere in the
    same formula, not the cell itself, not a label) is left out: the classic "forgot December" / "forgot the last cost"."""
    out = []
    try:
        toks = Tokenizer(f).items
    except Exception:
        return out
    refs = set()
    for t in toks:
        if t.type == "OPERAND" and t.subtype == "RANGE" and "!" not in t.value:
            for part in t.value.replace("$", "").split(":"):
                if A1.match(part):
                    refs.add(part.upper())
    for k, t in enumerate(toks):
        if t.type == "FUNC" and t.subtype == "OPEN" and t.value.upper() == "SUM(" and k + 1 < len(toks):
            nx = toks[k + 1]
            if nx.type != "OPERAND" or nx.subtype != "RANGE" or "!" in nx.value or ":" not in nx.value:
                continue
            try:
                c1, r1, c2, r2 = range_boundaries(nx.value.replace("$", ""))
            except Exception:
                continue
            if r1 == r2:
                nbrs = [(r1, c2 + 1), (r1, c1 - 1)]
            elif c1 == c2:
                nbrs = [(r2 + 1, c1), (r1 - 1, c1)]
            else:
                continue
            for nr, nc in nbrs:
                if nr < 1 or nc < 1 or (nr, nc) == (c.row, c.column):
                    continue
                coord = f"{get_column_letter(nc)}{nr}"
                nb = ws.cell(row=nr, column=nc).value
                if nb is None or (isinstance(nb, str) and not nb.startswith("=")) or coord in refs:
                    continue
                if r1 == r2 and nc < c.column and nr == c.row:   # the row-total column itself, left of the periods
                    continue
                out.append(f"{ws.title}!{c.coordinate} {f[:60]} stops short: {coord} next to {nx.value} is not included")
    return out


def literal_tricks(f):
    """Numbers smuggled past the literal check: a number inside a string ("0.4") used in arithmetic, or arithmetic made
    only of allowed literals ((1+1) = 2)."""
    out = []
    try:
        toks = [t for t in Tokenizer(f).items if t.type != "WHITE-SPACE"]
    except Exception:
        return out
    for k, t in enumerate(toks):
        if t.type == "OPERAND" and t.subtype == "TEXT":
            inner = t.value.strip('"')
            if re.fullmatch(r"-?\d+(\.\d+)?%?", inner):
                prev = toks[k - 1] if k else None
                nxt = toks[k + 1] if k + 1 < len(toks) else None
                if (prev is not None and prev.type in ("OPERATOR-INFIX", "OPERATOR-PREFIX") and prev.value in "+-*/^") or \
                   (nxt is not None and nxt.type == "OPERATOR-INFIX" and nxt.value in "+-*/^") or \
                   (prev is not None and prev.type == "FUNC" and prev.value.upper() in ("VALUE(", "N(", "NUMBERVALUE(", "INT(", "ABS(")):
                    out.append(f'number hidden in a string {t.value}')
        if t.type == "FUNC" and t.value.upper() in ("LEN(", "CODE(", "UNICODE(", "LENB(") and k + 1 < len(toks) and \
           toks[k + 1].type == "OPERAND" and toks[k + 1].subtype == "TEXT":
            out.append(f"constant made from a string {t.value}{toks[k + 1].value})")
        if t.type == "OPERAND" and t.subtype == "LOGICAL":
            prev = toks[k - 1] if k else None
            nxt = toks[k + 1] if k + 1 < len(toks) else None
            if (prev is not None and prev.type in ("OPERATOR-INFIX", "OPERATOR-PREFIX") and prev.value in "+-*/^") or \
               (nxt is not None and nxt.type == "OPERATOR-INFIX" and nxt.value in "+-*/^"):
                out.append(f"TRUE/FALSE used as a number ({t.value})")
        if t.type == "FUNC" and t.value.upper() in ("COLUMNS(", "ROWS(") and k + 1 < len(toks) and \
           toks[k + 1].type == "OPERAND" and toks[k + 1].subtype == "RANGE" and "$" in toks[k + 1].value:
            out.append(f"constant counted from a fixed range {t.value}{toks[k + 1].value})")
        if t.type == "OPERAND" and t.subtype == "NUMBER" and k + 2 < len(toks):
            if toks[k + 1].type == "OPERATOR-INFIX" and toks[k + 1].value in "+-*/^" and \
               toks[k + 2].type == "OPERAND" and toks[k + 2].subtype == "NUMBER":
                out.append(f"constant arithmetic {t.value}{toks[k + 1].value}{toks[k + 2].value}")
    return out


def literals(f):
    try:
        return [t.value for t in Tokenizer(f).items if t.type == "OPERAND" and t.subtype == "NUMBER"]
    except Exception:
        s2 = strip_formula(f)
        return [m.group(0) for m in re.finditer(r"(?<![\w.])\d+(?:\.\d+)?(?:[eE][+-]?\d+)?%?", s2)]


def num(x):
    try:
        return float(x[:-1]) / 100 if x.endswith("%") else float(x)
    except ValueError:
        return float("nan")


def style_sig(c):
    fill = c.fill.fgColor.rgb if c.fill and c.fill.fill_type == "solid" else None
    font = c.font.color.rgb if c.font and c.font.color is not None and c.font.color.type == "rgb" else None
    return (str(fill), str(font))


def refs_in(f, here):
    """Yield (sheet, coord) for simple single-cell refs (ranges are skipped)."""
    s = re.sub(r'"[^"]*"', '""', f)
    for m in re.finditer(r"(?<![\d.])(?:'((?:[^']|'')+)'|([A-Za-z_][\w.]*))?!?(\$?[A-Z]{1,3}\$?\d+)(?![\d:(])", s):
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
    lo = LO() if shutil.which("soffice") else None
    rc, err = recalc(src, out, lo)
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
    iferr = []
    frozen = []           # a number typed as text where results are shown (a conclusion that will not update)
    # a results sheet: has formulas and no unlocked (input) cells; inputs, notes and how-to sheets are not checked
    results_sheet = {w.title: w.title not in opts["data"]
                     and any(isinstance(x.value, str) and x.value.startswith("=") for r_ in w.iter_rows() for x in r_)
                     and not any(x.value is not None and not x.protection.locked for r_ in w.iter_rows() for x in r_)
                     for w in wf.worksheets}
    rowmap = {}           # (sheet,row) -> [(col, r1c1, formula, coord)]

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
                    if re.search(r"\bIFERROR\(|\bIFNA\(", up):
                        iferr.append(f"{ws.title}!{c.coordinate}")
                    rowmap.setdefault((ws.title, c.row), []).append((c.column, r1c1(f, c.row, c.column), f, c.coordinate))
                    if re.search(r"\b(OFFSET|INDIRECT)\(", up):
                        volatile.append(f"{ws.title}!{c.coordinate}")
                    if opts["target"] in ("excel2019", "excel2016", "excel2013"):
                        used = [fn for fn in NEW_FUNCS if re.search(rf"\b(_xlfn\.)?{fn}\(", up)]
                        if used:
                            newfn.append(f"{ws.title}!{c.coordinate} {','.join(used)}")
                    formula_sigs.setdefault(style_sig(c), []).append(f"{ws.title}!{c.coordinate}")
                    for msg in short_sums(ws, c, f):
                        sum_mismatch.append(msg)
                    for msg in literal_tricks(f):
                        hard.append(f"{ws.title}!{c.coordinate} {f[:80]}  <- {msg}")
                    for sh, coord in refs_in(f, ws.title):
                        if sh in wf.sheetnames:
                            if wf[sh][coord].value is None and wf[sh][coord].protection.locked:   # blank unlocked = input to fill
                                dangling.append(f"{ws.title}!{c.coordinate} -> {sh}!{coord}")
                    if vs is not None:
                        cv = vs[c.coordinate].value
                        if cv is None and '""' not in f:   # a formula that may legitimately return "" (blank)
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
                            if abs(tot - cv) > max(0.01, abs(tot) * 1e-9):
                                sum_mismatch.append(f"{ws.title}!{c.coordinate} shows {cv} but cells sum to {tot}")
                elif isinstance(v, (int, float)) and not isinstance(v, bool) and ws.title not in opts["data"]:
                    const_cells.append((ws.title, c.coordinate, style_sig(c), c))
                elif isinstance(v, str) and v.startswith(ERRORS):
                    errs.append(f"{ws.title}!{c.coordinate}={v} (typed)")
                elif isinstance(v, str) and c.column >= 3 and re.search(r"\d[\d,.]{2,}", v) and results_sheet.get(ws.title) \
                        and not any(isinstance(x.value, str) and x.value.startswith("=") for x in ws[c.row]):
                    frozen.append(f"{ws.title}!{c.coordinate} \"{v[:50]}\"")
        if hebrew:
            (P if ws.sheet_view.rightToLeft else F)(f"sheet '{ws.title}' has Hebrew and is {'RTL' if ws.sheet_view.rightToLeft else 'NOT right-to-left'}")

    P(f"{n_formulas} formulas scanned")
    (F(f"{len(errs)} error value(s): " + " | ".join(errs[:8])) if errs else P("no #REF!/#DIV/0!/#VALUE!/#NAME?/#N/A after recalculation")) if wv else None
    if wv and empty_val:
        F(f"{len(empty_val)} formula(s) with no computed value: {', '.join(empty_val[:8])}")
    (F(f"{len(hard)} formula(s) with hard-coded numbers (move each to a labelled input): " + " | ".join(hard[:8]))
     if hard else P(f"no hard-coded numbers inside formulas (allowed literals: {sorted(opts['allow'])})"))
    # FAST: one formula across each row. Row totals (aggregate of the own row, or a far link to its end) are set
    # aside; in every run of >=3 adjacent formulas, all cells after the first must share one R1C1 pattern.
    incons, runs_checked = [], 0
    for (sh, row), cells in rowmap.items():
        body = []
        for col, pat, f, coord in sorted(cells):
            n_cells, n_refs = same_row_refs(f, row)
            if n_cells >= 3:
                continue   # a row total (SUM/AVERAGE/MIN/MAX of its own row)
            body.append((col, pat, f, coord))
        # an edge cell that only links INTO its own row (total column "=D12" or "=O12") is a total, not a period;
        # a middle cell that copies its neighbour (the "=M6" in November) stays in and breaks the pattern
        def inward_link(item, others):
            m = re.fullmatch(r"=\$?([A-Z]{1,3})\$?(\d+)", item[2].replace(" ", "").upper())
            if not m or int(m.group(2)) != row or not others:
                return False
            tgt = column_index_from_string(m.group(1))
            cols = [o[0] for o in others]
            left = item[0] < min(cols) and tgt >= min(cols)
            right = item[0] > max(cols) and tgt <= max(cols) and item[0] - tgt >= 2   # "=N6" in the last period is a copy, not a total
            return left or right
        while len(body) >= 2 and inward_link(body[0], body[1:]):
            body = body[1:]
        while len(body) >= 2 and inward_link(body[-1], body[:-1]):
            body = body[:-1]
        run = []
        for item in body + [(None, None, None, None)]:
            if run and (item[0] is None or item[0] != run[-1][0] + 1):
                if len(run) >= 3:
                    runs_checked += 1
                    pats = [x[1] for x in run]
                    common = max(set(pats), key=pats.count)
                    # only a roll-forward row (it looks k periods back: C[-k]) may start with k different cells (openings)
                    back = [int(b) for b in re.findall(r"C\[-(\d+)\]", common)]
                    k = max(back) if back else 0
                    model = next(x[3] for x in run if x[1] == common)
                    for idx, x in enumerate(run):
                        if x[1] != common and idx >= k:
                            incons.append(f"{sh}!{x[3]} {x[2][:60]} (row pattern: like {model})")
                run = []
            if item[0] is not None:
                run.append(item)
    (F(f"{len(incons)} formula(s) break their row's pattern (copied wrong / overwritten): " + " | ".join(incons[:6]))
     if incons else P(f"{runs_checked} formula rows consistent across periods (one formula per row)"))
    if frozen:
        F(f"{len(frozen)} number(s) typed as TEXT in a results area (a conclusion that will never update): " + " | ".join(frozen[:6]))
    if iferr:
        W(f"IFERROR/IFNA in {len(iferr)} cell(s) can hide real errors: {', '.join(iferr[:6])}")
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
    const_names = [f"{n}={d.attr_text}" for n, d in names.items()
                   if re.fullmatch(r"=?\s*-?[\d.]+(?:[eE][+-]?\d+)?%?\s*", str(d.attr_text or ""))]
    (F(f"named constant(s) hidden in Name Manager (an input nobody sees): {', '.join(const_names[:8])}") if const_names
     else P("no constants hidden in named ranges"))
    by_target = {}
    for n_, d_ in names.items():
        by_target.setdefault(str(d_.attr_text).replace("$", ""), []).append(n_)
    dup = [f"{t}: {', '.join(ns)}" for t, ns in by_target.items() if len(ns) > 1]
    if dup:
        W(f"two names point at the same cell (one of them is probably wrong): " + " | ".join(dup[:5]))
    hidden = [f"{ws.title}!row {r}" for ws in wf.worksheets if ws.sheet_state == "visible"
              for r, d in ws.row_dimensions.items() if d.hidden] + \
             [f"{ws.title}!col {k}" for ws in wf.worksheets if ws.sheet_state == "visible"
              for k, d in ws.column_dimensions.items() if d.hidden]
    if hidden:
        W(f"hidden rows/columns on visible sheets (results the client cannot see): {', '.join(hidden[:8])}")
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

    # ---- mutation test: do the model's own checks notice a corrupted number? ----
    # Every calculation row (>=3 formulas) gets one cell typed over with a wrong number, in its own copy, recalculated
    # in parallel LibreOffice instances. A row whose corruption no check notices is a row nobody is guarding.
    if check_cells and wv and lo and opts["mutate"] != 0:
        check_sheets = {sh for sh, _, _ in check_cells}
        cand = [(sh, row, cells) for (sh, row), cells in rowmap.items()
                if sh not in check_sheets and len(cells) >= 3 and wf[sh].sheet_state == "visible"]
        # single named result cells (dashboard KPIs) must be guarded too
        for n_, d_ in names.items():
            try:
                dest = list(d_.destinations)
            except Exception:
                continue
            if len(dest) == 1 and ":" not in dest[0][1] and not n_.startswith("QA_") and dest[0][0] in wf.sheetnames:
                sh_, co_ = dest[0][0], dest[0][1].replace("$", "")
                cell_ = wf[sh_][co_]
                if isinstance(cell_.value, str) and cell_.value.startswith("=") and sh_ not in check_sheets:
                    cand.append((sh_, cell_.row, [(cell_.column, None, cell_.value, co_)]))
        # the hidden-copy check (QA_ShadowCheck) only proves "nobody edited a cell"; coverage must come from the others
        shadow = set()
        if "QA_ShadowCheck" in names:
            for sh_, co_ in names["QA_ShadowCheck"].destinations:
                c1, r1, c2, r2 = range_boundaries(co_.replace("$", ""))
                shadow.add((sh_, r1, c1))
        judge = [x for x in check_cells if x not in shadow]
        cand.sort(key=lambda t: (wf.sheetnames.index(t[0]), t[1]))
        if opts["mutate"] > 0 and opts["mutate"] < len(cand):
            k = opts["mutate"]
            cand = [cand[round(i * (len(cand) - 1) / max(1, k - 1))] for i in range(k)]
        mdir = out / "mutations"
        mdir.mkdir(exist_ok=True)
        jobs = []
        untested = []
        for n, (sh, row, cells) in enumerate(cand):
            srt = sorted(cells)
            order = srt[len(srt) // 2:] + srt[:len(srt) // 2]          # middle first, then any numeric cell
            vals = [wv[sh][coord].value for _, _, _, coord in srt]
            if vals and all(isinstance(x, datetime.datetime) for x in vals) and len(vals) >= 3:
                continue   # a period-header row (dates), not a result
            pick = next(((col, coord) for col, _, _, coord in order
                         if isinstance(wv[sh][coord].value, (int, float, str, datetime.datetime)) and not isinstance(wv[sh][coord].value, bool)
                         and wv[sh][coord].value != ""), None)
            if pick is None:
                untested.append(f"{sh}!{srt[0][3]} ({wf[sh].cell(row=row, column=1).value or ''})")
                continue
            col, coord = pick
            v = wv[sh][coord].value
            wm = openpyxl.load_workbook(src)
            if isinstance(v, str):
                wm[sh][coord].value = "x"                          # a sentence replaced: do the checks read the text?
            elif isinstance(v, datetime.datetime):
                wm[sh][coord].value = v + datetime.timedelta(days=31)
            else:
                wm[sh][coord].value = v * 1.1 + 1 if v else 1000
            mp = mdir / f"mut_{n}.xlsx"
            wm.save(mp)
            jobs.append((mp, sh, row, coord))
        workers = [lo] + [LO() for _ in range(min(3, max(0, len(jobs) - 1)))]
        from concurrent.futures import ThreadPoolExecutor
        def run(idx_job):
            idx, (mp, sh, row, coord) = idx_job
            saved, _ = workers[idx % len(workers)].recalc(mp)
            if not saved:
                return None
            wmv = openpyxl.load_workbook(mp, data_only=True)
            return any(wmv[csh].cell(row=r, column=cc).value is not True for csh, r, cc in judge)
        with ThreadPoolExecutor(max_workers=len(workers)) as ex:
            # one job per worker at a time: a LibreOffice profile cannot serve two documents at once
            res = []
            for start in range(0, len(jobs), len(workers)):
                batch = list(enumerate(jobs[start:start + len(workers)]))
                res += list(ex.map(run, batch))
        caught = [j for j, r in zip(jobs, res) if r]
        missed = [f"{sh}!{coord} ({wf[sh].cell(row=row, column=1).value or ''})" for (mp, sh, row, coord), r in zip(jobs, res) if r is False]
        n = len(caught) + len(missed)
        if n:
            if missed and not opts.get("mutate_warn"):
                F(f"mutation test: {len(missed)}/{n} calculation rows / named results can be corrupted and every INDEPENDENT "
                  "model check stays TRUE (the hidden-copy check does not count): " + " | ".join(missed[:10]))
            elif missed:
                W(f"mutation test (--mutate-warn): checks miss {len(missed)}/{n} rows: " + " | ".join(missed[:8]))
            else:
                P(f"mutation test: corrupted one cell in each of {n} calculation rows and named results; independent checks "
                  f"(not counting the hidden copy) caught every one")
        if untested:
            W(f"mutation test: {len(untested)} row(s) have no number to corrupt (blank or text results) and were NOT tested: "
              + " | ".join(untested[:6]) + ". Fill sample values (e.g. one month of actuals) and run again")
        shutil.rmtree(mdir, ignore_errors=True)

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
        weak_dv = []
        for ws in wf.worksheets:
            for dv in ws.data_validations.dataValidation:
                if dv.type not in ("whole", "decimal", "list", "date", "time", "textLength") or (dv.formula1 in (None, "")):
                    weak_dv.append(f"{ws.title}!{str(dv.sqref).split()[0]} (type={dv.type})")
        if weak_dv:
            F(f"{len(weak_dv)} data validation(s) that allow anything: " + ", ".join(weak_dv[:6]))
        novalid = [f"{s}!{c}" for s, c, _, cell in main_cells if (s, cell.row, cell.column) not in dv_cells]
        (F(f"{len(novalid)} input cell(s) without data validation: {', '.join(novalid[:8])}") if novalid
         else P("every input cell has data validation"))
        locked_inputs = [f"{s}!{c}" for s, c, _, cell in main_cells if wf[s].protection.sheet and cell.protection.locked]
        (F(f"{len(locked_inputs)} input cell(s) locked on a protected sheet (client cannot type): {', '.join(locked_inputs[:8])}")
         if locked_inputs else P("input cells are unlocked"))
    else:
        W("no typed numbers found: is there an inputs area at all?")
    unprot = [ws.title for ws in wf.worksheets if not ws.protection.sheet and any(
        isinstance(c.value, str) and c.value.startswith("=") for r in ws.iter_rows() for c in r)]
    (F(f"sheets with formulas but no protection (formulas can be overwritten): {', '.join(unprot)}") if unprot
     else P("every sheet with formulas is protected"))
    if dangling:
        W(f"{len(dangling)} formula reference(s) to EMPTY cells (often a wrong row/column): " + " | ".join(dangling[:6]))
    else:
        P("no formula points at an empty cell")
    if volatile:
        W(f"volatile OFFSET/INDIRECT in {len(volatile)} cell(s) (fragile, slow; FAST discourages): {', '.join(volatile[:6])}")
    if newfn:
        F(f"functions missing in {opts['target']}: " + " | ".join(newfn[:6]))

    # ---- charts: every series must take its name and its values from the same row, over the whole period ----
    import zipfile
    from xml.etree import ElementTree as ET
    C_NS = {"c": "http://schemas.openxmlformats.org/drawingml/2006/chart"}
    chart_bad, n_series = [], 0
    def _rng(ref):
        ref = ref.split("!")[-1].replace("$", "")
        try:
            return range_boundaries(ref)
        except Exception:
            return None
    with zipfile.ZipFile(src) as z:
        for name in sorted(n for n in z.namelist() if n.startswith("xl/charts/chart") and n.endswith(".xml")):
            root = ET.fromstring(z.read(name))
            cat_len = None
            for ser in root.iter("{%s}ser" % C_NS["c"]):
                n_series += 1
                tx = ser.find("c:tx/c:strRef/c:f", C_NS)
                val = ser.find("c:val/c:numRef/c:f", C_NS)
                cat = ser.find("c:cat/*/c:f", C_NS)
                vb = _rng(val.text) if val is not None else None
                if vb is None:
                    chart_bad.append(f"{name}: a series without a value range"); continue
                c1, r1, c2, r2 = vb
                if tx is not None and _rng(tx.text) and _rng(tx.text)[1] != r1:
                    chart_bad.append(f"{name}: series named by {tx.text.split('!')[-1]} plots row {r1} ({val.text.split('!')[-1]}): name and values from different rows")
                sh_name = val.text.split("!")[0].strip("'").replace("''", "'")
                if sh_name in wf.sheetnames:
                    wsx = wf[sh_name]
                    lit = ser.find("c:tx/c:v", C_NS)
                    row_label = wsx.cell(row=r1, column=1).value
                    if lit is not None and row_label and lit.text and lit.text.strip() != str(row_label).strip():
                        chart_bad.append(f"{name}: series called \"{lit.text}\" plots the row labelled \"{row_label}\"")
                    nxt = wsx.cell(row=r1, column=c2 + 1).value
                    if isinstance(nxt, (int, float)) or (isinstance(nxt, str) and nxt.startswith("=")):
                        chart_bad.append(f"{name}: series {val.text.split('!')[-1]} stops before {get_column_letter(c2 + 1)}{r1}, which has a value (a period is missing from the chart)")
                if cat is not None and _rng(cat.text):
                    k1, kr1, k2, kr2 = _rng(cat.text)
                    if (k2 - k1) != (c2 - c1) or k1 != c1:
                        chart_bad.append(f"{name}: values {val.text.split('!')[-1]} do not line up with the categories {cat.text.split('!')[-1]}")
    if n_series:
        (F(f"{len(chart_bad)} chart problem(s): " + " | ".join(chart_bad[:5])) if chart_bad
         else P(f"{n_series} chart series: names, values and periods line up"))

    # ---- number formats that hide the sign or scale the number ----
    fmt_bad = []
    for ws in wf.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.value is None or c.number_format in (None, "General", "@"):
                    continue
                f_ = re.sub(r'"[^"]*"|\[[^\]]*\]|_.|\\.|\*.', "", c.number_format)   # drop text, [colour], _x spacers, \x, *x fills
                parts = f_.split(";")
                if all(not re.search(r"[0#?@]|[ymdhs]", p_, re.I) for p_ in parts):
                    fmt_bad.append(f"{ws.title}!{c.coordinate} '{c.number_format}' displays nothing at all")
                elif len(parts) >= 2 and re.search(r"[0#]", parts[1]) and not re.search(r"[-(]", parts[1]):
                    fmt_bad.append(f"{ws.title}!{c.coordinate} '{c.number_format}' shows a negative number without a minus")
                elif len(parts) >= 2 and not re.search(r"[0#]", parts[1]):
                    fmt_bad.append(f"{ws.title}!{c.coordinate} '{c.number_format}' hides negative numbers")
                elif any(re.search(r"[0#?],+\s*$", p_) for p_ in parts):
                    fmt_bad.append(f"{ws.title}!{c.coordinate} '{c.number_format}' divides the number by 1,000 for display")
    (F(f"{len(fmt_bad)} cell(s) with a format that hides the sign or scale: " + " | ".join(fmt_bad[:5])) if fmt_bad
     else P("number formats show every sign and scale"))

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
