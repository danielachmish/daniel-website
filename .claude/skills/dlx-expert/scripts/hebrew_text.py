"""hebrew_text.py - shared helpers for Hebrew RTL documents (used by doc_build.py, deck_build.py, qa_text.py).

The Unicode bidi algorithm (UAX #9) gets several common cases wrong inside an RTL paragraph. Each fix below
was reproduced and then checked by rendering in LibreOffice 24.2:
  * "Next.js, Prisma ו-Stripe. 3 מרפאות"  -> rule W7 turns the "3" after a Latin word into Latin, so it glues
    to "Stripe" and the sentence reads "ו-3 ... Stripe."            fix: RLM after sentence punctuation that
    follows Latin (". ", ": ", "; ", "! ", "? ") - the period stays with the Hebrew sentence, the digit is Hebrew
  * "[לאשר: X%]" / "ב-Y%"                 -> "%X"                     fix: LRM after a "%" that follows Latin
  * abbreviation "B.Sc." / "Ph.D."        -> ".B.Sc"                  fix: LRM after the final dot
  * "C++" / "C#" before Hebrew             -> "++C"                    fix: LRM after the token
  * international phone "+972 50-..."      -> "+" jumps to the end     fix: LRE ... PDF around it
  * separators " · " / " | " between Latin items -> items reorder LTR   fix: RLM on both sides

Ranges - ONE convention for EVERY range (independent critic, rounds 1-2): shown LEFT-TO-RIGHT, start on the
left, like Israeli forms and most Hebrew CVs: "2018–2020", "03/2025–היום", "2–3", "09:00–17:00". bidi_fix
wraps the whole range in LRE...PDF (an LTR embedding), so it renders the same way on every line - also a line
that holds only the range, and a range ending in "היום". qa_text.py reads the glyph order of every range in the
PDF and fails a document whose ranges point in two directions.
Product names with a version number ("Google Analytics 4", "Next.js 15") are glued with a no-break space, so a
line never starts with a bare number that belongs to the name on the line above.

Placeholders: ONE marker only, "[לאשר: ...]". Anything not supplied by the client or by a checked source is
written as [לאשר: what is missing]. The builders paint it amber; qa_text.py --final fails if one is left.
"""
import re

LRM, RLM, LRE, PDF = "‎", "‏", "‪", "‬"
HEB = re.compile(r"[֐-׿]")
LATIN = re.compile(r"[A-Za-z]")
PLACEHOLDER = re.compile(r"\[לאשר[^\]]*\]")
OLD_MARKER = re.compile(r"\[להשלים[^\]]*\]")
# template leftovers that must never reach a client
HARD_LEFTOVER = re.compile(r"\{\{[^}]*\}\}|\bTODO\b|\bTBD\b|\bXXX\b|[Ll]orem ipsum|\bFIXME\b|<<[^>]*>>")

_TOK = r"(?:(?:0?[1-9]|1[0-2])/(?:19|20)\d\d|(?:19|20)\d\d|\d{1,2}:\d\d|\d{1,2})"
_RANGE = re.compile(r"(?<![\d–./:\u202a\u2060])(?<!\d-)(" + _TOK + r")\s*\u2060?[-–—]\u2060?\s*(" + _TOK + r"|היום|כיום|הווה)"
                    r"(?![\d\-–\u05d0-\u05ea])(?![.:/]\d)")
_PRODUCT_NUM = re.compile(r"\b([A-Z][A-Za-z.]*[A-Za-z](?: [A-Z][A-Za-z.]*[A-Za-z])*) (\d{1,3})\b(?![%:/.,\-–]\d)")
_ABBR = re.compile(r"(\b[A-Za-z]{1,4}\.(?:[A-Za-z]{1,4}\.)+)(?!‎)(?=\s)")
_PLUSLANG = re.compile(r"(?<![\w‎])([A-Za-z][A-Za-z0-9]*(?:\+\+|#))(?!‎)")
_INTL_PHONE = re.compile(r"(?<!‪)(\+\d[\d \-]{6,}\d)")
_SEP = re.compile(r"(?<!‏) ([·|•]) (?!‏)")
_LATIN_PUNCT = re.compile(r"(?<=[A-Za-z0-9)\]])([.!?;:])(?=\s)")      # sentence punctuation right after Latin
_LATIN_PCT = re.compile(r"(?<=[A-Za-z])%(?!‎)")

# claims that must come from the client or a checked source (else: [לאשר]). Strong ones FAIL in qa_text.py.
STRONG_CLAIMS = re.compile(r"הרוב\b|רוב הלקוחות|כבר משלמים|מוכח|מובטח|\bהכי\b|היחיד[הים]?\b|הראשון בישראל|"
                           r"מוביל[הים]?\s+(?:ב|את)|מספר 1|#1|\bפי \d+|100%")
SOFT_CLAIMS = re.compile(r"תוך \d+\s*(?:שניות|דקות|שעות|ימים)|ב-?\d+%|\d+%\s*(?:יותר|פחות)|חוסך|מגדיל|מכפיל")


def has_hebrew(s: str) -> bool:
    return bool(HEB.search(s or ""))


