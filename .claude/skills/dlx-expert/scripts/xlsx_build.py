#!/usr/bin/env python3
"""xlsx_build.py <spec.json> <out.xlsx>

Builds a FAST-style workbook (Flexible, Appropriate, Structured, Transparent) from a JSON spec:
  - separate sheets: outputs (dashboard) / inputs (assumptions) / calculations / checks / how-to
  - one consistent column layout on every time-based sheet: A label, B unit, C total-or-value, D.. periods
  - every scalar input and every row is a named range; formulas reference names, never typed numbers
  - inputs styled distinctly (blue text on light-yellow fill), unlocked, with data validation;
    every other cell is locked (sheet protection, no password, so the owner can unprotect)
  - right-to-left sheets, Hebrew labels, landscape fit-to-width print setup
  - a checks sheet whose results are exposed as the named range QA_Checks (read by qa_xlsx.py)

Formula tokens (inside "formula" / "first" strings):
  {Row}         same period column of row "Row" (inputs series, calcs or outputs rows)
  {Row[-1]}     previous period column (use "first" for the first period)
  {Row:total}   the total cell (column C) of that row
  {Row:row}     the whole period range of that row (D..last)
  {Row:first} / {Row:last}   first / last period cell
  {Periods:row} the period labels of the calculations sheet
  Bare names (e.g. PricePerDelivery) are scalar inputs, used as Excel defined names.

Then ALWAYS: python3 qa_xlsx.py <out.xlsx>  (recalculates headless in LibreOffice and checks).
"""
import datetime
import json
import re
import sys

try:
    from openpyxl import Workbook
    from openpyxl.chart import LineChart, BarChart, Reference
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.workbook.defined_name import DefinedName
    from openpyxl.worksheet.datavalidation import DataValidation
except ImportError:
    sys.exit("openpyxl missing: pip install openpyxl")

# ---- style tokens (FAST / banking convention: inputs blue on yellow, calcs black) -------------
FONT = "Arial"
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
INPUT_FONT = Font(name=FONT, color="0000FF", size=11)
CALC_FONT = Font(name=FONT, color="000000", size=11)
LINK_FONT = Font(name=FONT, color="006100", size=11)          # values pulled from another sheet
HEAD_FILL = PatternFill("solid", fgColor="1F3864")
HEAD_FONT = Font(name=FONT, color="FFFFFF", bold=True, size=11)
SECTION_FILL = PatternFill("solid", fgColor="D9E1F2")
SECTION_FONT = Font(name=FONT, bold=True, size=11, color="1F3864")
TITLE_FONT = Font(name=FONT, bold=True, size=18, color="1F3864")
SUB_FONT = Font(name=FONT, size=11, color="595959")
KPI_FONT = Font(name=FONT, bold=True, size=16, color="1F3864")
TOTAL_FONT = Font(name=FONT, bold=True, size=11)
NOTE_FONT = Font(name=FONT, italic=True, size=10, color="595959")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)

FORMATS = {
    "money": '₪#,##0;[Red]-₪#,##0',
    "money2": '₪#,##0.00;[Red]-₪#,##0.00',
    "int": '#,##0;[Red]-#,##0',
    "num": '#,##0.00',
    "pct": '0.0%',
    "text": '@',
    "bool": 'General',
    "month": '[$-40D]mmm yy',
    "date": 'dd/mm/yyyy',
}
LABEL_COL, UNIT_COL, TOTAL_COL, FIRST_PERIOD_COL = 1, 2, 3, 4
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CELLISH = re.compile(r"^[A-Za-z]{1,3}[0-9]+$|^[RrCc][0-9]*$")


def die(msg):
    sys.exit(f"SPEC ERROR: {msg}")


def qs(sheet):
    return "'" + sheet.replace("'", "''") + "'"


