"""
Step 2: Semantic Chunking.

Splits documents into chunks, embeds with Gemini.
Indexes for RAG retrieval. Uses keyword fallback if embeddings fail.
"""

import math
import time

from config import API_DELAY_SEC, CHUNK_SIZE, EMBED_MODELS
from models import DocChunk


class Chunker:
    """Chunks documents and builds embedding index for RAG."""

    def __init__(self, client, chunk_size: int = CHUNK_SIZE):
        self.client = client
        self.chunk_size = chunk_size
        self._index: list[tuple[DocChunk, list[float]]] = []

    def build_index(self, chunks: list[DocChunk]) -> list[tuple[DocChunk, list[float]]]:
        """Split long texts, embed each chunk. Returns (chunk, embedding) pairs."""
        expanded = self._expand_chunks(chunks)
        self._index = []
        for i, dc in enumerate(expanded):
            if i > 0:
                time.sleep(API_DELAY_SEC)
            emb = self._embed(dc.text)
            self._index.append((dc, emb))
        return self._index

    def _expand_chunks(self, chunks: list[DocChunk]) -> list[DocChunk]:
        expanded = []
        for dc in chunks:
            if len(dc.text) <= self.chunk_size:
                expanded.append(dc)
            else:
                for i, start in enumerate(range(0, len(dc.text), self.chunk_size)):
                    sub = dc.text[start : start + self.chunk_size]
                    expanded.append(
                        DocChunk(
                            text=sub,
                            doc_name=dc.doc_name,
                            page=dc.page,
                            chunk_id=f"{dc.chunk_id}_part{i}",
                        )
                    )
        return expanded

    def _embed(self, text: str) -> list[float]:
        for model in EMBED_MODELS:
            try:
                r = self.client.models.embed_content(model=model, contents=text)
                if r.embeddings and r.embeddings[0].values:
                    return r.embeddings[0].values
            except Exception:
                continue
        return [0.0] * 768

    def retrieve_top_k(
        self, query: str, top_k: int = 5
    ) -> list[tuple[DocChunk, float]]:
        """Retrieve top-k chunks by similarity to query. Uses keyword fallback if no embeddings."""
        if not self._index:
            return []

        time.sleep(API_DELAY_SEC)
        query_emb = self._embed(query)
        has_valid_emb = sum(x * x for x in query_emb) > 0

        def score(dc: DocChunk, emb: list[float]) -> float:
            if has_valid_emb and emb and sum(x * x for x in emb) > 0:
                return _cosine_similarity(query_emb, emb)
            kw = set(query.lower().split()) & set(dc.text.lower().split())
            return len(kw) / max(len(set(query.lower().split())), 1)

        scored = [(dc, emb, score(dc, emb)) for dc, emb in self._index]
        scored.sort(key=lambda x: x[2], reverse=True)
        return [(dc, s) for dc, _, s in scored[:top_k]]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(x * x for x in b)) or 1e-9
    return dot / (na * nb)
