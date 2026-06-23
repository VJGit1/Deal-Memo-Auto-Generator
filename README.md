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
frontend/       # React + Vite UI
backend/
  api/
    main.py     # FastAPI routes
    jobs.py     # Background pipeline jobs
  src/
    app.py      # CLI orchestrator
    pipeline.py # Shared 8-step pipeline
    config.py   # Paths, constants
    ingest.py   # Ingestor class
    chunker.py  # Chunker class
    synthesis.py
    financial.py
    exporter.py
    schema.py
  data/raw/     # Place DD documents here (CLI mode)
  templates/    # memo_template.docx
  output/       # final_memo.docx, final_memo_metadata.json
```

## Run

Add `GEMINI_API_KEY` to `.env` at the **repo root**.

**Backend** (terminal 1):

```bash
cd backend      # Windows
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

**Frontend** (terminal 2):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend on port 8000.

**Optional CLI** (batch mode, reads from `backend/data/raw/`):

```bash
cd backend
python src/app.py
```
