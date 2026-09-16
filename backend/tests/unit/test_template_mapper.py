"""Unit tests for TemplateMapper and multi-section template export."""

from __future__ import annotations

from pathlib import Path
import tempfile
import docx

from dmag.config import TEMPLATE_PATH
from dmag.exporter import Exporter
from dmag.schema import Citation, MemoOutput, MemoSection
from dmag.synthesis import TemplateMapper


def test_template_mapper_parses_all_template_sections():
    """Verify TemplateMapper extracts all core diligence sections without truncation."""
    mapper = TemplateMapper(TEMPLATE_PATH)
    headers = mapper.get_headers()
    assert len(headers) >= 6
    assert "Executive Summary" in headers
    assert "Market & Industry Overview" in headers
    assert "Business & Product Overview" in headers
    assert "Key Financial Metrics" in headers
    assert "Management & Organization" in headers
    assert "Key Risks & Diligence Findings" in headers
    # Ensure appendix and header banners are excluded
    assert not any(h.lower().startswith("appendix") for h in headers)
    assert not any("investment memo" in h.lower() for h in headers)


def test_template_mapper_fallback_when_file_missing():
    """Verify TemplateMapper returns default sections when template path does not exist."""
    mapper = TemplateMapper(Path("/non/existent/path/template.docx"))
    headers = mapper.get_headers()
    assert len(headers) == 6
    assert headers[0] == "Executive Summary"


def test_exporter_renders_all_expanded_sections():
    """Verify Exporter populates per-section variables into docx export."""
    with tempfile.TemporaryDirectory() as tmpdir:
        outdir = Path(tmpdir)
        exporter = Exporter(template_path=TEMPLATE_PATH, output_dir=outdir)

        sections = [
            MemoSection(
                title="Executive Summary",
                content="Executive summary content for Acme.",
                citations=[Citation(doc="CIM.txt", page=1)],
                confidence_score=0.9,
            ),
            MemoSection(
                title="Market & Industry Overview",
                content="Market size is $10B growing at 15% CAGR.",
                citations=[],
                confidence_score=0.85,
            ),
            MemoSection(
                title="Business & Product Overview",
                content="Proprietary SaaS platform with automated workflows.",
                citations=[],
                confidence_score=0.9,
            ),
            MemoSection(
                title="Key Financial Metrics",
                content="ARR is $52.9M with 80% gross margin.",
                citations=[],
                confidence_score=0.95,
            ),
            MemoSection(
                title="Management & Organization",
                content="Leadership has 20+ years of domain experience.",
                citations=[],
                confidence_score=0.88,
            ),
            MemoSection(
                title="Key Risks & Diligence Findings",
                content="Customer concentration risk with top client at 22% of ARR.",
                citations=[],
                confidence_score=0.8,
            ),
        ]
        memo = MemoOutput(
            company_name="Acme Corp",
            sections=sections,
            flags=[],
            evidence_appendix=[],
        )

        res = exporter.export(memo)
        assert res["docx"].exists()
        assert res["json"].exists()

        doc = docx.Document(res["docx"])
        doc_text = "\n".join(p.text for p in doc.paragraphs)
        assert "Acme Corp" in doc_text
        assert "Executive summary content for Acme." in doc_text
        assert "Market size is $10B growing at 15% CAGR." in doc_text
        assert "Proprietary SaaS platform with automated workflows." in doc_text
        assert "ARR is $52.9M with 80% gross margin." in doc_text
        assert "Leadership has 20+ years of domain experience." in doc_text
        assert "Customer concentration risk with top client at 22% of ARR." in doc_text
