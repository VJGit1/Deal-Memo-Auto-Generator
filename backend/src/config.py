"""
DMAG Configuration.

Centralizes paths, constants, and settings.
Primary User: Associate / Analyst
"""

from pathlib import Path

from dotenv import load_dotenv

# Paths (backend/ directory)
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
GEMINI_MODEL = "gemini-2.5-flash"  # gemini-1.5-flash deprecated; use available model
API_DELAY_SEC = 2
EMBED_MODELS = ["gemini-embedding-001", "text-embedding-004"]

# RAG & Chunking
CHUNK_SIZE = 800
TOP_K_CHUNKS = 5
MAX_PAGES_PER_PDF = 25
MAX_TEXT_CHARS = 60000

# Quality & Safety (Human-in-the-Loop)
CONFIDENCE_THRESHOLD = 0.7  # Below this → mandatory manual review
