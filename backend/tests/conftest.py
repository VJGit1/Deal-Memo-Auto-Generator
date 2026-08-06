"""Shared pytest fixtures for DMAG unit + eval tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
EVALS_ROOT = BACKEND_ROOT / "evals"
GOLD_DEAL = EVALS_ROOT / "fixtures" / "gold_deal"


@pytest.fixture
def gold_deal_dir() -> Path:
    return GOLD_DEAL


@pytest.fixture
def expected_json(gold_deal_dir: Path) -> dict:
    return json.loads((gold_deal_dir / "expected.json").read_text(encoding="utf-8"))


@pytest.fixture
def cassette_json(gold_deal_dir: Path) -> dict:
    return json.loads((gold_deal_dir / "gemini_cassette.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _zero_api_delay(monkeypatch):
    """Keep unit/eval smoke tests fast (no Gemini sleep)."""
    modules = (
        "dmag.config",
        "dmag.grounding",
        "dmag.financial",
        "dmag.agent_loop",
        "dmag.synthesis",
    )
    for name in modules:
        try:
            mod = __import__(name, fromlist=["*"])
            if hasattr(mod, "API_DELAY_SEC"):
                monkeypatch.setattr(mod, "API_DELAY_SEC", 0)
        except Exception:
            pass
