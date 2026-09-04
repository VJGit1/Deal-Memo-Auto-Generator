"""
Numeric normalize tests against ``dmag.normalize`` (Phase 4).

Skipped automatically if the module is absent.
"""

from __future__ import annotations

import pytest

normalize = pytest.importorskip(
    "dmag.normalize",
    reason="Phase 4 normalize.py not present yet",
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$52.9M", 52_900_000.0),
        ("52.9B", 52_900_000_000.0),
        ("$48,400,000", 48_400_000.0),
        ("(1.2M)", -1_200_000.0),
        ("$(1.2M)", -1_200_000.0),
        ("$(450K)", -450_000.0),
        # Percents stay in percentage points for like-for-like compare
        ("58%", 58.0),
        ("1,850,000", 1_850_000.0),
    ],
)
def test_parse_numeric_value(raw, expected):
    fn = getattr(normalize, "parse_numeric_value", None) or getattr(
        normalize, "parse_number", None
    )
    assert fn is not None, "normalize.py must export parse_numeric_value"
    assert fn(raw) == pytest.approx(expected, rel=1e-6)


@pytest.mark.parametrize(
    "alias,canonical",
    [
        ("rev", "revenue"),
        ("revenue", "revenue"),
        ("net sales", "revenue"),
        ("ebitda", "ebitda"),
    ],
)
def test_canonical_metric(alias, canonical):
    fn = getattr(normalize, "canonical_metric", None) or getattr(
        normalize, "normalize_metric_name", None
    )
    assert fn is not None
    assert fn(alias) == canonical


@pytest.mark.parametrize(
    "raw,canonical",
    [
        ("FY24", "FY2024"),
        ("FY2024", "FY2024"),
        ("TTM", "TTM"),
        ("Q1'24", "Q1FY2024"),
    ],
)
def test_canonical_period(raw, canonical):
    fn = getattr(normalize, "canonical_period", None) or getattr(
        normalize, "normalize_period", None
    )
    assert fn is not None
    assert fn(raw) == canonical


def test_values_agree_within_tolerance():
    agree = getattr(normalize, "values_agree", None)
    if agree is None:
        pytest.skip("values_agree not exported")
    assert agree(52_900_000.0, 52_900_000.0)
    assert agree(100.0, 100.5, relative_tolerance=0.01)
    assert not agree(52_900_000.0, 48_400_000.0, relative_tolerance=0.01)
