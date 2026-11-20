"""hebrew_text.py - shared helpers for Hebrew RTL documents (used by doc_build.py, deck_build.py, qa_text.py).

The Unicode bidi algorithm gets a few very common cases wrong inside an RTL paragraph. Each fix below was
checked by rendering in LibreOffice 24.2:
  * abbreviation "B.Sc." / "Ph.D." before Hebrew     -> shows as ".B.Sc"       fix: LRM after the final dot
  * "C++" / "C#" followed by Hebrew                  -> shows as "++C"         fix: LRM after the token
  * international phone "+972 50-123-4567"           -> "+" jumps to the end   fix: LRE ... PDF around it
  * separators " · " / " | " between Latin items     -> items reorder LTR      fix: RLM on both sides
Number ranges - house convention: a range is READ in Hebrew order, earlier value on the right
("2021–2025" with an en dash, exactly like "2025–היום"). A hyphen-minus range ("2021-2025") renders the other
way (left-to-right), so mixing the two in one document flips the reading order between lines. bidi_fix
normalises year ranges and small ranges to an en dash, and qa_text.py flags mixed styles.
Placeholders [לאשר ...] / [להשלים ...] are kept as-is and styled by the builders so they are impossible to miss.
"""
import re

LRM, RLM, LRE, PDF = "‎", "‏", "‪", "‬"
HEB = re.compile(r"[֐-׿]")
LATIN = re.compile(r"[A-Za-z]")
PLACEHOLDER = re.compile(r"\[(?:לאשר|להשלים)[^\]]*\]")
# template leftovers that must never reach a client
HARD_LEFTOVER = re.compile(r"\{\{[^}]*\}\}|\bTODO\b|\bTBD\b|\bXXX\b|[Ll]orem ipsum|\bFIXME\b|<<[^>]*>>")

_YEAR_HYPHEN = re.compile(r"(?<![\d–])(?<!\d-)((?:19|20)\d\d)-((?:19|20)\d\d)(?![\d\-])")
_SMALL_HYPHEN = re.compile(r"(?<![\d\-–.:/])(\d{1,2})-(\d{1,2})(?![\d\-.:/])")
_ABBR = re.compile(r"(\b[A-Za-z]{1,4}\.(?:[A-Za-z]{1,4}\.)+)(?!\u200e)(?=\s)")
_PLUSLANG = re.compile(r"(?<![\w‎])([A-Za-z][A-Za-z0-9]*(?:\+\+|#))(?!‎)")
_INTL_PHONE = re.compile(r"(?<!‪)(\+\d[\d \-]{6,}\d)")
_SEP = re.compile(r"(?<!‏) ([·|•]) (?!‏)")


def has_hebrew(s: str) -> bool:
    return bool(HEB.search(s or ""))


def bidi_fix(s: str) -> str:
    """Insert invisible direction marks so mixed Hebrew/English/number text renders in the right order.
    Idempotent: running it twice changes nothing."""
    if not s or not has_hebrew(s) and not _INTL_PHONE.search(s) and " · " not in s and " | " not in s:
        return s
    s = _YEAR_HYPHEN.sub(r"\1–\2", s)
    s = _SMALL_HYPHEN.sub(lambda m: f"{m.group(1)}–{m.group(2)}" if int(m.group(1)) < int(m.group(2)) else m.group(0), s)
    s = _ABBR.sub(lambda m: m.group(1) + LRM, s)
    s = _PLUSLANG.sub(lambda m: m.group(1) + LRM, s)
    s = _INTL_PHONE.sub(lambda m: LRE + m.group(1) + PDF, s)
    s = _SEP.sub(lambda m: f" {RLM}{m.group(1)}{RLM} ", s)
    return s


def bidi_problems(s: str):
    """Return a list of (kind, snippet) for risky, unprotected bidi patterns in a Hebrew paragraph."""
    out = []
    if not has_hebrew(s):
        return out
    for m in _ABBR.finditer(s):
        out.append(("קיצור לטיני עם נקודה בלי LRM (יוצג .B.Sc)", m.group(0)))
    for m in _YEAR_HYPHEN.finditer(s):
        out.append(("טווח שנים עם מקף רגיל (יוצג בכיוון הפוך מטווח עם קו מפריד)", m.group(0)))
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9]*(?:\+\+|#)(?!‎)", s):
        out.append(("C++/C# בלי LRM (יוצג ++C)", m.group(0)))
    for m in re.finditer(r"(?<!‪)\+\d[\d \-]{6,}\d", s):
        out.append(("טלפון בינלאומי בלי עטיפת LRE (ה-+ יקפוץ)", m.group(0)))
    if s.count("(") != s.count(")"):
        out.append(("סוגריים לא מאוזנים", s[:40]))
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
