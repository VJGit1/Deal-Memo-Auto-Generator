"""
Grounded agent loop: retrieve → structured generate → verify → re-retrieve.

Max repair rounds controlled by MAX_AGENT_ROUNDS (default 2).
"""

from __future__ import annotations

import json
import time

from .config import API_DELAY_SEC, GEMINI_MODEL, MAX_AGENT_ROUNDS, TOP_K
from .gemini_client import generate_content
from .grounding import GroundingService
from .models import DocChunk
from .schema import (
    Citation,
    EvidenceChunk,
    GeneratedClaim,
    MemoSection,
    SectionGeneration,
)


class AgentLoop:
    """Per-section generate–verify–retrieve loop with claim grounding."""

    SYNTHESIS_INSTRUCTION = (
        "Use ONLY the following excerpts. Do not add information not in the excerpts. "
        "Do not give final judgement, investment recommendation, or risk assessment. "
        "Every factual claim must be traceable to the excerpts via citation_ids. Closed-book."
    )

    def __init__(self, client, chunker, model: str = GEMINI_MODEL, max_rounds: int = MAX_AGENT_ROUNDS):
        self.client = client
        self.chunker = chunker
        self.model = model
        self.max_rounds = max_rounds
        self.grounding = GroundingService(client, model=model)

    def run_section(self, title: str, top_k: int = TOP_K) -> MemoSection:
        """
        1. Retrieve top-k
        2. Generate structured JSON: narrative + claims with citation ids
        3. Verify each claim against evidence quotes
        4. If gaps → rewrite query, re-retrieve, regenerate (≤ max_rounds)
        5. Strip/bracket unsupported claims; calibrate confidence from claims
        """
        query = title
        evidence: list[EvidenceChunk] = []
        generation: SectionGeneration | None = None
        claims = []

        for round_idx in range(self.max_rounds + 1):
            top = self.chunker.retrieve_top_k(query, top_k=top_k)
            evidence = self._chunks_to_evidence(top)
            if not evidence:
                return MemoSection(
                    title=title,
                    content=f"[No content found for {title}. Manual review required.]",
                    citations=[],
                    confidence_score=0.3,
                    claims=[],
                    evidence_chunks=[],
                    verification_summary=self.grounding.build_summary([]),
                )

            generation = self._generate(title, evidence)
            claims = self.grounding.extract_claims(
                generation.narrative,
                evidence,
                existing=generation.claims,
            )
            claims = self.grounding.verify_claims(claims, evidence)

            if not self.grounding.needs_repair(claims) or round_idx >= self.max_rounds:
                break

            query = self.grounding.gap_query(title, claims)

        assert generation is not None
        narrative = self.grounding.bracket_unsupported(generation.narrative, claims)
        summary = self.grounding.build_summary(claims)
        confidence = self.grounding.confidence_from_claims(claims)
        citations = self._citations_from_evidence(evidence, claims)

        return MemoSection(
            title=title,
            content=narrative.strip(),
            citations=citations,
            confidence_score=confidence,
            claims=claims,
            evidence_chunks=evidence,
            verification_summary=summary,
        )

    def _generate(self, title: str, evidence: list[EvidenceChunk]) -> SectionGeneration:
        context = "\n\n---\n\n".join(
            f"[{e.id}] ({e.doc} p.{e.page})\n{e.quote}" for e in evidence
        )
        time.sleep(API_DELAY_SEC)
        prompt = (
            f"Write a memo section '{title}' as structured JSON. "
            f"{self.SYNTHESIS_INSTRUCTION} "
            "Return JSON with keys: "
            "narrative (2-3 paragraphs), "
            "claims (array of {id, text, citation_ids}). "
            "Each claim id like c1, c2. citation_ids must be evidence ids like e1. "
            "If excerpts lack relevant info, say so briefly in narrative and emit few claims.\n\n"
            f"Evidence excerpts:\n{context[:20000]}"
        )
        try:
            resp = generate_content(
                self.client,
                model=self.model,
                contents=prompt,
                config={"temperature": 0.2, "response_mime_type": "application/json"},
                step="agent_generate",
            )
            data = json.loads(resp.text or "{}")
            claims = []
            for i, raw in enumerate(data.get("claims", [])):
                text = (raw.get("text") or "").strip()
                if not text:
                    continue
                claims.append(
                    GeneratedClaim(
                        id=str(raw.get("id") or f"c{i + 1}"),
                        text=text,
                        citation_ids=[str(x) for x in (raw.get("citation_ids") or [])],
                    )
                )
            narrative = (data.get("narrative") or "").strip()
            if not narrative and claims:
                narrative = " ".join(c.text for c in claims)
            return SectionGeneration(narrative=narrative or f"[No content generated for {title}.]", claims=claims)
        except Exception as e:
            return SectionGeneration(
                narrative=f"[Generation failed: {e}. Manual review required.]",
                claims=[],
            )

    @staticmethod
    def _chunks_to_evidence(top_chunks: list[tuple[DocChunk, float]]) -> list[EvidenceChunk]:
        evidence: list[EvidenceChunk] = []
        for i, (dc, _) in enumerate(top_chunks):
            doc = dc.doc_name.split("::")[0]
            evidence.append(
                EvidenceChunk(
                    id=f"e{i + 1}",
                    doc=doc,
                    page=dc.page,
                    quote=dc.text[:1500],
                )
            )
        return evidence

    @staticmethod
    def _citations_from_evidence(
        evidence: list[EvidenceChunk], claims: list
    ) -> list[Citation]:
        used_ids = {cid for c in claims for cid in c.citation_ids}
        by_id = {e.id: e for e in evidence}
        citations: list[Citation] = []
        seen: set[tuple[str, int]] = set()
        for eid in used_ids or [e.id for e in evidence]:
            ev = by_id.get(eid)
            if not ev:
                continue
            key = (ev.doc, ev.page)
            if key in seen:
                continue
            seen.add(key)
            citations.append(Citation(doc=ev.doc, page=ev.page))
        if not citations:
            for ev in evidence:
                key = (ev.doc, ev.page)
                if key not in seen:
                    seen.add(key)
                    citations.append(Citation(doc=ev.doc, page=ev.page))
        return citations
