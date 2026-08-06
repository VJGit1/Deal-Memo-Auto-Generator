"""
Step 3: Template Mapping.
Step 4: Grounded Synthesis (delegates to agent loop).

Parses memo_template.docx for section headers.
"""

from pathlib import Path

from docx import Document

from .config import TEMPLATE_PATH, TOP_K
from .schema import MemoSection


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
    Thin wrapper around AgentLoop for backwards-compatible call sites.
    Prefer AgentLoop.run_section for new code.
    """

    def __init__(self, client, chunker=None, model: str | None = None):
        from .agent_loop import AgentLoop
        from .config import GEMINI_MODEL

        self.client = client
        self.chunker = chunker
        self.model = model or GEMINI_MODEL
        self._loop = AgentLoop(client, chunker, model=self.model) if chunker is not None else None

    def synthesize_section(
        self, title: str, top_chunks=None, top_k: int = TOP_K
    ) -> MemoSection:
        """Generate a grounded section via the agent loop (retrieve handled by loop)."""
        if self._loop is None:
            raise RuntimeError("Synthesizer requires a chunker for grounded synthesis")
        return self._loop.run_section(title, top_k=top_k)
