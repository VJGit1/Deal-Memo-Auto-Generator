"""
Claim extraction and LLM-as-judge verification.

Closed-book: judges each claim against cited evidence quotes only.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .config import API_DELAY_SEC, CONFIDENCE_THRESHOLD, GEMINI_MODEL
from .gemini_client import generate_content
from .schema import (
    Claim,
    ClaimStatus,
    ClaimVerdict,
    EvidenceChunk,
    GeneratedClaim,
    VerificationSummary,
)


VALID_STATUSES: set[str] = {"supported", "unsupported", "contradicted", "insufficient"}


class GroundingService:
    """Extract claims from narrative and verify against cited quotes only."""

    def __init__(self, client, model: str = GEMINI_MODEL):
        self.client = client
        self.model = model

    def extract_claims(
        self,
        narrative: str,
        evidence: list[EvidenceChunk],
        existing: list[GeneratedClaim] | list[Claim] | None = None,
    ) -> list[Claim]:
        """
        Prefer structured claims from generation. If empty, ask the LLM to
        split the narrative into atomic claims with citation ids.
        """
        if existing:
            return [
                Claim(
                    id=c.id if getattr(c, "id", None) else f"c{i + 1}",
                    text=c.text,
                    citation_ids=list(getattr(c, "citation_ids", []) or []),
                    status=getattr(c, "status", "insufficient")
                    if getattr(c, "status", None) in VALID_STATUSES
                    else "insufficient",
                )
                for i, c in enumerate(existing)
                if getattr(c, "text", None)
            ]

        if not narrative.strip():
            return []

        evidence_blob = self._format_evidence(evidence)
        time.sleep(API_DELAY_SEC)
        prompt = (
            "Split the memo narrative into atomic factual claims. "
            "Return JSON: {\"claims\": [{\"id\": \"c1\", \"text\": \"...\", "
            "\"citation_ids\": [\"e1\"]}]}. "
            "Assign citation_ids only from the evidence ids listed. "
            "If a claim has no supporting excerpt, use an empty citation_ids list. "
            "Do not invent facts.\n\n"
            f"Narrative:\n{narrative[:8000]}\n\n"
            f"Evidence:\n{evidence_blob[:12000]}"
        )
        try:
            resp = generate_content(
                self.client,
                model=self.model,
                contents=prompt,
                config={"temperature": 0, "response_mime_type": "application/json"},
                step="extract_claims",
            )
            data = json.loads(resp.text or "{}")
            claims: list[Claim] = []
            for i, raw in enumerate(data.get("claims", [])):
                cid = str(raw.get("id") or f"c{i + 1}")
                text = (raw.get("text") or "").strip()
                if not text:
                    continue
                cids = [str(x) for x in (raw.get("citation_ids") or [])]
                claims.append(Claim(id=cid, text=text, citation_ids=cids, status="insufficient"))
            return claims
        except Exception:
            # Fallback: treat whole narrative as one unverified claim
            return [
                Claim(
                    id="c1",
                    text=narrative.strip()[:500],
                    citation_ids=[e.id for e in evidence[:3]],
                    status="insufficient",
                )
            ]

    def verify_claims(
        self,
        claims: list[Claim],
        evidence: list[EvidenceChunk],
    ) -> list[Claim]:
        """LLM-as-judge: verify each claim against cited quotes only (closed-book)."""
        if not claims:
            return []

        by_id = {e.id: e for e in evidence}
        verified: list[Claim] = []

        # Batch judge when possible; fall back per-claim on parse failure
        batch = self._verify_batch(claims, by_id)
        if batch is not None:
            status_map = {v.claim_id: v.status for v in batch}
            for c in claims:
                status = status_map.get(c.id)
                if status is None:
                    status = self._local_status(c, by_id)
                verified.append(
                    Claim(id=c.id, text=c.text, citation_ids=list(c.citation_ids), status=status)
                )
            return verified

        for c in claims:
            status = self._verify_one(c, by_id)
            verified.append(
                Claim(id=c.id, text=c.text, citation_ids=list(c.citation_ids), status=status)
            )
        return verified

    def build_summary(self, claims: list[Claim]) -> VerificationSummary:
        counts = {
            "supported": 0,
            "unsupported": 0,
            "contradicted": 0,
            "insufficient": 0,
        }
        for c in claims:
            counts[c.status] = counts.get(c.status, 0) + 1
        total = len(claims)
        rate = counts["supported"] / max(total, 1)
        return VerificationSummary(
            total_claims=total,
            supported=counts["supported"],
            unsupported=counts["unsupported"],
            contradicted=counts["contradicted"],
            insufficient=counts["insufficient"],
            supported_claim_rate=rate,
        )

    def confidence_from_claims(self, claims: list[Claim]) -> float:
        """
        Calibrated confidence = supported / max(total, 1).
        Sections with unsupported or contradicted claims are capped below threshold.
        """
        summary = self.build_summary(claims)
        rate = summary.supported_claim_rate
        if summary.unsupported > 0 or summary.contradicted > 0:
            rate = min(rate, CONFIDENCE_THRESHOLD - 0.01)
        if summary.total_claims == 0:
            return 0.3
        return max(0.0, min(1.0, rate))

    def bracket_unsupported(self, narrative: str, claims: list[Claim]) -> str:
        """Bracket unsupported/contradicted claim text in the final narrative."""
        content = narrative
        for c in claims:
            if c.status in ("unsupported", "contradicted") and c.text and c.text in content:
                content = content.replace(c.text, f"[{c.text}]", 1)
        # Claims not found verbatim: append a short note if any remain unbracketed
        missing = [
            c
            for c in claims
            if c.status in ("unsupported", "contradicted") and f"[{c.text}]" not in content
        ]
        if missing:
            notes = "; ".join(c.text[:120] for c in missing[:5])
            content = content.rstrip() + f"\n\n[Unverified claims: {notes}]"
        return content

    def gap_query(self, title: str, claims: list[Claim]) -> str:
        """Build a re-retrieval query from unsupported / insufficient claims."""
        gaps = [
            c.text
            for c in claims
            if c.status in ("unsupported", "contradicted", "insufficient") or not c.citation_ids
        ]
        if not gaps:
            return title
        joined = " ".join(gaps[:5])
        return f"{title}: {joined}"[:500]

    def needs_repair(self, claims: list[Claim]) -> bool:
        if not claims:
            return True
        return any(
            c.status in ("unsupported", "contradicted", "insufficient") or not c.citation_ids
            for c in claims
        )

    def _verify_batch(
        self, claims: list[Claim], by_id: dict[str, EvidenceChunk]
    ) -> list[ClaimVerdict] | None:
        payload: list[dict[str, Any]] = []
        for c in claims:
            quotes = []
            for cid in c.citation_ids:
                ev = by_id.get(cid)
                if ev:
                    quotes.append({"id": ev.id, "doc": ev.doc, "page": ev.page, "quote": ev.quote})
            payload.append({"claim_id": c.id, "text": c.text, "cited_quotes": quotes})

        time.sleep(API_DELAY_SEC)
        prompt = (
            "You are a strict fact-checker. For each claim, judge ONLY using the "
            "cited_quotes provided for that claim. Do not use outside knowledge. "
            "If cited_quotes is empty, status must be 'insufficient'. "
            "If quotes support the claim, 'supported'. "
            "If quotes clearly conflict, 'contradicted'. "
            "If quotes do not support the claim, 'unsupported'. "
            "Return JSON: {\"verdicts\": [{\"claim_id\": \"c1\", \"status\": "
            "\"supported|unsupported|contradicted|insufficient\", \"rationale\": \"...\"}]}.\n\n"
            f"Claims:\n{json.dumps(payload)[:18000]}"
        )
        try:
            resp = generate_content(
                self.client,
                model=self.model,
                contents=prompt,
                config={"temperature": 0, "response_mime_type": "application/json"},
                step="verify_batch",
            )
            data = json.loads(resp.text or "{}")
            verdicts: list[ClaimVerdict] = []
            for raw in data.get("verdicts", []):
                status = raw.get("status", "insufficient")
                if status not in VALID_STATUSES:
                    status = "insufficient"
                verdicts.append(
                    ClaimVerdict(
                        claim_id=str(raw.get("claim_id", "")),
                        status=status,  # type: ignore[arg-type]
                        rationale=str(raw.get("rationale", "")),
                    )
                )
            return verdicts if verdicts else None
        except Exception:
            return None

    def _verify_one(self, claim: Claim, by_id: dict[str, EvidenceChunk]) -> ClaimStatus:
        if not claim.citation_ids:
            return "insufficient"

        quotes = []
        for cid in claim.citation_ids:
            ev = by_id.get(cid)
            if ev:
                quotes.append(f"[{ev.id}] ({ev.doc} p.{ev.page}) \"{ev.quote}\"")
        if not quotes:
            return "insufficient"

        time.sleep(API_DELAY_SEC)
        prompt = (
            "Judge this claim using ONLY the cited quotes. No outside knowledge. "
            "Return JSON: {\"status\": \"supported|unsupported|contradicted|insufficient\", "
            "\"rationale\": \"...\"}.\n\n"
            f"Claim: {claim.text}\n\nQuotes:\n" + "\n".join(quotes)
        )
        try:
            resp = generate_content(
                self.client,
                model=self.model,
                contents=prompt,
                config={"temperature": 0, "response_mime_type": "application/json"},
                step="verify_one",
            )
            data = json.loads(resp.text or "{}")
            status = data.get("status", "insufficient")
            return status if status in VALID_STATUSES else "insufficient"  # type: ignore[return-value]
        except Exception:
            return self._local_status(claim, by_id)

    def _local_status(self, claim: Claim, by_id: dict[str, EvidenceChunk]) -> ClaimStatus:
        if not claim.citation_ids:
            return "insufficient"
        quotes = [by_id[c].quote for c in claim.citation_ids if c in by_id]
        if not quotes:
            return "insufficient"
        # Heuristic fallback when LLM fails: keyword overlap
        tokens = set(claim.text.lower().split())
        overlap = max(len(tokens & set(q.lower().split())) for q in quotes)
        if overlap >= max(3, len(tokens) // 4):
            return "supported"
        return "unsupported"

    @staticmethod
    def _format_evidence(evidence: list[EvidenceChunk]) -> str:
        lines = []
        for e in evidence:
            lines.append(f"[{e.id}] {e.doc} p.{e.page}\n{e.quote}")
        return "\n\n".join(lines)
