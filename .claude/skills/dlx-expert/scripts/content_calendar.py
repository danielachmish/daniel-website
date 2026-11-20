#!/usr/bin/env python3
"""content_calendar.py: מייצר לוח תוכן כגיליון Excel (RTL) מתוכנית JSON, ובודק אותה.

הפעלה:
  python3 content_calendar.py plan.json out.xlsx           # טיוטה: [לאשר] בטקסט = אזהרה
  python3 content_calendar.py plan.json out.xlsx --final   # מסירה: [לאשר] בטקסט = שגיאה
קוד יציאה: 0 = תקין, 1 = יש שגיאות (הקובץ נכתב בכל זאת, עם עמודת QA), 2 = קלט לא תקין.

מבנה ה-JSON (שדות חובה מסומנים *):
{
  "brand"*: "שם המותג", "title": "לוח תוכן - דצמבר 2026",
  "start"*: "2026-12-01", "days": 30,
  "goal": "מטרה במשפט", "kpis": ["מדד 1", "מדד 2"],
  "hours_per_week": 3, "minutes_per_post": 40, "shoot_hours_per_month": 3,
  "utm": {"base_url": "https://example.com", "campaign": "dec26", "medium": "social"},
  "pillars"*: [{"name": "ערך וטיפים", "share": 0.4, "color": "#DCEBFF"}],
  "posts"*: [{"date"*: "2026-12-01", "platform"*: "Instagram", "pillar"*: "ערך וטיפים", "format": "Reel",
              "hook"*: "שורה ראשונה", "caption"*: "הטקסט המלא", "cta": "שמרו לפעם הבאה",
              "visual": "הנחיית צילום/ויזואל", "link_path": "/register", "status": "טיוטה", "owner": "",
              "field": "instagram.caption"}]
}
"""
from __future__ import annotations

import datetime as dt
import json
import re
import os
import subprocess
import sys
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qa_copy  # noqa: E402

try:
    import openpyxl  # noqa: F401
except ImportError:  # התקנה אוטומטית
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "openpyxl"], check=False)
from openpyxl import Workbook  # noqa: E402
from openpyxl.formatting.rule import FormulaRule  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402
from openpyxl.worksheet.datavalidation import DataValidation  # noqa: E402

PLATFORM_FIELD = {
    "instagram": "instagram.caption", "facebook": "facebook.post", "linkedin": "linkedin.post",
    "gbp": "gbp.post", "google": "gbp.post", "google business profile": "gbp.post", "youtube": "youtube.description",
    "tiktok": "post", "whatsapp": "whatsapp.broadcast", "newsletter": "email.body", "מייל": "email.body",
}
DAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
STATUSES = ["רעיון", "טיוטה", "ממתין לאישור", "מאושר", "מתוזמן", "פורסם"]
HEADERS = ["תאריך", "יום", "שבוע", "פלטפורמה", "עמוד תוכן", "פורמט", "הוק (שורה ראשונה)", "טקסט מלא",
           "הנעה לפעולה", "ויזואל / הנחיית צילום", "קישור עם UTM", "תווים", "מגבלה", "QA", "סטטוס", "אחראי",
           "תוצאה (פניות/קליקים/שמירות)"]
WIDTHS = [11, 8, 6, 12, 14, 10, 34, 60, 22, 34, 34, 7, 7, 26, 13, 10, 22]
THIN = Side(style="thin", color="D0D5DD")


def field_for(p: dict) -> str:
    return p.get("field") or PLATFORM_FIELD.get(p["platform"].strip().lower(), "post")


def build_utm(plan: dict, p: dict) -> str:
    u = plan.get("utm") or {}
    if not u.get("base_url"):
        return ""
    base = u["base_url"].rstrip("/") + (p.get("link_path") or "")
    q = {"utm_source": re.sub(r"[^a-z0-9_]+", "_", p["platform"].strip().lower()).strip("_") or "social", "utm_medium": u.get("medium", "social"),
         "utm_campaign": u.get("campaign", "content"), "utm_content": p.get("utm_content") or f"{p['date']}-post"}
    return f"{base}{'&' if '?' in base else '?'}{urlencode(q)}"


