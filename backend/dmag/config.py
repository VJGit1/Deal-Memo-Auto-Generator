"""
DMAG Configuration.

Centralizes paths, constants, and settings.
Primary User: Associate / Analyst
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Paths (backend/ directory) — package lives at backend/dmag/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT.parent

load_dotenv(REPO_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env")

RAW_DIR = PROJECT_ROOT / "data" / "raw"
TEMPLATE_PATH = PROJECT_ROOT / "templates" / "memo_template.docx"
OUTPUT_DIR = PROJECT_ROOT / "output"

# Output files (in output/ folder)
OUTPUT_DOCX = OUTPUT_DIR / "final_memo.docx"
OUTPUT_JSON = OUTPUT_DIR / "final_memo_metadata.json"

# LLM
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
API_DELAY_SEC = 2
EMBED_MODELS = ["gemini-embedding-001", "text-embedding-004"]
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "5"))

# RAG & Chunking
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
TOP_K = 5
TOP_K_CHUNKS = TOP_K  # alias kept for existing call sites
RERANK_CANDIDATES = 20  # hybrid candidate pool before cutting to TOP_K
EMBED_BATCH_SIZE = 16
EMBED_MAX_RETRIES = 5
RRF_K = 60  # Reciprocal Rank Fusion constant
MAX_PAGES_PER_PDF = 25
MAX_TEXT_CHARS = 60000

# Quality & Safety (Human-in-the-Loop)
CONFIDENCE_THRESHOLD = 0.7  # Below this → mandatory manual review
MAX_AGENT_ROUNDS = 2  # generate → verify → re-retrieve repair rounds

# Financial reconciliation: relative tolerance on normalized magnitudes
# e.g. 0.01 → flag when |a-b| / max(|a|,|b|) > 1%
RECONCILE_RELATIVE_TOLERANCE = 0.01

# Jobs (Redis + RQ)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RQ_QUEUE_NAME = os.getenv("RQ_QUEUE_NAME", "dmag")
JOB_TTL_SEC = int(os.getenv("JOB_TTL_SEC", "86400"))  # Redis key + artifact TTL
JOB_TIMEOUT_SEC = int(os.getenv("JOB_TIMEOUT_SEC", "1800"))  # RQ worker timeout
