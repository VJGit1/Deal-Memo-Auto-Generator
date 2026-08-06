"""Unit tests for offline eval metrics helpers."""

from __future__ import annotations

import pytest

from evals.metrics import (
    LatencyCostCounters,
    claim_support_rate,
    reconciliation_precision_recall,
    score_memo_against_expected,
    unsupported_claim_rate,
)
from dmag.schema import Claim


def test_claim_support_rate_empty():
    assert claim_support_rate([]) == 0.0


def test_claim_support_and_unsupported_rates():
    claims = [
        Claim(id="c1", text="a", status="supported"),
        Claim(id="c2", text="b", status="supported"),
        Claim(id="c3", text="c", status="unsupported"),
        Claim(id="c4", text="d", status="insufficient"),
    ]
    assert claim_support_rate(claims) == pytest.approx(0.5)
    # unsupported_claim_rate counts unsupported+contradicted only
    assert unsupported_claim_rate(claims) == pytest.approx(0.25)


def test_reconciliation_precision_recall_perfect():
    flags = ["Revenue discrepancy (FY2024): CIM.txt, Tax_Return.txt"]
    out = reconciliation_precision_recall(flags, flags)
    assert out["precision"] == 1.0
    assert out["recall"] == 1.0
    assert out["f1"] == 1.0


def test_reconciliation_matches_enriched_phase4_flag():
    predicted = [
        "Revenue discrepancy (FY2024): CIM.txt=52.9M (norm=52.9M) vs "
        "Tax_Return.txt=48.4M (norm=48.4M), delta=8.51%"
    ]
    expected = ["Revenue discrepancy (FY2024): CIM.txt, Tax_Return.txt"]
    out = reconciliation_precision_recall(predicted, expected)
    assert out["f1"] == 1.0


def test_reconciliation_precision_recall_partial():
    predicted = [
        "Revenue discrepancy (FY2024): CIM.txt, Tax_Return.txt",
        "EBITDA discrepancy (FY2024): A.txt, B.txt",
    ]
    expected = ["Revenue discrepancy (FY2024): CIM.txt, Tax_Return.txt"]
    out = reconciliation_precision_recall(predicted, expected)
    assert out["tp"] == 1
    assert out["fp"] == 1
    assert out["fn"] == 0
    assert out["precision"] == pytest.approx(0.5)
    assert out["recall"] == pytest.approx(1.0)


def test_latency_cost_counters():
    c = LatencyCostCounters(usd_per_1k_tokens=1.0)
    c.start("x")
    ev = c.stop("x", prompt_tokens=500, completion_tokens=500)
    assert ev["total_tokens"] == 1000
    assert ev["approx_cost_usd"] == pytest.approx(1.0)
    summary = c.summary()
    assert summary["calls"] == 1
    assert summary["total_tokens"] == 1000
    assert any("TOTAL" in line for line in c.log_lines())


def test_score_memo_against_expected(expected_json: dict):
    scores = score_memo_against_expected(
        claims=expected_json["claims"],
        predicted_flags=expected_json["reconciliation_flags"],
        expected=expected_json,
    )
    assert scores["pass_support"]
    assert scores["pass_unsupported"]
    assert scores["pass_reconciliation"]
    assert scores["passed"]
