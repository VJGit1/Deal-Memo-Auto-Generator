"""
Eval smoke tests: offline path with mocked Gemini (no API key).

Optional live eval is gated behind RUN_LIVE_EVAL=1.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from evals.run_eval import build_mock_gemini_client, run_live_eval, run_offline_eval
from dmag.financial import Reconciler
from dmag.grounding import GroundingService
from dmag.schema import Claim, EvidenceChunk, FinancialEvidence, MemoOutput


def test_offline_eval_passes(gold_deal_dir: Path):
    result = run_offline_eval()
    assert result["mode"] == "offline"
    assert result["scores"]["passed"] is True
    assert result["cassette_supported_claim_rate"] >= 0.5
    assert result["latency_cost"]["calls"] >= 1
    assert "Revenue" in result["predicted_flags"][0]


def test_mock_gemini_client_returns_cassette_json(cassette_json: dict):
    client = build_mock_gemini_client(cassette_json)
    resp = client.models.generate_content(
        model="x",
        contents="You are a strict fact-checker. Return verdicts.",
        config={},
    )
    data = json.loads(resp.text)
    assert "verdicts" in data
    assert data["verdicts"][0]["status"] == "supported"


def test_grounding_verify_with_cassette(expected_json: dict, cassette_json: dict):
    client = build_mock_gemini_client(cassette_json)
    gs = GroundingService(client)
    evidence = [EvidenceChunk.model_validate(e) for e in expected_json["evidence_chunks"]]
    claims = [
        Claim(
            id=c["id"],
            text=c["text"],
            citation_ids=c["citation_ids"],
            status="insufficient",
        )
        for c in expected_json["claims"]
    ]
    verified = gs.verify_claims(claims, evidence)
    by_id = {c.id: c.status for c in verified}
    assert by_id["c1"] == "supported"
    assert by_id["c2"] == "supported"
    assert by_id["c3"] == "supported"
    assert by_id["c4"] == "insufficient"


def test_reconcile_gold_financial_evidence(expected_json: dict):
    evidence = [
        FinancialEvidence.model_validate(ev) for ev in expected_json["financial_evidence"]
    ]
    _, flags = Reconciler().reconcile(evidence)
    memo = MemoOutput.model_validate(expected_json["mock_memo"])
    assert flags
    assert memo.company_name == "Acme Robotics"


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_EVAL", "").strip() not in ("1", "true", "True", "yes"),
    reason="Set RUN_LIVE_EVAL=1 to run live Gemini eval",
)
def test_live_eval_optional():
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        pytest.skip("Live eval requires GEMINI_API_KEY or GOOGLE_API_KEY")
    result = run_live_eval()
    assert result["mode"] == "live"
    assert "scores" in result
    # Live quality can vary; only assert harness completes with structure
    assert "claim_support_rate" in result["scores"]
    assert "reconciliation" in result["scores"]


def test_build_mock_does_not_need_network():
    """Sanity: MagicMock client never touches the network."""
    client = build_mock_gemini_client()
    assert isinstance(client, MagicMock)
    r1 = client.models.generate_content(model="m", contents="Split the memo narrative into atomic")
    r2 = client.models.generate_content(model="m", contents="Write narrative with citation_ids")
    assert json.loads(r1.text).get("claims")
    assert "narrative" in json.loads(r2.text)