def _range_sub(m):
    a, b = m.group(1), m.group(2)
    if re.fullmatch(r"\d{1,2}", a) and re.fullmatch(r"\d{1,2}", b) and int(a) >= int(b):
        return m.group(0)                      # "12-11" is a date, not a range
    return f"{LRE}{a}\u2060–\u2060{b}{PDF}"      # word joiners: the range never breaks across lines


def bidi_fix(s: str) -> str:
    """Insert invisible direction marks so mixed Hebrew/English/number text renders in the right order.
    Idempotent: running it twice changes nothing."""
    if not s:
        return s
    s = _RANGE.sub(_range_sub, s)               # always: even a line that is only "2018-2020" sits in RTL text
    s = _PRODUCT_NUM.sub(lambda m: f"{m.group(1)}\u00a0{m.group(2)}", s)
    if not has_hebrew(s) and not _INTL_PHONE.search(s) and " · " not in s and " | " not in s:
        return s
    s = _ABBR.sub(lambda m: m.group(1) + LRM, s)
    s = _PLUSLANG.sub(lambda m: m.group(1) + LRM, s)
    s = _INTL_PHONE.sub(lambda m: LRE + m.group(1) + PDF, s)
    s = _SEP.sub(lambda m: f" {RLM}{m.group(1)}{RLM} ", s)
    if has_hebrew(s):
        s = _LATIN_PCT.sub("%" + LRM, s)
        s = _LATIN_PUNCT.sub(lambda m: m.group(1) + RLM, s)
    return s


def bidi_problems(s: str):
    """Return a list of (kind, snippet) for unprotected bidi patterns that render wrong in a Hebrew paragraph."""
    out = []
    for m in _RANGE.finditer(s):
        if _range_sub(m) != m.group(0):
            out.append(("טווח בלי עטיפת LRE (יוצג בכיוון אחר משאר הטווחים)", m.group(0)))
    for m in _PRODUCT_NUM.finditer(s):
        out.append(("שם מוצר ומספר עם רווח רגיל (המספר עלול לפתוח שורה לבד)", m.group(0)))
    if not has_hebrew(s):
        return out
    for m in _ABBR.finditer(s):
        out.append(("קיצור לטיני עם נקודה בלי LRM (יוצג .B.Sc)", m.group(0)))
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9]*(?:\+\+|#)(?!‎)", s):
        out.append(("C++/C# בלי LRM (יוצג ++C)", m.group(0)))
    for m in re.finditer(r"(?<!‪)\+\d[\d \-]{6,}\d", s):
        out.append(("טלפון בינלאומי בלי עטיפת LRE (ה-+ יקפוץ)", m.group(0)))
    for m in re.finditer(r"[A-Za-z][.!?;:](?!‏)\s+\d", s):
        out.append(("מספר אחרי מילה לועזית ונקודה, בלי RLM (המספר נדבק למילה הלועזית)", m.group(0)))
    for m in re.finditer(r"[A-Za-z]%(?!‎)", s):
        out.append(("אחוז אחרי אות לועזית בלי LRM (יוצג %X)", m.group(0)))
    if s.count("(") != s.count(")"):
        out.append(("סוגריים לא מאוזנים", s[:40]))
    return out


# dummy data that looks real: FAIL unless marked [לאשר] or listed in the spec's "supplied" facts
DUMMY_PHONE = re.compile(r"\b0\d{1,2}-?(?:0{7}|1234567|0{3}-?0{4})\b")
DUMMY_EMAIL = re.compile(r"[\w.+-]+@(?:example|test|domain|email)\.(?:com|org|net|co\.il)\b")
STREET = re.compile(r"(?:רח'|רחוב|שד'|שדרות)\s+[\u05d0-\u05ea\"'״׳]+(?:\s[\u05d0-\u05ea\"'״׳]+)?\s\d{1,4}")


def find_dummies(s: str):
    bare = PLACEHOLDER.sub("", s)
    return ([("טלפון דמה", m.group(0)) for m in DUMMY_PHONE.finditer(bare)] +
            [("מייל דמה", m.group(0)) for m in DUMMY_EMAIL.finditer(bare)] +
            [("כתובת", m.group(0)) for m in STREET.finditer(bare)])


def find_claims(s: str):
    """(strength, snippet) for every claim outside a [לאשר] marker. strong = must have a source or [לאשר]."""
    bare = PLACEHOLDER.sub("", s)
    out = [("strong", m.group(0)) for m in STRONG_CLAIMS.finditer(bare)]
    out += [("soft", m.group(0)) for m in SOFT_CLAIMS.finditer(bare)]
    return out


def ils(x: float, decimals: int = 0) -> str:
    """Format an amount as Israeli shekels: '12,500 ₪' (non-breaking space)."""
    fmt = f"{{:,.{decimals}f}}"
    return fmt.format(x) + " ₪"


def split_rich(text: str):
    """Split text into segments: (str, is_bold, is_placeholder). Supports **bold** and [לאשר ...] markers."""
    segs = []
    for i, part in enumerate(re.split(r"\*\*", text)):
        bold = i % 2 == 1
        pos = 0
        for m in PLACEHOLDER.finditer(part):
            if m.start() > pos:
                segs.append((part[pos:m.start()], bold, False))
            segs.append((m.group(0), bold, True))
            pos = m.end()
        if pos < len(part):
            segs.append((part[pos:], bold, False))
    return [s for s in segs if s[0]]
