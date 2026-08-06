"""Unit tests for Claim / EvidenceChunk / MemoSection schema (Phase 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dmag.grounding import GroundingService
from dmag.schema import (
    Claim,
    EvidenceChunk,
    MemoOutput,
    MemoSection,
    VerificationSummary,
)


def test_claim_defaults_to_insufficient():
    c = Claim(id="c1", text="Revenue was $52.9M in FY2024.")
    assert c.status == "insufficient"
    assert c.citation_ids == []


def test_claim_rejects_invalid_status():
    with pytest.raises(ValidationError):
        Claim(id="c1", text="x", status="maybe")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "status",
    ["supported", "unsupported", "contradicted", "insufficient"],
)
def test_claim_accepts_valid_statuses(status: str):
    c = Claim(id="c1", text="fact", status=status)  # type: ignore[arg-type]
    assert c.status == status


def test_evidence_chunk_requires_page_ge_1():
    with pytest.raises(ValidationError):
        EvidenceChunk(id="e1", doc="CIM.txt", page=0, quote="x")


def test_memo_section_with_claims_and_summary():
    claims = [
        Claim(id="c1", text="A", citation_ids=["e1"], status="supported"),
        Claim(id="c2", text="B", citation_ids=[], status="insufficient"),
    ]
    evidence = [EvidenceChunk(id="e1", doc="CIM.txt", page=1, quote="A")]
    summary = VerificationSummary(
        total_claims=2,
        supported=1,
        unsupported=0,
        contradicted=0,
        insufficient=1,
        supported_claim_rate=0.5,
    )
    section = MemoSection(
        title="Executive Summary",
        content="A. B.",
        confidence_score=0.5,
        claims=claims,
        evidence_chunks=evidence,
        verification_summary=summary,
    )
    assert section.verification_summary is not None
    assert section.verification_summary.supported_claim_rate == 0.5
    dumped = section.model_dump()
    assert dumped["claims"][0]["status"] == "supported"


def test_memo_output_roundtrip(expected_json: dict):
    memo = MemoOutput.model_validate(expected_json["mock_memo"])
    assert memo.company_name == "Acme Robotics"
    assert len(memo.sections[0].claims) == 4
    assert memo.flags


def test_grounding_build_summary_and_confidence():
    gs = GroundingService(client=None)
    claims = [
        Claim(id="c1", text="a", status="supported"),
        Claim(id="c2", text="b", status="supported"),
        Claim(id="c3", text="c", status="unsupported"),
    ]
    summary = gs.build_summary(claims)
    assert summary.total_claims == 3
    assert summary.supported == 2
    assert summary.unsupported == 1
    assert summary.supported_claim_rate == pytest.approx(2 / 3)
    # Unsupported present → rate capped at CONFIDENCE_THRESHOLD-0.01 when higher;
    # here raw rate 2/3 already sits below the cap, so confidence equals support rate.
    conf = gs.confidence_from_claims(claims)
    assert conf < 0.7
    assert conf == pytest.approx(2 / 3)
    high = [
        Claim(id="c1", text="a", status="supported"),
        Claim(id="c2", text="b", status="supported"),
        Claim(id="c3", text="c", status="supported"),
        Claim(id="c4", text="d", status="unsupported"),
    ]
    # 0.75 would exceed cap → forced below threshold
    assert gs.confidence_from_claims(high) == pytest.approx(0.69)


def test_grounding_extract_claims_from_existing_skips_llm():
    gs = GroundingService(client=None)
    existing = [
        Claim(id="c1", text="Revenue was $52.9M.", citation_ids=["e1"], status="supported"),
    ]
    out = gs.extract_claims("ignored", evidence=[], existing=existing)
    assert len(out) == 1
    assert out[0].text.startswith("Revenue")


def test_grounding_local_status_heuristic():
    gs = GroundingService(client=None)
    ev = {
        "e1": EvidenceChunk(
            id="e1",
            doc="CIM.txt",
            page=1,
            quote="Revenue FY2024: $52.9M from warehouse robotics sales",
        )
    }
    claim = Claim(
        id="c1",
        text="Revenue FY2024 $52.9M warehouse robotics",
        citation_ids=["e1"],
    )
    assert gs._local_status(claim, ev) == "supported"
    empty = Claim(id="c2", text="x", citation_ids=[])
    assert gs._local_status(empty, ev) == "insufficient"


def test_bracket_unsupported():
    gs = GroundingService(client=None)
    narrative = "Good fact. Bad fact here."
    claims = [
        Claim(id="c1", text="Good fact.", status="supported"),
        Claim(id="c2", text="Bad fact here.", status="unsupported"),
    ]
    out = gs.bracket_unsupported(narrative, claims)
    assert "[Bad fact here.]" in out
    assert "Good fact." in out