def validate(plan: dict, final: bool):
    errors, warns, qa_by_post = [], [], []
    for k in ("brand", "start", "pillars", "posts"):
        if k not in plan:
            errors.append(f"חסר שדה חובה '{k}'")
    if errors:
        return errors, warns, qa_by_post
    start = dt.date.fromisoformat(plan["start"])
    end = start + dt.timedelta(days=int(plan.get("days", 30)) - 1)
    pillars = {pl["name"]: pl for pl in plan["pillars"]}
    for i, p in enumerate(plan["posts"], 1):
        tag = f"פוסט {i} ({p.get('date', '?')} {p.get('platform', '?')})"
        miss = [k for k in ("date", "platform", "pillar", "hook", "caption") if not str(p.get(k, "")).strip()]
        if miss:
            errors.append(f"{tag}: חסר {', '.join(miss)}")
            qa_by_post.append("FAIL: שדות חסרים")
            continue
        d = dt.date.fromisoformat(p["date"])
        if not start <= d <= end:
            errors.append(f"{tag}: התאריך מחוץ לטווח {start}–{end}")
        if p["pillar"] not in pillars:
            errors.append(f"{tag}: עמוד תוכן '{p['pillar']}' לא מוגדר ב-pillars")
        if not p["caption"].strip().startswith(p["hook"].strip()[:15]):
            warns.append(f"{tag}: הטקסט המלא לא מתחיל בהוק — מה שנראה לפני 'עוד' הוא הטקסט, לא עמודת ההוק")
        # QA של הטקסט עם qa_copy (טענות, מגבלות, CTA, placeholders, קריאות)
        rep = qa_copy.Report()
        unit = qa_copy.Unit(field_for(p), p["caption"] + ("\n" + p["cta"] if p.get("cta") and p["cta"] not in p["caption"] else ""))
        qa_copy.check_unit(unit, rep, plan.get("qa_allow", []), draft=not final)
        qa_copy.check_groups([unit], rep, draft=not final)
        fails = [m for s, _, m in rep.rows if s == "FAIL"]
        ws_ = [m for s, _, m in rep.rows if s == "WARN"]
        for m in fails:
            errors.append(f"{tag}: {m}")
        for m in ws_:
            warns.append(f"{tag}: {m}")
        qa_by_post.append("FAIL: " + fails[0][:60] if fails else ("WARN: " + ws_[0][:60] if ws_ else "PASS"))
    # קצב מול זמן הלקוח
    n = len(plan["posts"])
    weeks = max(1, int(plan.get("days", 30)) / 7)
    if plan.get("hours_per_week") and plan.get("minutes_per_post"):
        need = n / weeks * plan["minutes_per_post"] / 60 + plan.get("shoot_hours_per_month", 0) / (30 / 7)
        if need > plan["hours_per_week"] * 1.05:
            errors.append(f"התוכנית דורשת כ-{need:.1f} שעות בשבוע (כולל יום צילום), והלקוח אמר {plan['hours_per_week']}. לצמצם פוסטים.")
    elif plan.get("posts"):
        warns.append("חסרים hours_per_week / minutes_per_post — אי אפשר לבדוק שהתוכנית מתאימה לזמן של הלקוח")
    # חלוקה לעמודי תוכן
    for name, pl in pillars.items():
        if "share" in pl and n:
            actual = sum(1 for p in plan["posts"] if p.get("pillar") == name) / n
            if abs(actual - pl["share"]) > 0.15:
                warns.append(f"עמוד '{name}': {actual:.0%} מהפוסטים מול יעד {pl['share']:.0%}")
    # אותו יום/פלטפורמה פעמיים
    seen = set()
    for p in plan["posts"]:
        k = (p.get("date"), p.get("platform"))
        if k in seen:
            warns.append(f"שני פוסטים באותו יום באותה פלטפורמה: {k}")
        seen.add(k)
    return errors, warns, qa_by_post


