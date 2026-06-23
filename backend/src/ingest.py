"""
Step 1: Ingest & Parse.

Loads DD materials: PDF, CSV, Excel, Word, meeting transcripts (.txt).
Uses pandas for Excel/CSV. pdfplumber for PDF text.
"""

from pathlib import Path

import pandas as pd
import pdfplumber

from config import MAX_PAGES_PER_PDF, MAX_TEXT_CHARS, RAW_DIR
from models import DocChunk


class Ingestor:
    """Loads due diligence documents from a folder."""

    def __init__(self, raw_dir: Path = RAW_DIR):
        self.raw_dir = raw_dir

    def ingest(self) -> list[DocChunk]:
        """Load all documents. Returns list of chunks with doc name and page."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        chunks: list[DocChunk] = []

        for path in sorted(self.raw_dir.glob("*.pdf")):
            chunks.extend(self._parse_pdf(path))
        for path in sorted(self.raw_dir.glob("*.csv")):
            chunks.extend(self._parse_csv(path))
        for path in sorted(self.raw_dir.glob("*.xlsx")):
            chunks.extend(self._parse_excel(path))
        for path in sorted(self.raw_dir.glob("*.docx")):
            if "memo_template" not in path.name.lower():
                chunks.extend(self._parse_docx(path))
        for path in sorted(self.raw_dir.glob("*.txt")):
            chunks.extend(self._parse_txt(path))

        if not chunks:
            raise FileNotFoundError(
                f"No documents in {self.raw_dir}. Add PDF, CSV, xlsx, docx, or txt."
            )
        return chunks

    def _parse_pdf(self, path: Path) -> list[DocChunk]:
        chunks = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= MAX_PAGES_PER_PDF:
                    break
                text = page.extract_text()
                if text and text.strip():
                    chunks.append(
                        DocChunk(
                            text=text[: MAX_TEXT_CHARS // MAX_PAGES_PER_PDF],
                            doc_name=path.name,
                            page=i + 1,
                            chunk_id=f"{path.stem}_p{i + 1}",
                        )
                    )
        return chunks

    def _parse_csv(self, path: Path) -> list[DocChunk]:
        df = pd.read_csv(path, on_bad_lines="skip")
        return [
            DocChunk(
                text=df.to_string()[:MAX_TEXT_CHARS],
                doc_name=path.name,
                page=1,
                chunk_id=f"{path.stem}_sheet1",
            )
        ]

    def _parse_excel(self, path: Path) -> list[DocChunk]:
        chunks = []
        xl = pd.ExcelFile(path)
        for sheet in xl.sheet_names:
            df = pd.read_excel(xl, sheet_name=sheet)
            text = df.to_string()
            if text.strip():
                chunks.append(
                    DocChunk(
                        text=text[: MAX_TEXT_CHARS // max(len(xl.sheet_names), 1)],
                        doc_name=f"{path.name}::{sheet}",
                        page=1,
                        chunk_id=f"{path.stem}_{sheet}",
                    )
                )
        return chunks or [
            DocChunk(text="(empty)", doc_name=path.name, page=1, chunk_id=path.stem)
        ]

    def _parse_docx(self, path: Path) -> list[DocChunk]:
        from docx import Document

        doc = Document(path)
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip()) or "(no text)"
        return [
            DocChunk(
                text=text[:MAX_TEXT_CHARS],
                doc_name=path.name,
                page=1,
                chunk_id=path.stem,
            )
        ]

    def _parse_txt(self, path: Path) -> list[DocChunk]:
        """Meeting transcripts and other plain text."""
        text = path.read_text(encoding="utf-8", errors="ignore").strip() or "(empty)"
        return [
            DocChunk(
                text=text[:MAX_TEXT_CHARS],
                doc_name=path.name,
                page=1,
                chunk_id=path.stem,
            )
        ]
