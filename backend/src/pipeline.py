"""
DMAG pipeline orchestrator.

Shared by CLI (app.py) and FastAPI backend.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from google import genai

from config import (
    API_DELAY_SEC,
    CONFIDENCE_THRESHOLD,
    GEMINI_MODEL,
    OUTPUT_DIR,
    RAW_DIR,
    TEMPLATE_PATH,
    TOP_K_CHUNKS,
)
from schema import MemoOutput, MemoSection
from ingest import Ingestor
from chunker import Chunker
from synthesis import Synthesizer, TemplateMapper
from financial import FinancialExtractor, Reconciler
from exporter import Exporter

ProgressCallback = Callable[[int, int, str], None]

STEP_LABELS = [
    "Ingest & Parse",
    "Semantic Chunking",
    "Template Mapping",
    "Agentic Synthesis",
    "Financial Auto-Fill",
    "Fact-Check & Reconcile",
    "Evidence Appendix",
    "Export",
]


@dataclass
class PipelineResult:
    """Pipeline output with paths and run statistics."""

    memo: MemoOutput
    output_docx: Path
    output_json: Path
    doc_count: int = 0
    chunk_count: int = 0
    section_count: int = 0
    flag_count: int = 0
    log: list[str] = field(default_factory=list)


def _notify(on_progress: ProgressCallback | None, step: int, message: str) -> None:
    if on_progress:
        on_progress(step, len(STEP_LABELS), message)


def run_pipeline(
    raw_dir: Path | None = None,
    template_path: Path | None = None,
    output_dir: Path | None = None,
    on_progress: ProgressCallback | None = None,
    company_name_override: str | None = None,
    confidence_threshold: float | None = None,
) -> PipelineResult:
    """
    Run the full 8-step DMAG pipeline.

    Returns PipelineResult with memo, export paths, and stats.
    """
    raw_dir = raw_dir or RAW_DIR
    template_path = template_path or TEMPLATE_PATH
    output_dir = output_dir or OUTPUT_DIR
    threshold = confidence_threshold if confidence_threshold is not None else CONFIDENCE_THRESHOLD
    log: list[str] = []

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    # Step 1: Ingest & Parse
    _notify(on_progress, 1, "Ingesting due diligence documents...")
    ingestor = Ingestor(raw_dir=raw_dir)
    chunks = ingestor.ingest()
    seen_docs = {c.doc_name for c in chunks}
    doc_count = len(seen_docs)
    msg = f"Ingested {len(chunks)} chunks from {doc_count} document(s)"
    log.append(msg)
    _notify(on_progress, 1, msg)

    # Step 2: Semantic Chunking
    _notify(on_progress, 2, "Building embedding index for RAG retrieval...")
    chunker = Chunker(client)
    index = chunker.build_index(chunks)
    chunk_count = len(index)
    msg = f"Indexed {chunk_count} chunks"
    log.append(msg)
    _notify(on_progress, 2, msg)

    # Step 3: Template Mapping
    _notify(on_progress, 3, "Parsing memo template for section headers...")
    mapper = TemplateMapper(template_path=template_path)
    headers = mapper.get_headers()
    msg = f"Template sections: {', '.join(headers)}"
    log.append(msg)
    _notify(on_progress, 3, msg)

    # Step 4: Agentic Synthesis
    _notify(on_progress, 4, "Synthesizing memo sections from retrieved evidence...")
    synthesizer = Synthesizer(client)
    sections: list[MemoSection] = []
    for i, title in enumerate(headers):
        _notify(on_progress, 4, f"Synthesizing section {i + 1}/{len(headers)}: {title}")
        top = chunker.retrieve_top_k(title, top_k=TOP_K_CHUNKS)
        sec = synthesizer.synthesize_section(title, top)
        sections.append(sec)
    msg = f"Generated {len(sections)} memo sections"
    log.append(msg)
    _notify(on_progress, 4, msg)

    # Step 5: Financial Auto-Fill
    _notify(on_progress, 5, "Extracting financial metrics with Pydantic validation...")
    extractor = FinancialExtractor(client)
    all_evidence = []
    index_docs = {dc.doc_name for dc, _ in index}
    for doc_name in index_docs:
        _notify(on_progress, 5, f"Extracting metrics from {doc_name}")
        text = "\n\n".join(dc.text for dc, _ in index if dc.doc_name == doc_name)
        all_evidence.extend(extractor.extract(text, doc_name))

    for sec in sections:
        if "financial" in sec.title.lower() or "metric" in sec.title.lower():
            sec.financial_evidence = all_evidence
            break

    msg = f"Extracted {len(all_evidence)} financial evidence record(s)"
    log.append(msg)
    _notify(on_progress, 5, msg)

    # Company name
    company_name = company_name_override or "Unknown"
    if not company_name_override:
        for dc, _ in index:
            if len(dc.text) > 500:
                try:
                    time.sleep(API_DELAY_SEC)
                    r = client.models.generate_content(
                        model=GEMINI_MODEL,
                        contents=(
                            f'Extract company name only. JSON: {{"company_name": "..."}}\n\n'
                            f"{dc.text[:3000]}"
                        ),
                        config={"temperature": 0, "response_mime_type": "application/json"},
                    )
                    data = json.loads(r.text or "{}")
                    company_name = data.get("company_name", company_name)
                    break
                except Exception:
                    pass

    # Step 6: Fact-Check & Reconcile
    _notify(on_progress, 6, "Reconciling metrics across source documents...")
    reconciler = Reconciler()
    _, flags = reconciler.reconcile(all_evidence)
    flag_count = len(flags)
    if flags:
        for f in flags:
            log.append(f"FLAG: {f}")
        _notify(on_progress, 6, f"Found {flag_count} reconciliation flag(s)")
    else:
        msg = "No cross-document discrepancies detected"
        log.append(msg)
        _notify(on_progress, 6, msg)

    # Step 7: Evidence Appendix
    _notify(on_progress, 7, "Building evidence appendix with verbatim quotes...")
    exporter = Exporter(
        template_path=template_path,
        output_dir=output_dir,
        confidence_threshold=threshold,
    )
    appendix = exporter.build_appendix(sections)
    msg = f"Appendix contains {len(appendix)} citation(s)"
    log.append(msg)
    _notify(on_progress, 7, msg)

    memo = MemoOutput(
        output_type="memo",
        company_name=company_name,
        sections=sections,
        flags=flags,
        evidence_appendix=appendix,
    )

    # Step 8: Export
    _notify(on_progress, 8, "Exporting memo to DOCX and CRM JSON...")
    exporter.export(memo)
    msg = f"Exported to {exporter.output_docx.name} and {exporter.output_json.name}"
    log.append(msg)
    _notify(on_progress, 8, msg)

    low = [s.title for s in sections if s.confidence_score < threshold]
    if low:
        review_msg = f"Human-in-the-Loop: review required for {', '.join(low)}"
        log.append(review_msg)
        _notify(on_progress, 8, review_msg)

    return PipelineResult(
        memo=memo,
        output_docx=exporter.output_docx,
        output_json=exporter.output_json,
        doc_count=doc_count,
        chunk_count=chunk_count,
        section_count=len(sections),
        flag_count=flag_count,
        log=log,
    )
