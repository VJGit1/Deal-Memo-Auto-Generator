"""
Numeric / metric / period normalization for financial reconciliation.

Converts display forms like "52.9B", "$(1.2M)", "15%" into comparable floats,
and maps metric/period aliases onto canonical keys.
"""

from __future__ import annotations

import re
from typing import Optional

# Canonical metric name ← aliases (lowercase, stripped punctuation variants)
_METRIC_ALIASES: dict[str, str] = {
    "rev": "revenue",
    "revenue": "revenue",
    "revenues": "revenue",
    "net sales": "revenue",
    "netsales": "revenue",
    "net_sales": "revenue",
    "total revenue": "revenue",
    "total revenues": "revenue",
    "sales": "revenue",
    "ebitda": "ebitda",
    "adj ebitda": "ebitda",
    "adjusted ebitda": "ebitda",
    "net income": "net_income",
    "netincome": "net_income",
    "net_income": "net_income",
    "net profit": "net_income",
    "profit": "net_income",
    "earnings": "net_income",
    "gross profit": "gross_profit",
    "gross margin": "gross_margin",
    "operating income": "operating_income",
    "operating profit": "operating_income",
    "arr": "arr",
    "mrr": "mrr",
}

_MULTIPLIER = {
    "k": 1_000,
    "m": 1_000_000,
    "mm": 1_000_000,
    "b": 1_000_000_000,
    "bn": 1_000_000_000,
    "t": 1_000_000_000_000,
}

# Strip currency symbols / words before parsing
_CURRENCY_RE = re.compile(
    r"(?i)\b(?:usd|eur|gbp|cad|aud)\b|[$€£¥]"
)
_PARENS_RE = re.compile(r"^\((.+)\)$")
_PERCENT_RE = re.compile(r"%\s*$")
# number + optional multiplier suffix (K/M/B/MM/BN)
_NUM_UNIT_RE = re.compile(
    r"(?i)^\s*"
    r"([+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[+-]?\d+(?:\.\d+)?)"
    r"\s*([kmb]|mm|bn|t)?\s*$"
)
_FY_SHORT_RE = re.compile(r"(?i)^fy\s*'?(\d{2})$")
_FY_LONG_RE = re.compile(r"(?i)^fy\s*'?(\d{4})$")
_YEAR_ONLY_RE = re.compile(r"^(\d{4})$")
_QUARTER_RE = re.compile(
    r"(?i)^(?:(?:q([1-4])\s*(?:fy\s*)?'?(\d{2}|\d{4}))|"
    r"(?:([1-4])q\s*(?:fy\s*)?'?(\d{2}|\d{4}))|"
    r"(?:q([1-4])\s+(?:fy\s*)?(\d{2}|\d{4})))$"
)
_TTM_RE = re.compile(r"(?i)^(ttm|ltm|trailing\s+twelve\s+months)$")


def _clean_metric_key(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[_\-/]+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def canonical_metric(name: str) -> str:
    """Map metric aliases to a stable key (e.g. 'Net Sales' → 'revenue')."""
    key = _clean_metric_key(name)
    if key in _METRIC_ALIASES:
        return _METRIC_ALIASES[key]
    # Try without leading "total "
    if key.startswith("total ") and key[6:] in _METRIC_ALIASES:
        return _METRIC_ALIASES[key[6:]]
    return key.replace(" ", "_") or "unknown"


def _expand_year(y: str) -> str:
    """'24' → '2024', '2024' → '2024'."""
    y = y.strip()
    if len(y) == 2:
        n = int(y)
        # Pivot: 00–79 → 2000–2079, 80–99 → 1980–1999
        return str(2000 + n if n < 80 else 1900 + n)
    return y


def canonical_period(period: str) -> str:
    """
    Normalize fiscal periods.

    FY24 → FY2024, FY2024 → FY2024, TTM/LTM → TTM,
    Q1'24 / 1Q24 / Q1 2024 → Q1FY2024.
    """
    raw = (period or "").strip()
    if not raw:
        return "unknown"

    s = re.sub(r"\s+", " ", raw).strip()

    if _TTM_RE.match(s):
        return "TTM"

    m = _FY_LONG_RE.match(s)
    if m:
        return f"FY{m.group(1)}"

    m = _FY_SHORT_RE.match(s)
    if m:
        return f"FY{_expand_year(m.group(1))}"

    m = _YEAR_ONLY_RE.match(s)
    if m:
        return f"FY{m.group(1)}"

    compact = re.sub(r"[\s\-_/]+", "", s)
    m = _QUARTER_RE.match(compact) or _QUARTER_RE.match(s)
    if m:
        q = m.group(1) or m.group(3) or m.group(5)
        y = m.group(2) or m.group(4) or m.group(6)
        return f"Q{q}FY{_expand_year(y)}"

    # Soft fallback: uppercase, collapse spaces
    return re.sub(r"\s+", "", s).upper()


def parse_numeric_value(value: str | int | float) -> Optional[float]:
    """
    Parse a financial display value into a float.

    Handles currency symbols, commas, K/M/B(/MM/BN) multipliers,
    percent signs, and parentheses negatives accounting style.
    Returns None if the value cannot be parsed.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    if not s:
        return None

    negative = False
    # Accounting negatives: (1.2M)
    pm = _PARENS_RE.match(s)
    if pm:
        negative = True
        s = pm.group(1).strip()

    s = _CURRENCY_RE.sub("", s).strip()
    s = s.replace(",", "")

    is_percent = bool(_PERCENT_RE.search(s))
    if is_percent:
        s = _PERCENT_RE.sub("", s).strip()

    # Leading sign
    if s.startswith("+"):
        s = s[1:].strip()
    elif s.startswith("-"):
        negative = not negative
        s = s[1:].strip()

    m = _NUM_UNIT_RE.match(s)
    if not m:
        # Bare scientific / plain float fallback
        try:
            num = float(s)
        except ValueError:
            return None
        if negative:
            num = -num
        return num

    num = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    if unit:
        num *= _MULTIPLIER[unit]

    # Percents stay in percentage points (15% → 15.0) for like-for-like compare
    if negative:
        num = -num
    return num


def relative_delta(a: float, b: float) -> float:
    """Absolute relative difference |a-b| / max(|a|,|b|). 0 if both zero."""
    denom = max(abs(a), abs(b))
    if denom == 0:
        return 0.0
    return abs(a - b) / denom


def values_agree(
    a: float,
    b: float,
    *,
    relative_tolerance: float = 0.01,
) -> bool:
    """True if relative difference is within tolerance."""
    return relative_delta(a, b) <= relative_tolerance


def format_normalized(n: float) -> str:
    """Compact human-readable normalized magnitude for flag messages."""
    sign = "-" if n < 0 else ""
    x = abs(n)
    if x >= 1_000_000_000:
        return f"{sign}{x / 1_000_000_000:.4g}B"
    if x >= 1_000_000:
        return f"{sign}{x / 1_000_000:.4g}M"
    if x >= 1_000:
        return f"{sign}{x / 1_000:.4g}K"
    if x == int(x) and abs(x) < 1e12:
        return f"{sign}{int(x)}"
    return f"{sign}{x:.6g}"
