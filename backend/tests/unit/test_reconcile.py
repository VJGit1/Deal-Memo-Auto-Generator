"""Unit tests for financial.Reconciler (current Phase-1/4-pre API)."""

from __future__ import annotations

from dmag.financial import Reconciler
from dmag.schema import FinancialEvidence


def _ev(
    metric: str,
    value,
    fy: str = "FY2024",
    doc: str = "CIM.txt",
    quote: str = "quote",
) -> FinancialEvidence:
    return FinancialEvidence(
        metric_name=metric,
        value=value,
        fiscal_year=fy,
        source_quote=quote,
        page_number=1,
        doc_name=doc,
    )


def test_reconciler_no_flag_when_values_match():
    evidence = [
        _ev("Revenue", "52.9M", doc="CIM.txt"),
        _ev("Revenue", "52.9M", doc="Meeting_Notes.txt"),
    ]
    _, flags = Reconciler().reconcile(evidence)
    assert flags == []


def test_reconciler_flags_string_mismatch_same_metric_year():
    evidence = [
        _ev("Revenue", "52.9M", doc="CIM.txt"),
        _ev("Revenue", "48.4M", doc="Tax_Return.txt"),
    ]
    _, flags = Reconciler().reconcile(evidence)
    assert len(flags) == 1
    assert "Revenue" in flags[0]
    assert "FY2024" in flags[0]
    assert "CIM.txt" in flags[0]
    assert "Tax_Return.txt" in flags[0]


def test_reconciler_ignores_different_metrics():
    evidence = [
        _ev("Revenue", "52.9M", doc="CIM.txt"),
        _ev("EBITDA", "6.2M", doc="CIM.txt"),
    ]
    _, flags = Reconciler().reconcile(evidence)
    assert flags == []


def test_reconciler_ignores_different_fiscal_years():
    evidence = [
        _ev("Revenue", "52.9M", fy="FY2024", doc="CIM.txt"),
        _ev("Revenue", "38.1M", fy="FY2023", doc="CIM.txt"),
    ]
    _, flags = Reconciler().reconcile(evidence)
    assert flags == []


def test_reconciler_metric_name_case_insensitive_grouping():
    evidence = [
        _ev("Revenue", "52.9M", doc="A.txt"),
        _ev("revenue", "48.4M", doc="B.txt"),
    ]
    _, flags = Reconciler().reconcile(evidence)
    assert len(flags) == 1


def test_reconciler_against_gold_expected(expected_json: dict):
    evidence = [
        FinancialEvidence.model_validate(ev) for ev in expected_json["financial_evidence"]
    ]
    _, flags = Reconciler().reconcile(evidence)
    # Only Revenue FY2024 differs across CIM vs Tax; EBITDA/ARR are single-doc
    assert len(flags) == 1
    golden = expected_json["reconciliation_flags"][0].lower()
    assert "revenue" in flags[0].lower()
    assert "fy2024" in flags[0].lower()
    # Soft check: both docs named in golden appear in predicted
    for token in ("cim.txt", "tax_return.txt"):
        assert token in flags[0].lower()
        assert token in golden
