"""
Step 3: Template Mapping.
Step 4: Agentic Synthesis.

Parses memo_template.docx for section headers.
RAG: retrieves top-5 chunks per section, generates 2-3 paragraphs.
Evidence Gating: closed-book, no judgements or risk assessment.
"""

import time
from pathlib import Path

from docx import Document

from config import API_DELAY_SEC, CONFIDENCE_THRESHOLD, GEMINI_MODEL, TEMPLATE_PATH, TOP_K_CHUNKS
from schema import Citation, MemoSection
from models import DocChunk


class TemplateMapper:
    """Parses memo_template.docx for mandatory section headers."""

    def __init__(self, template_path: Path = TEMPLATE_PATH):
        self.template_path = template_path

    def get_headers(self) -> list[str]:
        if not self.template_path.exists():
            return ["Executive Summary", "Key Financial Metrics", "Market Overview"]

        doc = Document(self.template_path)
        skip = ("MEMORANDUM", "Company:", "Summary:", "Appendix")
        headers = []
        for p in doc.paragraphs:
            t = p.text.strip()
            if t and len(t) < 80 and "{{" not in t and not any(t.startswith(s) for s in skip):
                headers.append(t)
        return headers[:6] if headers else ["Executive Summary", "Key Financial Metrics"]


class Synthesizer:
    """
    RAG synthesis. For each section: generate 2-3 paragraphs from retrieved chunks.
    Does NOT give final judgement or risk assessment (per proposal).
    """

    # Prompt constraints: closed-book, no judgement, no risk assessment
    SYNTHESIS_INSTRUCTION = (
        "Use ONLY the following excerpts. Do not add information not in the excerpts. "
        "Do not give final judgement, investment recommendation, or risk assessment. "
        "Every factual claim must be traceable to the excerpts. Closed-book."
    )

    def __init__(self, client, model: str = GEMINI_MODEL):
        self.client = client
        self.model = model

    def synthesize_section(
        self, title: str, top_chunks: list[tuple[DocChunk, float]]
    ) -> MemoSection:
        """Generate 2-3 paragraphs for one section from retrieved chunks."""
        if not top_chunks:
            return MemoSection(
                title=title,
                content=f"[No content found for {title}. Manual review required.]",
                citations=[],
                confidence_score=0.3,
            )

        context = "\n\n---\n\n".join(
            f"[{dc.doc_name} p.{dc.page}]\n{dc.text}" for dc, _ in top_chunks
        )
        citations = [
            Citation(doc=dc.doc_name.split("::")[0], page=dc.page)
            for dc, _ in top_chunks
        ]

        time.sleep(API_DELAY_SEC)
        prompt = (
            f"Write 2-3 paragraphs for the memo section '{title}'. "
            f"{self.SYNTHESIS_INSTRUCTION} "
            "If excerpts lack relevant info, say so briefly.\n\n"
            f"Excerpts:\n{context[:20000]}"
        )

        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={"temperature": 0.2},
            )
            content = resp.text or ""
            conf = min(0.95, 0.5 + 0.1 * sum(1 for _, s in top_chunks if s > 0.3))
        except Exception as e:
            content = f"[Generation failed: {e}. Manual review required.]"
            conf = 0.2

        return MemoSection(
            title=title,
            content=content.strip(),
            citations=citations,
            confidence_score=conf,
        )
