"""
Step 5: Financial Auto-Fill.
Step 6: Fact-Check & Reconcile.

Extracts metrics from DD using structured Gemini JSON + Pydantic validation.
Reconciles on (canonical_metric, period) with relative numeric tolerance so
display forms like "52.9B" and "$52,900,000,000" agree.
"""

from __future__ import annotations

import json
import time
from typing import Any

from pydantic import BaseModel, Field

from .config import API_DELAY_SEC, GEMINI_MODEL, RECONCILE_RELATIVE_TOLERANCE
from .gemini_client import generate_content
from .normalize import (
    canonical_metric,
    canonical_period,
    format_normalized,
    parse_numeric_value,
    relative_delta,
    values_agree,
)
from .schema import FinancialEvidence


class _ExtractedMetric(BaseModel):
    """LLM extraction row before doc_name is attached."""

    metric_name: str
    value: str | int | float
    fiscal_year: str
    source_quote: str
    page_number: int = Field(ge=1, default=1)


class MetricExtractionResult(BaseModel):
    """Structured Gemini output for financial metric extraction."""

    company_name: str = ""
    financial_evidence: list[_ExtractedMetric] = Field(default_factory=list)


class FinancialExtractor:
    """Extracts financial metrics with Pydantic validation. Evidence Gating."""

    def __init__(self, client, model: str = GEMINI_MODEL):
        self.client = client
        self.model = model

    def extract(self, text: str, doc_name: str) -> list[FinancialEvidence]:
        time.sleep(API_DELAY_SEC)
        prompt = (
            f"Extract 3-8 key financial metrics from this text. "
            "Return valid JSON: company_name, financial_evidence (array of "
            "metric_name, value, fiscal_year, source_quote, page_number). "
            "value = exactly as written (e.g. '52.9B', '$1.2M', '15%'). "
            "source_quote = exact verbatim sentence. page_number = 1-based. "
            "Only include explicitly stated metrics. No inference.\n\n"
            f"Text ({doc_name}):\n{text[:15000]}"
        )
        try:
            config: dict[str, Any] = {
                "temperature": 0,
                "response_mime_type": "application/json",
            }
            # Prefer schema-constrained JSON when the client supports it
            try:
                config["response_schema"] = MetricExtractionResult
                resp = generate_content(
                    self.client,
                    model=self.model,
                    contents=prompt,
                    config=config,
                    step="financial_extract",
                )
            except (TypeError, ValueError, AttributeError):
                config.pop("response_schema", None)
                resp = generate_content(
                    self.client,
                    model=self.model,
                    contents=prompt,
                    config=config,
                    step="financial_extract",
                )

            parsed = self._parse_response(resp.text or "{}", doc_name)
            return parsed
        except Exception:
            return []

    def _parse_response(self, raw: str, doc_name: str) -> list[FinancialEvidence]:
        data = json.loads(raw or "{}")
        result_model = MetricExtractionResult.model_validate(data)
        out: list[FinancialEvidence] = []
        for ev in result_model.financial_evidence:
            out.append(
                FinancialEvidence.model_validate(
                    {
                        "metric_name": ev.metric_name,
                        "value": ev.value,
                        "fiscal_year": ev.fiscal_year,
                        "source_quote": ev.source_quote,
                        "page_number": ev.page_number,
                        "doc_name": doc_name,
                    }
                )
            )
        return out


class Reconciler:
    """Compares metrics across documents using normalized numeric values."""

    def __init__(self, relative_tolerance: float = RECONCILE_RELATIVE_TOLERANCE):
        self.relative_tolerance = relative_tolerance

    def reconcile(
        self, evidence: list[FinancialEvidence]
    ) -> tuple[list[FinancialEvidence], list[str]]:
        """
        Returns (evidence, flags).

        Groups on (canonical_metric, canonical_period). Flags when any pair of
        parseable values differs by more than relative_tolerance. Unparseable
        values fall back to exact string compare.

        Flag example:
          Revenue discrepancy (FY2024): Deck.pdf=50B (norm=50B) vs
          10K.pdf=52.9B (norm=52.9B), delta=5.48%
        """
        flags: list[str] = []
        by_key: dict[tuple[str, str], list[FinancialEvidence]] = {}
        for ev in evidence:
            key = (canonical_metric(ev.metric_name), canonical_period(ev.fiscal_year))
            by_key.setdefault(key, []).append(ev)

        for (metric, period), rows in by_key.items():
            if len(rows) < 2:
                continue
            flag = self._flag_group(metric, period, rows)
            if flag:
                flags.append(flag)

        return evidence, flags

    def _flag_group(
        self,
        metric: str,
        period: str,
        rows: list[FinancialEvidence],
    ) -> str | None:
        parsed: list[tuple[FinancialEvidence, float | None]] = [
            (ev, parse_numeric_value(ev.value)) for ev in rows
        ]

        # Compare every pair; flag if any disagree
        disagreeing: list[tuple[FinancialEvidence, float | None, FinancialEvidence, float | None, float | None]] = []
        for i in range(len(parsed)):
            for j in range(i + 1, len(parsed)):
                ev_a, num_a = parsed[i]
                ev_b, num_b = parsed[j]
                if num_a is not None and num_b is not None:
                    if not values_agree(
                        num_a, num_b, relative_tolerance=self.relative_tolerance
                    ):
                        disagreeing.append(
                            (ev_a, num_a, ev_b, num_b, relative_delta(num_a, num_b))
                        )
                else:
                    # Fallback: exact string compare on raw display values
                    if str(ev_a.value).strip() != str(ev_b.value).strip():
                        disagreeing.append((ev_a, num_a, ev_b, num_b, None))

        if not disagreeing:
            return None

        # Use the worst delta pair for the message; list all docs involved
        worst = max(
            disagreeing,
            key=lambda t: (t[4] if t[4] is not None else 1.0),
        )
        ev_a, num_a, ev_b, num_b, delta = worst
        label = metric.replace("_", " ").title()

        def _side(ev: FinancialEvidence, num: float | None) -> str:
            raw = ev.value
            if num is None:
                return f"{ev.doc_name}={raw} (unparseable)"
            return f"{ev.doc_name}={raw} (norm={format_normalized(num)})"

        if delta is None:
            return (
                f"{label} discrepancy ({period}): "
                f"{_side(ev_a, num_a)} vs {_side(ev_b, num_b)}"
            )
        return (
            f"{label} discrepancy ({period}): "
            f"{_side(ev_a, num_a)} vs {_side(ev_b, num_b)}, "
            f"delta={delta * 100:.2f}%"
        )
