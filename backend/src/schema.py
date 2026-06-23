"""
Pydantic v2 schemas for DMAG (Deal Memo Auto Generator).

Aligns with proposal: Evidence Gating, Accountability, Transparency.
CRM-ready JSON output structure.
"""

from typing import Annotated

from pydantic import BaseModel, Field


# --- Citation: maps to proposal format {doc, page} ---
class Citation(BaseModel):
    """Inline citation pointing to source document and page."""

    doc: Annotated[str, Field(description="Source document filename (e.g., 'Pitch_Deck.pdf').")]
    page: Annotated[int, Field(description="Page number (1-based).", ge=1)]


# --- Financial evidence with full audit trail ---
class FinancialEvidence(BaseModel):
    """Single financial metric with exact quote for audit trail. Evidence Gating: no unsourced claims."""

    metric_name: Annotated[
        str,
        Field(
            description="Metric name as stated in document (e.g., 'Revenue', 'Net Income'). Extract exactly."
        ),
    ]
    value: Annotated[
        str | int | float,
        Field(
            description="Value exactly as in source. Preserve format (e.g., '52.9B'). Do not convert."
        ),
    ]
    fiscal_year: Annotated[
        str,
        Field(
            description="Fiscal year/period as stated (e.g., 'FY2024'). Extract verbatim."
        ),
    ]
    source_quote: Annotated[
        str,
        Field(
            description="Exact verbatim sentence from document. Required for audit trail."
        ),
    ]
    page_number: Annotated[
        int,
        Field(description="Page number in source document (1-based).", ge=1),
    ]
    doc_name: Annotated[
        str,
        Field(
            description="Source document filename (e.g., '10-K.pdf').",
            default="unknown",
        ),
    ]


# --- Memo section: proposal format ---
class MemoSection(BaseModel):
    """One section of the memo with content, citations, and confidence."""

    title: Annotated[
        str,
        Field(description="Section title (e.g., 'Executive Summary', 'Key Financial Metrics')."),
    ]
    content: Annotated[
        str,
        Field(
            description="2–3 paragraphs. Every fact must have a citation. Closed-book: no unsourced claims."
        ),
    ]
    citations: Annotated[
        list[Citation],
        Field(
            description="List of {doc, page} for inline references. Each cited fact must appear here.",
            default_factory=list,
        ),
    ]
    confidence_score: Annotated[
        float,
        Field(
            description="Confidence 0.0–1.0. Sections below 0.7 require mandatory manual review.",
            ge=0.0,
            le=1.0,
        ),
    ]
    financial_evidence: Annotated[
        list[FinancialEvidence],
        Field(
            description="Financial metrics for this section with full audit trail.",
            default_factory=list,
        ),
    ]


# --- Full memo output: CRM-ready JSON ---
class MemoOutput(BaseModel):
    """Final memo structure for export. Matches proposal schema."""

    output_type: Annotated[
        str,
        Field(description="Always 'memo' for CRM integration.", default="memo"),
    ]
    company_name: Annotated[str, Field(description="Company name from documents.")]
    sections: Annotated[
        list[MemoSection],
        Field(description="Memo sections with content and citations."),
    ]
    flags: Annotated[
        list[str],
        Field(
            description="Discrepancy flags (e.g., 'Revenue discrepancy: CIM vs. Tax Filing').",
            default_factory=list,
        ),
    ]
    evidence_appendix: Annotated[
        list[dict],
        Field(
            description="Appendix mapping citations to exact quotes. For audit trail.",
            default_factory=list,
        ),
    ]


# --- LLM extraction schema ---
class ExtractionResult(BaseModel):
    """LLM output when extracting from a document."""

    company_name: Annotated[str, Field(description="Company name as stated.")]
    section_content: Annotated[
        str,
        Field(description="2–3 paragraphs summarizing the document. Every fact must be in financial_evidence."),
    ]
    financial_evidence: Annotated[
        list[FinancialEvidence],
        Field(description="Financial metrics with source_quote and page_number.", default_factory=list),
    ]
