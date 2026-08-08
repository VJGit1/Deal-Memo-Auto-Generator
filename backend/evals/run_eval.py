#!/usr/bin/env python3
"""
Offline (and optional live) eval runner for DMAG.

Usage (from backend/, after ``pip install -e .``):
  python -m evals.run_eval                  # offline / cassette path
  RUN_LIVE_EVAL=1 python -m evals.run_eval  # live Gemini (requires API key)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from evals.metrics import (
    LatencyCostCounters,
    score_memo_against_expected,
)
from dmag.financial import Reconciler
from dmag.schema import Claim, FinancialEvidence

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "gold_deal"
EXPECTED_PATH = FIXTURE_DIR / "expected.json"
CASSETTE_PATH = FIXTURE_DIR / "gemini_cassette.json"


def load_expected() -> dict[str, Any]:
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


def load_cassette() -> dict[str, Any]:
    return json.loads(CASSETTE_PATH.read_text(encoding="utf-8"))


def build_mock_gemini_client(cassette: dict[str, Any] | None = None) -> MagicMock:
    """Gemini client that returns cassette JSON — no network / API key."""
    cassette = cassette or load_cassette()
    client = MagicMock()

    def _generate_content(*, model, contents, config=None):  # noqa: ARG001
        text = contents if isinstance(contents, str) else str(contents)
        lower = text.lower()
        if "fact-checker" in lower or "verdict" in lower or "judge this claim" in lower:
            payload = cassette.get("verify_batch") or {"verdicts": []}
        elif "atomic" in lower or "split the memo" in lower:
            payload = cassette.get("extract_claims") or {"claims": []}
        else:
            payload = cassette.get("section_generation") or cassette.get("extract_claims") or {}
        resp = MagicMock()
        resp.text = json.dumps(payload) if isinstance(payload, dict) else str(payload)
        return resp

    client.models.generate_content.side_effect = _generate_content
    return client


def run_offline_eval() -> dict[str, Any]:
    """Score cassette-backed claims + golden financial evidence (no live Gemini)."""
    expected = load_expected()
    counters = LatencyCostCounters()

    counters.start("load_cassette")
    cassette = load_cassette()
    counters.stop("load_cassette")

    claims = [Claim.model_validate(c) for c in expected["claims"]]
    evidence = [
        FinancialEvidence.model_validate(ev) for ev in expected["financial_evidence"]
    ]

    counters.start("reconcile")
    _, flags = Reconciler().reconcile(evidence)
    counters.stop("reconcile")

    counters.start("score")
    scores = score_memo_against_expected(
        claims=claims,
        predicted_flags=flags,
        expected=expected,
    )
    counters.stop("score")

    # Optional: exercise grounding verify path with cassette (still offline)
    counters.start("grounding_verify_cassette")
    import dmag.grounding as grounding_mod
    from dmag.grounding import GroundingService
    from dmag.schema import EvidenceChunk

    client = build_mock_gemini_client()
    # grounding imported API_DELAY_SEC by value — patch the module binding
    original_delay = grounding_mod.API_DELAY_SEC
    grounding_mod.API_DELAY_SEC = 0
    try:
        gs = GroundingService(client)
        evidence_chunks = [
            EvidenceChunk.model_validate(e) for e in expected["evidence_chunks"]
        ]
        claim_objs = [Claim.model_validate(c) for c in expected["claims"]]
        # Reset statuses so verify path is exercised
        for c in claim_objs:
            c.status = "insufficient"
        verified = gs.verify_claims(claim_objs, evidence_chunks)
        cassette_support = sum(1 for c in verified if c.status == "supported") / max(
            len(verified), 1
        )
    finally:
        grounding_mod.API_DELAY_SEC = original_delay
    counters.stop(
        "grounding_verify_cassette",
        prompt_chars=2000,
        completion_chars=800,
        model="cassette",
    )

    result = {
        "mode": "offline",
        "fixture": str(FIXTURE_DIR),
        "predicted_flags": flags,
        "scores": scores,
        "cassette_supported_claim_rate": cassette_support,
        "latency_cost": counters.summary(),
        "log_lines": counters.log_lines(),
    }
    return result


def run_live_eval() -> dict[str, Any]:
    """
    Live path: ingest gold_deal docs, extract claims via real Gemini.

    Requires GEMINI_API_KEY / GOOGLE_API_KEY and RUN_LIVE_EVAL=1.
    """
    expected = load_expected()
    counters = LatencyCostCounters()

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("RUN_LIVE_EVAL=1 requires GEMINI_API_KEY or GOOGLE_API_KEY")

    from google import genai

    import dmag.config as cfg
    import dmag.grounding as grounding_mod
    from dmag.grounding import GroundingService
    from dmag.ingest import Ingestor
    from dmag.schema import EvidenceChunk

    original_raw = cfg.RAW_DIR
    original_delay = grounding_mod.API_DELAY_SEC
    cfg.RAW_DIR = FIXTURE_DIR
    grounding_mod.API_DELAY_SEC = float(os.getenv("EVAL_API_DELAY_SEC", "0.5"))

    try:
        counters.start("ingest")
        chunks = Ingestor(raw_dir=FIXTURE_DIR).ingest()
        counters.stop("ingest", prompt_chars=sum(len(c.text) for c in chunks))

        client = genai.Client(api_key=api_key)
        gs = GroundingService(client)

        evidence_chunks = [
            EvidenceChunk(
                id=f"e{i + 1}",
                doc=c.doc_name,
                page=c.page,
                quote=c.text[:500],
            )
            for i, c in enumerate(chunks[:8])
        ]
        narrative = " ".join(c.text[:400] for c in chunks[:3])

        counters.start("extract_claims")
        claims = gs.extract_claims(narrative, evidence_chunks)
        counters.stop(
            "extract_claims",
            prompt_chars=len(narrative),
            completion_chars=sum(len(c.text) for c in claims),
            model=cfg.GEMINI_MODEL,
        )

        counters.start("verify_claims")
        claims = gs.verify_claims(claims, evidence_chunks)
        counters.stop(
            "verify_claims",
            prompt_chars=sum(len(c.text) for c in claims),
            completion_chars=200 * len(claims),
            model=cfg.GEMINI_MODEL,
        )

        evidence = [
            FinancialEvidence.model_validate(ev) for ev in expected["financial_evidence"]
        ]
        counters.start("reconcile")
        _, predicted_flags = Reconciler().reconcile(evidence)
        counters.stop("reconcile")

        scores = score_memo_against_expected(
            claims=claims,
            predicted_flags=predicted_flags,
            expected=expected,
        )
    finally:
        cfg.RAW_DIR = original_raw
        grounding_mod.API_DELAY_SEC = original_delay

    return {
        "mode": "live",
        "fixture": str(FIXTURE_DIR),
        "n_claims": len(claims),
        "predicted_flags": predicted_flags,
        "scores": scores,
        "latency_cost": counters.summary(),
        "log_lines": counters.log_lines(),
    }


def main() -> int:
    live = os.getenv("RUN_LIVE_EVAL", "").strip() in ("1", "true", "True", "yes")
    result = run_live_eval() if live else run_offline_eval()
    for line in result.get("log_lines") or []:
        print(line)
    print(json.dumps({k: v for k, v in result.items() if k != "log_lines"}, indent=2))
    passed = bool(result.get("scores", {}).get("passed"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
