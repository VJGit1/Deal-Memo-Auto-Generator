# DMAG - Deal Memo Auto Generator

Automates due diligence into a structured investment memo for Associates/Analysts.
Reduces memo drafting from hours to minutes. Citations ensure all numbers trace to DD.

## Proposal Alignment

| Requirement | Implementation |
|-------------|----------------|
| **Workflow** | Deal Memo Auto Generator (DMAG) |
| **Goal** | Automates DD → memo. Does NOT give judgement or risk assessment. |
| **Inputs** | PDF, CSV, Excel, Word, .txt (meeting transcripts), memo_template.docx |
| **Outputs** | Editable docx, appendix of citations, JSON for CRM |
| **Schema** | `{output_type, sections: [{title, content, citations, confidence_score}], flags}` |

## 8-Step Workflow

1. **Ingest & Parse** – `ingest.py` – PDF, CSV, Excel, docx, txt
2. **Semantic Chunking** – `chunker.py` – Embed with Gemini, index for RAG
3. **Template Mapping** – `synthesis.py` – Parse memo_template.docx for headers
4. **Agentic Synthesis** – `synthesis.py` – RAG top-5 chunks → 2–3 paragraphs/section
5. **Financial Auto-Fill** – `financial.py` – Pydantic validation
6. **Fact-Check & Reconcile** – `financial.py` – Flag discrepancies (e.g. CIM vs Tax)
7. **Evidence Appendix** – `exporter.py` – Map citations to exact quotes
8. **Export** – `exporter.py` – docx + JSON to `output/` folder

## Quality & Safety

- **Evidence Gating**: Closed-book; only info from provided docs
- **Conflict Detection**: Flags e.g. "Revenue discrepancy: Pitch_Deck.pdf vs Tax_Return.pdf"
- **Human-in-the-Loop**: Sections with confidence < 0.7 marked for mandatory review

## Structure

```
src/
  app.py        # Orchestrator (~100 lines)
  config.py     # Paths, constants
  models.py     # DocChunk
  ingest.py     # Ingestor class
  chunker.py    # Chunker class
  synthesis.py  # TemplateMapper, Synthesizer
  financial.py  # FinancialExtractor, Reconciler
  exporter.py   # Exporter
  web_enrichment.py  # Stub for LinkedIn/G2 (optional)
  schema.py     # Pydantic schemas

data/raw/       # Place DD documents here
templates/      # memo_template.docx
output/         # final_memo.docx, final_memo_metadata.json
```

## Run

```bash
pip install -r requirements.txt
# Add GEMINI_API_KEY to .env
python src/app.py
```
