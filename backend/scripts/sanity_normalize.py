#!/usr/bin/env python3
"""Local sanity checks for Phase 4 normalize + reconcile (no Gemini)."""

from __future__ import annotations

from dmag.financial import Reconciler
from dmag.normalize import (
    canonical_metric,
    canonical_period,
    parse_numeric_value,
    values_agree,
)
from dmag.schema import FinancialEvidence


def _ev(metric: str, value, fy: str, doc: str) -> FinancialEvidence:
    return FinancialEvidence(
        metric_name=metric,
        value=value,
        fiscal_year=fy,
        source_quote=f"{metric} was {value} in {fy}.",
        page_number=1,
        doc_name=doc,
    )


def main() -> None:
    # Multipliers / currency / negatives / percent
    assert parse_numeric_value("52.9B") == 52_900_000_000.0
    assert parse_numeric_value("$52,900,000,000") == 52_900_000_000.0
    assert parse_numeric_value("52.9M") == 52_900_000.0
    assert parse_numeric_value("$52,900,000") == 52_900_000.0
    assert parse_numeric_value("(1.2M)") == -1_200_000.0
    assert parse_numeric_value("15%") == 15.0
    assert values_agree(
        parse_numeric_value("52.9B"),
        parse_numeric_value("$52,900,000,000"),
    )

    assert canonical_metric("Net Sales") == "revenue"
    assert canonical_period("FY24") == "FY2024"

    evidence = [
        _ev("Revenue", "52.9M", "FY2024", "CIM.txt"),
        _ev("Revenue", "$52,900,000", "FY2024", "Meeting_Notes.txt"),
        _ev("Revenue", "48.4M", "FY2024", "Tax_Return.txt"),
    ]
    _, flags = Reconciler().reconcile(evidence)
    assert flags, "expected at least one reconciliation flag"
    print("sanity_normalize: OK")
    for f in flags:
        print(f"  FLAG: {f}")


if __name__ == "__main__":
    main()