class Builder:
    def __init__(self, spec):
        self.spec = spec
        # periods: either real months from a "start" date input (preferred: next year = change one cell), or fixed labels
        self.start = spec.get("start")
        if self.start:
            self.n = int(spec.get("months", 12))
            self.periods = [None] * self.n
            spec.setdefault("inputs", []).insert(0, {"name": "StartMonth", "label": "החודש הראשון במודל",
                "value": datetime.date.fromisoformat(self.start), "unit": "תאריך", "format": "date",
                "note": "משנים לשנה הבאה, ומעדכנים ימי עבודה ועונתיות"})
            spec["inputs"].insert(0, {"section": "תקופה"})
        else:
            self.periods = spec.get("periods") or die("periods: give \"start\" (YYYY-MM-01) or a list of period labels")
            self.n = len(self.periods)
        names = {"outputs": "תוצאות", "inputs": "הנחות", "calcs": "חישובים", "checks": "בדיקות", "howto": "איך משתמשים"}
        names.update(spec.get("sheets", {}))
        self.sn = names
        self.rows = {}       # row name -> (sheet, row number, kind 'series'|'scalar')
        self.scalars = {}    # scalar input name -> (sheet, row)
        self.wb = Workbook()
        self.wb.remove(self.wb.active)
        self.input_cells = []

    # ---------- helpers ----------
    def pcol(self, j):
        return get_column_letter(FIRST_PERIOD_COL + j)

    def ref(self, name, here_sheet, j, mod):
        if name == "Periods":
            if mod != "row":
                die("{Periods} only supports :row")
            return f"{qs(self.sn['calcs'])}!${self.pcol(0)}$2:${self.pcol(self.n - 1)}$2"
        if name not in self.rows:
            die(f"unknown row {{{name}}} (define it before use, or it is a scalar: write it without braces)")
        sheet, r, _ = self.rows[name]
        pre = "" if sheet == here_sheet else qs(sheet) + "!"
        if mod is None or mod.startswith("["):
            if j is None:
                die(f"{{{name}}} needs a period column; use {{{name}:total}} or :row outside the timeline")
            off = int(mod[1:-1]) if mod else 0
            jj = j + off
            if jj < 0 or jj >= self.n:
                die(f"{{{name}{mod}}} points outside the timeline at period {j + 1}; give a 'first' formula")
            return f"{pre}{self.pcol(jj)}{r}"
        if mod == "total":
            return f"{pre}{get_column_letter(TOTAL_COL)}{r}"
        if mod == "row":
            return f"{pre}${self.pcol(0)}${r}:${self.pcol(self.n - 1)}${r}"
        if mod == "first":
            return f"{pre}{self.pcol(0)}{r}"
        if mod == "last":
            return f"{pre}{self.pcol(self.n - 1)}{r}"
        die(f"bad modifier in {{{name}{mod}}}")

    def tr(self, formula, sheet, j=None):
        if not formula.startswith("="):
            die(f"formula must start with '=': {formula}")

        def sub(m):
            name, mod = m.group(1), m.group(2) or m.group(3)
            if mod and mod.startswith(":"):
                mod = mod[1:]
            return self.ref(name, sheet, j, mod)

        def span(m):   # {FirstRow..LastRow}: the same period column across a block of rows (subtotal with SUM)
            a, b = m.group(1), m.group(2)
            for x in (a, b):
                if x not in self.rows:
                    die(f"unknown row {x} in {{{a}..{b}}}")
            (sa, ra, _), (sb, rb, _) = self.rows[a], self.rows[b]
            if sa != sb or sa != sheet or j is None:
                die(f"{{{a}..{b}}} must be rows on this sheet, used inside the timeline")
            return f"{self.pcol(j)}{ra}:{self.pcol(j)}{rb}"

        formula = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\.\.([A-Za-z_][A-Za-z0-9_]*)\}", span, formula)
        out = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)(\[-?\d+\])?(:[a-z]+)?\}", sub, formula)
        if "{" in out:
            die(f"untranslated token in {formula}")
        return out

    def register(self, name, sheet, r, kind):
        if not NAME_RE.match(name) or CELLISH.match(name):
            die(f"name '{name}' is not a valid Excel name (letters/digits/_; must not look like a cell such as AB12)")
        if name in self.rows or name in self.scalars:
            die(f"duplicate name {name}")
        if kind == "scalar":
            self.scalars[name] = (sheet, r)
            target = f"{qs(sheet)}!${get_column_letter(TOTAL_COL)}${r}"
        else:
            self.rows[name] = (sheet, r, kind)
            target = f"{qs(sheet)}!${self.pcol(0)}${r}:${self.pcol(self.n - 1)}${r}"
        self.wb.defined_names[name] = DefinedName(name, attr_text=target)

    def sheet(self, key, with_timeline=True):
        ws = self.wb.create_sheet(self.sn[key])
        ws.sheet_view.rightToLeft = True
        ws.sheet_view.showGridLines = False
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.column_dimensions["A"].width = 44
        ws.column_dimensions["B"].width = 11
        ws.column_dimensions["C"].width = 16
        if with_timeline:
            for j in range(self.n):
                ws.column_dimensions[self.pcol(j)].width = 13
            ws.column_dimensions[get_column_letter(FIRST_PERIOD_COL + self.n)].width = 60
        return ws

    def header(self, ws, r, total_label="שנה (סה\"כ או סוף שנה)"):
        labels = ["", "יחידה", total_label] + list(self.periods)
        for i, t in enumerate(labels):
            if i >= 3 and self.start:
                j = i - 3
                if ws.title == self.sn["calcs"]:
                    t = "=StartMonth" if j == 0 else f"=EDATE({self.pcol(j - 1)}{r},1)"
                else:
                    t = f"={qs(self.sn['calcs'])}!{self.pcol(j)}$2"
            c = ws.cell(row=r, column=i + 1, value=t)
            c.fill, c.font = HEAD_FILL, HEAD_FONT
            c.alignment = Alignment(horizontal="center", vertical="center")
            if i >= 3 and self.start:
                c.number_format = FORMATS["month"]
        ws.row_dimensions[r].height = 20

    def section(self, ws, r, text, width):
        for col in range(1, width + 1):
            ws.cell(row=r, column=col).fill = SECTION_FILL
        c = ws.cell(row=r, column=1, value=text)
        c.font = SECTION_FONT

    def title(self, ws, text, sub=None):
        ws.cell(row=1, column=1, value=text).font = TITLE_FONT
        ws.row_dimensions[1].height = 28

    def validate(self, ws, item, cells):
        fmt = item.get("format", "num")
        lo, hi = item.get("min"), item.get("max")
        if fmt == "pct":
            lo = 0 if lo is None else lo
            hi = 1 if hi is None else hi
        if lo is None:
            lo = 0
        if hi is None:
            hi = 10 ** 9
        dv = DataValidation(type="whole" if fmt == "int" else "decimal", operator="between",
                            formula1=str(lo), formula2=str(hi), allow_blank=False, showErrorMessage=True,
                            showInputMessage=bool(item.get("note")),
                            errorTitle="ערך לא תקין",
                            error=f"מספר בין {lo} ל-{hi}" + (" (אחוז: 0%–100%)" if fmt == "pct" else ""),
                            promptTitle=item["label"][:32], prompt=(item.get("note") or "")[:250])
        ws.add_data_validation(dv)
        for c in cells:
            dv.add(c)

    def style_input(self, c, fmt):
        c.fill, c.font, c.border = INPUT_FILL, INPUT_FONT, BOX
        c.number_format = FORMATS.get(fmt, fmt)
        c.protection = Protection(locked=False)
        c.alignment = Alignment(horizontal="center")
        self.input_cells.append(c)

    # ---------- sheets ----------
    def build_inputs(self):
        ws = self.sheet("inputs")
        self.title(ws, self.spec.get("inputs_title", "הנחות: כל המספרים שמשנים נמצאים כאן, ורק כאן"))
        ws.cell(row=2, column=1, value="תאים צהובים עם כתב כחול = קלט. כל השאר מחושב ונעול.").font = SUB_FONT
        self.header(ws, 3, "ערך")
        ws.freeze_panes = ws.cell(row=4, column=FIRST_PERIOD_COL)
        note_col = FIRST_PERIOD_COL + self.n
        ws.cell(row=3, column=note_col, value="מקור / הסבר").font = HEAD_FONT
        ws.cell(row=3, column=note_col).fill = HEAD_FILL
        r = 4
        for item in self.spec.get("inputs", []):
            if "section" in item:
                self.section(ws, r, item["section"], note_col)
                r += 1
                continue
            ws.cell(row=r, column=LABEL_COL, value=item["label"]).font = CALC_FONT
            ws.cell(row=r, column=UNIT_COL, value=item.get("unit", "")).font = SUB_FONT
            fmt = item.get("format", "num")
            if "series" in item or item.get("blank_series"):
                vals = item["series"] if "series" in item and item["series"] is not None else [None] * self.n
                if len(vals) != self.n:
                    die(f"{item['name']}: series has {len(vals)} values, periods has {self.n}")
                cells = []
                for j, v in enumerate(vals):
                    c = ws.cell(row=r, column=FIRST_PERIOD_COL + j, value=v)
                    self.style_input(c, fmt)
                    cells.append(c.coordinate)
                self.validate(ws, item, cells)
                self.register(item["name"], ws.title, r, "series")
            else:
                c = ws.cell(row=r, column=TOTAL_COL, value=item["value"])
                self.style_input(c, fmt)
                self.validate(ws, item, [c.coordinate])
                self.register(item["name"], ws.title, r, "scalar")
            if item.get("note"):
                ws.cell(row=r, column=note_col, value=item["note"]).font = NOTE_FONT
            r += 1
        self.ws_inputs = ws

    def build_calcs(self):
        ws = self.sheet("calcs")
        self.title(ws, self.spec.get("calcs_title", "חישובים (אין כאן קלט: הכל נגזר מההנחות)"))
        self.header(ws, 2)
        ws.freeze_panes = ws.cell(row=3, column=FIRST_PERIOD_COL)
        width = FIRST_PERIOD_COL + self.n - 1
        r = 3
        pending = []
        for item in self.spec.get("calcs", []):
            if "section" in item:
                self.section(ws, r, item["section"], width)
                r += 1
                continue
            self.register(item["name"], ws.title, r, "series")
            pending.append((item, r))
            r += 1
        for item, r in pending:
            self.fill_row(ws, item, r)
        self.ws_calcs = ws

    def fill_row(self, ws, item, r):
        ws.cell(row=r, column=LABEL_COL, value=item["label"]).font = TOTAL_FONT if item.get("bold") else CALC_FONT
        ws.cell(row=r, column=UNIT_COL, value=item.get("unit", "")).font = SUB_FONT
        fmt = FORMATS.get(item.get("format", "money"), item.get("format"))
        for j in range(self.n):
            f = item.get("first") if (j == 0 and item.get("first")) else item["formula"]
            c = ws.cell(row=r, column=FIRST_PERIOD_COL + j, value=self.tr(f, ws.title, j))
            c.number_format = fmt
            c.font = TOTAL_FONT if item.get("bold") else CALC_FONT
        total = item.get("total", "sum")
        rng = f"{self.pcol(0)}{r}:{self.pcol(self.n - 1)}{r}"
        tf = {"sum": f"=SUM({rng})", "avg": f"=AVERAGE({rng})", "last": f"={self.pcol(self.n - 1)}{r}",
              "first": f"={self.pcol(0)}{r}", "min": f"=MIN({rng})", "max": f"=MAX({rng})", "none": None}[total]
        if tf:
            c = ws.cell(row=r, column=TOTAL_COL, value=tf)
            c.number_format, c.font = fmt, TOTAL_FONT
        if item.get("bold"):
            for col in range(1, FIRST_PERIOD_COL + self.n):
                ws.cell(row=r, column=col).border = Border(top=THIN)

    def build_outputs(self):
        out = self.spec.get("outputs", {})
        ws = self.sheet("outputs")
        self.title(ws, self.spec.get("title", "מודל"))
        ws.cell(row=2, column=1, value=self.spec.get("subtitle", "")).font = SUB_FONT
        r = 4
        self.section(ws, r, "השורה התחתונה", 3)
        r += 1
        for k in out.get("kpis", []):
            if "section" in k:
                r += 1
                self.section(ws, r, k["section"], 3)
                r += 1
                continue
            ws.cell(row=r, column=1, value=k["label"]).font = Font(name=FONT, size=12)
            c = ws.cell(row=r, column=TOTAL_COL, value=self.tr(k["formula"], ws.title))
            c.font = KPI_FONT
            c.number_format = FORMATS.get(k.get("format", "money"), k.get("format"))
            c.alignment = Alignment(horizontal="center")
            if k.get("format") == "text":   # a sentence: give it the whole row width, aligned to the reading start
                ws.merge_cells(start_row=r, start_column=TOTAL_COL, end_row=r, end_column=FIRST_PERIOD_COL + self.n - 1)
                c.font = Font(name=FONT, bold=True, size=12, color="1F3864")
                c.alignment = Alignment(horizontal="right", readingOrder=2)
            if k.get("note"):
                ws.cell(row=r, column=FIRST_PERIOD_COL, value=k["note"]).font = NOTE_FONT
            ws.row_dimensions[r].height = 24
            r += 1
        # model-integrity line, always visible on the dashboard
        r += 1
        ws.cell(row=r, column=1, value="בדיקות תקינות של המודל").font = TOTAL_FONT
        c = ws.cell(row=r, column=TOTAL_COL, value='=IF(QA_AllChecks,"✔ הכל תקין","✖ יש בעיה, ראה לשונית בדיקות")')
        c.font = TOTAL_FONT
        ok_row = r
        ws.conditional_formatting.add(f"C{ok_row}", FormulaRule(formula=["QA_AllChecks"], font=Font(color="006100", bold=True)))
        ws.conditional_formatting.add(f"C{ok_row}", FormulaRule(formula=["NOT(QA_AllChecks)"], font=Font(color="C00000", bold=True)))
        r += 2
        table = out.get("table", [])
        if table:
            self.section(ws, r, out.get("table_title", "חודש אחרי חודש"), FIRST_PERIOD_COL + self.n - 1)
            r += 1
            self.header(ws, r)
            hdr = r
            r += 1
            first_row = r
            for t in table:
                if "section" in t:
                    self.section(ws, r, t["section"], FIRST_PERIOD_COL + self.n - 1)
                    r += 1
                    continue
                item = {"label": t["label"], "unit": t.get("unit", "₪"), "formula": t.get("formula") or "={" + t["ref"] + "}",
                        "format": t.get("format", "money"), "total": t.get("total", "sum"), "bold": t.get("bold")}
                self.register(t.get("name") or "Out_" + t["ref"], ws.title, r, "series")
                self.fill_row(ws, item, r)
                for j in range(-2, self.n):
                    ws.cell(row=r, column=FIRST_PERIOD_COL + j).font = LINK_FONT if not t.get("bold") else Font(name=FONT, bold=True, color="006100")
                r += 1
            last_row = r - 1
            ch = out.get("chart")
            if ch:
                rows = [self.rows["Out_" + x][1] for x in ch["rows"]]
                chart = LineChart() if ch.get("type", "line") == "line" else BarChart()
                chart.title = ch["title"]
                chart.height, chart.width = 8, 26
                chart.y_axis.numFmt = '₪#,##0'
                for rr in rows:
                    data = Reference(ws, min_col=FIRST_PERIOD_COL - 3, max_col=FIRST_PERIOD_COL + self.n - 1, min_row=rr, max_row=rr)
                    chart.add_data(data, from_rows=True, titles_from_data=True)
                # series title comes from column A; drop the unit and total columns from the series values
                for s, rr in zip(chart.series, rows):
                    s.val.numRef.f = f"{qs(ws.title)}!${self.pcol(0)}${rr}:${self.pcol(self.n - 1)}${rr}"
                    s.tx.strRef.f = f"{qs(ws.title)}!$A${rr}"
                    s.smooth = False
                cats = Reference(ws, min_col=FIRST_PERIOD_COL, max_col=FIRST_PERIOD_COL + self.n - 1, min_row=hdr, max_row=hdr)
                chart.set_categories(cats)
                chart.x_axis.scaling.orientation = "maxMin"   # right-to-left, like the table above it
                chart.x_axis.tickLblPos = "low"               # month labels under the plot, even when values go negative
                chart.x_axis.number_format = FORMATS["month"] if self.start else "General"
                chart.x_axis.delete = False
                chart.y_axis.delete = False
                chart.legend.position = "b"
                ws.add_chart(chart, f"A{last_row + 3}")
        ws.freeze_panes = None
        self.ws_out = ws

    def build_checks(self):
        ws = self.sheet("checks", with_timeline=False)
        ws.column_dimensions["A"].width = 70
        self.title(ws, "בדיקות תקינות: כל שורה חייבת להיות TRUE")
        ws.cell(row=2, column=1, value="אם שורה הופכת ל-FALSE אחרי שינוי, משהו במודל נשבר. לא למסור ולא להחליט לפי המספרים עד שמתקנים.").font = SUB_FONT
        r = 4
        first = r
        for chk in self.spec.get("checks", []):
            ws.cell(row=r, column=1, value=chk["label"]).font = CALC_FONT
            c = ws.cell(row=r, column=TOTAL_COL, value=self.tr(chk["formula"], ws.title))
            c.font, c.alignment = TOTAL_FONT, Alignment(horizontal="center")
            r += 1
        last = r - 1
        if last < first:
            die("at least one check is required (FAST: build the checks with the model)")
        rng = f"{qs(ws.title)}!$C${first}:$C${last}"
        self.wb.defined_names["QA_Checks"] = DefinedName("QA_Checks", attr_text=rng)
        r += 1
        ws.cell(row=r, column=1, value="כל הבדיקות עברו").font = TOTAL_FONT
        c = ws.cell(row=r, column=TOTAL_COL, value=f"=AND($C${first}:$C${last})")
        c.font = TOTAL_FONT
        self.wb.defined_names["QA_AllChecks"] = DefinedName("QA_AllChecks", attr_text=f"{qs(ws.title)}!$C${r}")
        green, red = PatternFill("solid", fgColor="C6EFCE"), PatternFill("solid", fgColor="FFC7CE")
        for rng, top in ((f"C{first}:C{last}", first), (f"C{r}", r)):   # not the blank row between them
            ws.conditional_formatting.add(rng, FormulaRule(formula=[f"C{top}=TRUE"], fill=green))
            ws.conditional_formatting.add(rng, FormulaRule(formula=[f'AND(C{top}<>"",C{top}=FALSE)'], fill=red))

    def build_howto(self):
        ws = self.sheet("howto", with_timeline=False)
        ws.column_dimensions["A"].width = 110
        self.title(ws, "איך משתמשים בקובץ")
        r = 3
        for line in self.spec.get("howto", []):
            c = ws.cell(row=r, column=1, value=line)
            c.font = Font(name=FONT, size=12)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            r += 1

    def rtl_text(self):
        """readingOrder=RTL on every text cell, so mixed Hebrew/English/numbers render in the right order (PDF, Excel)."""
        for ws in self.wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str):
                        a = c.alignment
                        c.alignment = Alignment(horizontal=a.horizontal, vertical=a.vertical, wrap_text=a.wrap_text, readingOrder=2)

    def protect(self):
        for ws in self.wb.worksheets:
            ws.protection.sheet = True
            ws.protection.formatColumns = False   # allow widening columns
            ws.protection.selectLockedCells = False
            ws.protection.selectUnlockedCells = False

    def build(self, out):
        self.build_inputs()
        self.build_calcs()
        self.build_outputs()       # uses the name QA_AllChecks, defined by build_checks
        self.build_checks()
        self.build_howto()
        self.rtl_text()
        self.protect()
        order = [self.sn[k] for k in ("outputs", "inputs", "calcs", "checks", "howto")]
        self.wb._sheets.sort(key=lambda w: order.index(w.title))
        self.wb.active = 0
        self.wb.calculation.fullCalcOnLoad = True   # Excel / Sheets compute on open
        self.wb.save(out)
        print(f"Wrote {out}: {len(self.wb.sheetnames)} sheets ({', '.join(self.wb.sheetnames)}), "
              f"{len(self.input_cells)} input cells, {len(self.rows)} named rows, {len(self.scalars)} named inputs")
        print("NEXT: python3 qa_xlsx.py", out, "  (recalculates in LibreOffice and checks; must end with 0 FAIL)")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as f:
        spec = json.load(f)
    Builder(spec).build(sys.argv[2])


if __name__ == "__main__":
    main()
