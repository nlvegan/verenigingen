"""
Shared date and year extraction from text (filenames, folder paths, etc.).

Used by:
- MijnRood document import (document_import_service.py)
- Document portal uploads (document_portal_service.py)
- Organization Document DocType (organization_document.py)

Handles Dutch document naming conventions including European date formats,
Dutch month names, and various delimiter styles.
"""

import re
from datetime import date

# Dutch month names → month number
DUTCH_MONTHS = {
    "januari": 1,
    "februari": 2,
    "maart": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "augustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}

# Build regex alternation from month names
_MONTH_PATTERN = "|".join(DUTCH_MONTHS.keys())


def _safe_date(year: int, month: int, day: int) -> date | None:
    """Construct a date, returning None if values are out of range."""
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_date_from_text(text: str) -> date | None:
    """Extract a full date from text, trying patterns in priority order.

    Returns a datetime.date on success, None if no valid date is found.

    Pattern priority (first match wins):
    1. YYYYMMDD at start of text (with optional dash/space separator after)
    2. YYYY-MM-DD anywhere (ISO format)
    3. DD-MM-YYYY anywhere (European format, also with / or . separators)
    4. YYYY MM DD at start (space-separated)
    5. Dutch month: "DD maand YYYY" or "YYYY DD maand" patterns
    """
    if not text or not isinstance(text, str):
        return None

    text = text.strip()

    # 1. YYYYMMDD at start (e.g. "20251221 Intern Bulletin" or "20251108-Intern-Bulletin")
    m = re.match(r"^(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:[-\s_.]|$)", text)
    if m:
        result = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if result:
            return result

    # 2. YYYY-MM-DD anywhere (e.g. "Notulen 2025-12-10.docx")
    m = re.search(r"(20\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", text)
    if m:
        result = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if result:
            return result

    # 3. DD-MM-YYYY anywhere (e.g. "18-01-2026 - Intern Bulletin" or "Notulen 28-09-2025.pdf")
    #    Also matches DD/MM/YYYY and DD.MM.YYYY
    m = re.search(r"(0[1-9]|[12]\d|3[01])[-/.](0[1-9]|1[0-2])[-/.](20\d{2})", text)
    if m:
        result = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if result:
            return result

    # 4. YYYY MM DD at start (e.g. "2025 08 30 notulen kaderdag.pdf")
    m = re.match(r"^(20\d{2})\s+(0[1-9]|1[0-2])\s+(0[1-9]|[12]\d|3[01])(?:\s|$)", text)
    if m:
        result = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if result:
            return result

    # 5. Dutch month patterns (e.g. "31 mei 2025 Notulen congres.pdf")
    #    Pattern A: DD month YYYY
    m = re.search(
        rf"(\d{{1,2}})\s+({_MONTH_PATTERN})\s+(20\d{{2}})",
        text,
        re.IGNORECASE,
    )
    if m:
        month_num = DUTCH_MONTHS.get(m.group(2).lower())
        if month_num:
            result = _safe_date(int(m.group(3)), month_num, int(m.group(1)))
            if result:
                return result

    return None


def extract_date_with_precision(text: str | None) -> tuple[date | None, str]:
    """Extract a date and its precision label from text.

    Precision label is one of "Day", "Month", "Year". Day-precision
    returns the actual day; Month uses day=1; Year uses month=1, day=1.

    Returns (None, "Day") when no date pattern matches. The "Day" default
    in the no-match case is irrelevant since callers check the date for
    None first.

    Pattern priority (first match wins):
      1. Full date (delegates to extract_date_from_text) → "Day"
      2. Year-month patterns (YYYY-MM, MM-YYYY, "<dutch_month> YYYY") → "Month"
      3. Bare year (20\\d{2}) → "Year"
    """
    if not text or not isinstance(text, str):
        return (None, "Day")

    # 1. Full date wins
    d = extract_date_from_text(text)
    if d:
        return (d, "Day")

    # 2. Year-month patterns
    text_stripped = text.strip()

    # 2a. YYYY-MM (also YYYY/MM, YYYY.MM, YYYY MM).
    # Valid YYYY-MM-DD inputs are absorbed by step 1 (full-date) above,
    # so this branch only fires on month-only or invalid-day full-date inputs.
    m = re.search(r"(?<!\d)(20\d{2})[-/.\s](0[1-9]|1[0-2])(?!\d)", text_stripped)
    if m:
        result = _safe_date(int(m.group(1)), int(m.group(2)), 1)
        if result:
            return (result, "Month")

    # 2b. MM-YYYY (also MM/YYYY, MM.YYYY)
    m = re.search(r"(?<!\d)(0[1-9]|1[0-2])[-/.](20\d{2})(?!\d)", text_stripped)
    if m:
        result = _safe_date(int(m.group(2)), int(m.group(1)), 1)
        if result:
            return (result, "Month")

    # 2c. <dutch_month> YYYY
    m = re.search(
        rf"(?<![a-zA-Z])({_MONTH_PATTERN})\s+(20\d{{2}})(?!\d)",
        text_stripped,
        re.IGNORECASE,
    )
    if m:
        month_num = DUTCH_MONTHS.get(m.group(1).lower())
        if month_num:
            result = _safe_date(int(m.group(2)), month_num, 1)
            if result:
                return (result, "Month")

    # 3. Bare year
    m = re.search(r"\b(20\d{2})\b", text_stripped)
    if m:
        result = _safe_date(int(m.group(1)), 1, 1)
        if result:
            return (result, "Year")

    return (None, "Day")


def extract_year_from_text(text: str, default: str = "Other") -> str:
    """Extract a year string from text.

    First tries to extract a full date (via extract_date_from_text), then
    falls back to a standalone 4-digit year pattern (20xx).

    Returns:
        Year as a string (e.g. "2025"), or `default` if no year found.
    """
    if not text or not isinstance(text, str):
        return default

    # Try full date extraction first
    full_date = extract_date_from_text(text)
    if full_date:
        return str(full_date.year)

    # Fallback: standalone year with word boundaries
    m = re.search(r"\b(20\d{2})\b", text)
    if m:
        return m.group(1)

    return default
