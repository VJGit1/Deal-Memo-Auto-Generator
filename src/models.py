"""
DMAG Data Models.

Simple dataclasses for internal use.
"""

from dataclasses import dataclass


@dataclass
class DocChunk:
    """A chunk of document text with metadata for RAG."""

    text: str
    doc_name: str
    page: int
    chunk_id: str
