"""
Step 5: Financial Auto-Fill.
Step 6: Fact-Check & Reconcile.

Extracts metrics from DD using Pydantic validation.
Flags contradictory figures between documents (e.g., Pitch Deck vs Tax Return).
"""

import json
import time

from config import API_DELAY_SEC, GEMINI_MODEL
from schema import FinancialEvidence


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
            "source_quote = exact verbatim sentence. page_number = 1-based. "
            "Only include explicitly stated metrics. No inference.\n\n"
            f"Text ({doc_name}):\n{text[:15000]}"
        )
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "temperature": 0,
                    "response_mime_type": "application/json",
                },
            )
            data = json.loads(resp.text or "{}")
            result = []
            for ev in data.get("financial_evidence", []):
                ev["doc_name"] = ev.get("doc_name", doc_name)
                result.append(FinancialEvidence.model_validate(ev))
            return result
        except Exception:
            return []


class Reconciler:
    """Compares metrics across documents. Flags discrepancies."""

    def reconcile(
        self, evidence: list[FinancialEvidence]
    ) -> tuple[list[FinancialEvidence], list[str]]:
        """
        Returns (evidence, flags).
        Flags: e.g. "Revenue discrepancy (FY2024): Pitch_Deck.pdf, Tax_Return.pdf"
        """
        flags: list[str] = []
        by_key: dict[tuple[str, str], list[tuple[str, str | int | float]]] = {}
        for ev in evidence:
            key = (ev.metric_name.lower(), ev.fiscal_year)
            by_key.setdefault(key, []).append((ev.doc_name, ev.value))

        for (metric, fy), doc_vals in by_key.items():
            vals = [str(v) for _, v in doc_vals]
            if len(set(vals)) > 1:
                docs = ", ".join(d for d, _ in doc_vals)
                flags.append(f"{metric.title()} discrepancy ({fy}): {docs}")
        return evidence, flags
