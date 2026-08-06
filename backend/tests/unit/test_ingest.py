"""Unit tests for Ingestor against gold_deal fixture files."""

from __future__ import annotations

from pathlib import Path

import pytest

from dmag.ingest import Ingestor


def test_ingest_gold_deal_txt_and_csv(gold_deal_dir: Path):
    chunks = Ingestor(raw_dir=gold_deal_dir).ingest()
    doc_names = {c.doc_name for c in chunks}
    assert "CIM.txt" in doc_names
    assert "Tax_Return.txt" in doc_names
    assert "Meeting_Notes.txt" in doc_names
    assert "financials.csv" in doc_names

    cim = next(c for c in chunks if c.doc_name == "CIM.txt")
    assert "Acme Robotics" in cim.text
    assert "52.9M" in cim.text
    assert cim.page == 1
    assert cim.chunk_id


def test_ingest_empty_dir_raises(tmp_path: Path):
    empty = tmp_path / "empty_raw"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="No documents"):
        Ingestor(raw_dir=empty).ingest()


def test_parse_txt_direct(gold_deal_dir: Path):
    ing = Ingestor(raw_dir=gold_deal_dir)
    chunks = ing._parse_txt(gold_deal_dir / "Tax_Return.txt")
    assert len(chunks) == 1
    assert "48.4" in chunks[0].text or "48,400,000" in chunks[0].text


def test_parse_csv_direct(gold_deal_dir: Path):
    ing = Ingestor(raw_dir=gold_deal_dir)
    chunks = ing._parse_csv(gold_deal_dir / "financials.csv")
    assert len(chunks) == 1
    assert "Revenue" in chunks[0].text
    assert chunks[0].chunk_id.endswith("_sheet1") or "financials" in chunks[0].chunk_id
