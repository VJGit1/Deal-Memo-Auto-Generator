"""
DMAG - Deal Memo Auto Generator

Workflow: Automates due diligence into a structured investment memo.
Primary User: Associate / Analyst
Does NOT automate: final judgement, risk assessment.

Run: python src/app.py
"""

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from config import API_DELAY_SEC, RAW_DIR, TOP_K_CHUNKS
from schema import MemoOutput, MemoSection
from models import DocChunk
from ingest import Ingestor
from chunker import Chunker
from synthesis import Synthesizer, TemplateMapper
from financial import FinancialExtractor, Reconciler
from exporter import Exporter

load_dotenv()
client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))


def main() -> None:
    # Step 1: Ingest & Parse
    ingestor = Ingestor()
    chunks = ingestor.ingest()
    print(f"Step 1 Ingest: {len(chunks)} chunks from {RAW_DIR}")

    # Step 2: Semantic Chunking
    chunker = Chunker(client)
    index = chunker.build_index(chunks)
    print(f"Step 2 Chunking: {len(index)} chunks indexed")

    # Step 3: Template Mapping
    mapper = TemplateMapper()
    headers = mapper.get_headers()
    print(f"Step 3 Template: sections = {headers}")

    # Step 4: Agentic Synthesis
    synthesizer = Synthesizer(client)
    sections: list[MemoSection] = []
    for title in headers:
        top = chunker.retrieve_top_k(title, top_k=TOP_K_CHUNKS)
        sec = synthesizer.synthesize_section(title, top)
        sections.append(sec)

    # Step 5: Financial Auto-Fill
    extractor = FinancialExtractor(client)
    all_evidence = []
    seen_docs = {dc.doc_name for dc, _ in index}
    for doc_name in seen_docs:
        text = "\n\n".join(dc.text for dc, _ in index if dc.doc_name == doc_name)
        all_evidence.extend(extractor.extract(text, doc_name))

    # Attach evidence to financial section
    for sec in sections:
        if "financial" in sec.title.lower() or "metric" in sec.title.lower():
            sec.financial_evidence = all_evidence
            break

    # Company name
    company_name = "Unknown"
    for dc, _ in index:
        if len(dc.text) > 500:
            try:
                time.sleep(API_DELAY_SEC)
                r = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"Extract company name only. JSON: {{\"company_name\": \"...\"}}\n\n{dc.text[:3000]}",
                    config={"temperature": 0, "response_mime_type": "application/json"},
                )
                data = json.loads(r.text or "{}")
                company_name = data.get("company_name", company_name)
                break
            except Exception:
                pass

    # Step 6: Fact-Check & Reconcile
    reconciler = Reconciler()
    _, flags = reconciler.reconcile(all_evidence)
    if flags:
        print(f"Step 6 Reconcile: {flags}")

    # Step 7: Evidence Appendix
    exporter = Exporter()
    appendix = exporter.build_appendix(sections)
    print(f"Step 7 Appendix: {len(appendix)} entries")

    # Build output
    memo = MemoOutput(
        output_type="memo",
        company_name=company_name,
        sections=sections,
        flags=flags,
        evidence_appendix=appendix,
    )

    # Step 8: Export
    exporter.export(memo)

    # Human-in-the-Loop
    from config import CONFIDENCE_THRESHOLD
    low = [s.title for s in sections if s.confidence_score < CONFIDENCE_THRESHOLD]
    if low:
        print(f"Human-in-the-Loop: Review required for {low}")


if __name__ == "__main__":
    main()