def write_xlsx(plan: dict, out: str, qa_by_post: list) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "לוח תוכן"
    ws.sheet_view.rightToLeft = True
    hdr_fill = PatternFill("solid", fgColor="1F2A44")
    title = plan.get("title") or f"לוח תוכן — {plan['brand']}"
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"מטרה: {plan.get('goal', '')}   |   מדדים: {' · '.join(plan.get('kpis', []))}"
    ws["A2"].font = Font(italic=True, color="555555")
    hr = 4
    for c, h in enumerate(HEADERS, 1):
        cell = ws.cell(row=hr, column=c, value=h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = hdr_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = WIDTHS[c - 1]
    ws.row_dimensions[hr].height = 30
    start = dt.date.fromisoformat(plan["start"])
    posts = sorted(plan["posts"], key=lambda p: (p.get("date", ""), p.get("platform", "")))
    order = {id(p): i for i, p in enumerate(plan["posts"])}
    for r, p in enumerate(posts, hr + 1):
        d = dt.date.fromisoformat(p["date"])
        lim = qa_copy.LIMITS.get(qa_copy.base_field(field_for(p)), {})
        cap = lim.get("hard") or ""
        vals = [d, DAYS_HE[d.weekday()], (d - start).days // 7 + 1, p["platform"], p["pillar"], p.get("format", ""),
                p["hook"], p["caption"], p.get("cta", ""), p.get("visual", ""), build_utm(plan, p),
                f"=LEN(H{r})", cap, qa_by_post[order[id(p)]] if qa_by_post else "", p.get("status", "טיוטה"),
                p.get("owner", ""), ""]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.alignment = Alignment(wrap_text=True, vertical="top", horizontal="right")
            cell.border = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
        ws.cell(row=r, column=1).number_format = "dd/mm/yyyy"
        ws.row_dimensions[r].height = min(409, max(60, 15 * (len(p["caption"]) // 70 + p["caption"].count("\n") + 1)))
    last = hr + len(posts)
    ws.freeze_panes = ws.cell(row=hr + 1, column=2)
    ws.auto_filter.ref = f"A{hr}:{get_column_letter(len(HEADERS))}{last}"
    dv = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"O{hr + 1}:O{max(last, hr + 200)}")
    for pl in plan["pillars"]:
        if pl.get("color"):
            ws.conditional_formatting.add(
                f"E{hr + 1}:E{last}",
                FormulaRule(formula=[f'$E{hr + 1}="{pl["name"]}"'], fill=PatternFill("solid", fgColor=pl["color"].lstrip("#"))))
    red = PatternFill("solid", fgColor="F8D7DA")
    ws.conditional_formatting.add(f"L{hr + 1}:L{last}", FormulaRule(formula=[f'AND(ISNUMBER($M{hr + 1}),$L{hr + 1}>$M{hr + 1})'], fill=red))
    ws.conditional_formatting.add(f"N{hr + 1}:N{last}", FormulaRule(formula=[f'LEFT($N{hr + 1},4)="FAIL"'], fill=red))
    ws.conditional_formatting.add(f"N{hr + 1}:N{last}", FormulaRule(formula=[f'LEFT($N{hr + 1},4)="PASS"'], fill=PatternFill("solid", fgColor="D4EDDA")))
    ws.print_title_rows = f"{hr}:{hr}"
    ws.page_setup.orientation = "landscape"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_setup.paperSize = ws.PAPERSIZE_A4

    # סיכום
    s = wb.create_sheet("סיכום")
    s.sheet_view.rightToLeft = True
    s["A1"] = "חלוקה לעמודי תוכן"
    s["A1"].font = Font(bold=True, size=13)
    for c, h in enumerate(["עמוד תוכן", "פוסטים", "בפועל %", "יעד %"], 1):
        s.cell(row=2, column=c, value=h).font = Font(bold=True)
    rng = f"'לוח תוכן'!$E${hr + 1}:$E${last}"
    for i, pl in enumerate(plan["pillars"], 3):
        s.cell(row=i, column=1, value=pl["name"])
        s.cell(row=i, column=2, value=f"=COUNTIF({rng},A{i})")
        s.cell(row=i, column=3, value=f"=IF(SUM($B$3:$B${2 + len(plan['pillars'])})=0,0,B{i}/SUM($B$3:$B${2 + len(plan['pillars'])}))").number_format = "0%"
        s.cell(row=i, column=4, value=pl.get("share", None)).number_format = "0%"
    r0 = 4 + len(plan["pillars"])
    s.cell(row=r0, column=1, value="לפי פלטפורמה").font = Font(bold=True, size=13)
    prng = f"'לוח תוכן'!$D${hr + 1}:$D${last}"
    for j, plat in enumerate(sorted({p["platform"] for p in plan["posts"]}), r0 + 1):
        s.cell(row=j, column=1, value=plat)
        s.cell(row=j, column=2, value=f"=COUNTIF({prng},A{j})")
    r1 = r0 + 3 + len({p["platform"] for p in plan["posts"]})
    s.cell(row=r1, column=1, value="לפי שבוע").font = Font(bold=True, size=13)
    wrng = f"'לוח תוכן'!$C${hr + 1}:$C${last}"
    for k in range(1, (int(plan.get("days", 30)) + 6) // 7 + 1):
        s.cell(row=r1 + k, column=1, value=f"שבוע {k}")
        s.cell(row=r1 + k, column=2, value=f"=COUNTIF({wrng},{k})")
    s.column_dimensions["A"].width = 24

    # אסטרטגיה ומדידה
    m = wb.create_sheet("מדידה שבועית")
    m.sheet_view.rightToLeft = True
    cols = ["שבוע"] + plan.get("kpis", ["פניות", "קליקים לאתר", "שמירות", "שיתופים"]) + ["מה עבד", "מה משנים"]
    for c, h in enumerate(cols, 1):
        cell = m.cell(row=1, column=c, value=h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = hdr_fill
        m.column_dimensions[get_column_letter(c)].width = 18
    for k in range(1, (int(plan.get("days", 30)) + 6) // 7 + 1):
        m.cell(row=k + 1, column=1, value=f"שבוע {k}")
    if plan.get("notes"):
        n = wb.create_sheet("הנחיות")
        n.sheet_view.rightToLeft = True
        n.column_dimensions["A"].width = 110
        for i, line in enumerate(plan["notes"], 1):
            n.cell(row=i, column=1, value=line).alignment = Alignment(wrap_text=True, horizontal="right")
    wb.save(out)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    final = "--final" in sys.argv
    if len(args) != 2:
        print(__doc__)
        sys.exit(2)
    try:
        plan = json.load(open(args[0], encoding="utf-8"))
        errors, warns, qa_by_post = validate(plan, final)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"ERROR: קלט לא תקין: {e}", file=sys.stderr)
        sys.exit(2)
    if any(e.startswith("חסר שדה חובה") for e in errors):
        print("\n".join("FAIL  " + e for e in errors))
        sys.exit(2)
    write_xlsx(plan, args[1], qa_by_post)
    for e in errors:
        print("FAIL  " + e)
    for w in warns:
        print("WARN  " + w)
    print(f"\nנכתב: {args[1]} ({len(plan['posts'])} פוסטים)")
    print(f"סיכום: {'FAIL' if errors else 'PASS'} — {len(errors)} FAIL, {len(warns)} WARN")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
