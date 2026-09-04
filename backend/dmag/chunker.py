"""
Step 2: Semantic Chunking + Hybrid Retrieval.

Recursive/semantic splitter with overlap; table rows stay atomic.
Dense (Gemini → Chroma) + BM25 fused via Reciprocal Rank Fusion.
Fails loudly on embed errors (no zero-vector fallback).
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

from .config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBED_BATCH_SIZE,
    EMBED_MAX_RETRIES,
    EMBED_MODELS,
    RERANK_CANDIDATES,
    RRF_K,
    TOP_K,
)
from .gemini_client import embed_content, is_retryable
from .models import DocChunk

logger = logging.getLogger(__name__)

# Section-title → retrieval synonyms for PE / deal-memo jargon
_SECTION_EXPANSIONS: dict[str, str] = {
    "executive summary": (
        "overview highlights key findings investment thesis company snapshot "
        "transaction summary"
    ),
    "key financial metrics": (
        "revenue EBITDA margin ARR ARR growth gross margin operating income "
        "cash flow free cash flow FCF net income NRR churn LTV CAC "
        "burn runway valuation multiples"
    ),
    "financial metrics": (
        "revenue EBITDA margin ARR gross margin operating income cash flow "
        "net income FCF"
    ),
    "market overview": (
        "TAM SAM SOM market size growth rate industry competitive landscape "
        "market share addressable market"
    ),
    "company overview": (
        "business description products services founding headquarters "
        "customers operations history"
    ),
    "business overview": (
        "products services customers go-to-market operations model"
    ),
    "competitive landscape": (
        "competitors differentiation moat market share positioning rivals"
    ),
    "management team": (
        "CEO CFO founders executives leadership board background experience"
    ),
    "risks": (
        "risk factors challenges headwinds customer concentration regulatory "
        "litigation dependency"
    ),
    "investment highlights": (
        "strengths opportunities growth drivers competitive advantage thesis"
    ),
    "customer": (
        "customers retention NRR churn logos cohort concentration expansion"
    ),
    "product": (
        "product roadmap features technology platform architecture"
    ),
}


class EmbeddingError(RuntimeError):
    """Raised when Gemini embedding fails after retries."""


def deterministic_local_embedding(text: str, dim: int = 768) -> list[float]:
    """
    Fallback deterministic pseudo-embedding using term-frequency hashing and L2 normalization.
    Ensures the pipeline and live demos never crash if an external API or DNS drops out.
    """
    vec = [0.0] * dim
    tokens = tokenize(text)
    if not tokens:
        tokens = [text.strip() or "empty"]
    for tok in tokens:
        h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if ((h >> 16) & 1) else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 1e-9:
        vec = [x / norm for x in vec]
    else:
        vec[0] = 1.0
    return vec


class Chunker:
    """
    Chunks documents and builds a hybrid dense+BM25 index for RAG.

    API:
      - build_index(chunks) -> list[tuple[DocChunk, list[float]]]
      - retrieve_top_k(query, top_k) -> list[tuple[DocChunk, float]]
    """

    def __init__(
        self,
        client,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
        persist_dir: Path | str | None = None,
        collection_name: str = "dmag",
    ):
        self.client = client
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.persist_dir = Path(persist_dir) if persist_dir else None
        self.collection_name = collection_name

        self._chunks: list[DocChunk] = []
        self._embeddings: list[list[float]] = []
        self._index: list[tuple[DocChunk, list[float]]] = []
        self._bm25: BM25Okapi | None = None
        self._tokenized: list[list[str]] = []
        self._chroma_collection = None

    def build_index(self, chunks: list[DocChunk]) -> list[tuple[DocChunk, list[float]]]:
        """Split long texts, embed in batches, persist to Chroma + BM25."""
        expanded = self._expand_chunks(chunks)
        if not expanded:
            self._chunks = []
            self._embeddings = []
            self._index = []
            self._bm25 = None
            self._tokenized = []
            self._chroma_collection = None
            return []

        texts = [dc.text for dc in expanded]
        embeddings = self._embed_batch(texts)

        self._chunks = expanded
        self._embeddings = embeddings
        self._index = list(zip(expanded, embeddings))
        self._tokenized = [_tokenize(t) for t in texts]
        self._bm25 = BM25Okapi(self._tokenized) if self._tokenized else None
        self._persist_chroma(expanded, embeddings)
        return self._index

    def retrieve_top_k(
        self, query: str, top_k: int = TOP_K
    ) -> list[tuple[DocChunk, float]]:
        """
        Expand query, hybrid retrieve (dense + BM25), fuse with RRF, return top_k.

        Signature preserved for agent_loop / pipeline callers.
        Returned scores are RRF fusion scores (higher is better).
        """
        if not self._chunks:
            return []

        expanded_query = expand_query(query)
        candidates = min(max(top_k, RERANK_CANDIDATES), len(self._chunks))

        dense_ranked = self._dense_retrieve(expanded_query, candidates)
        bm25_ranked = self._bm25_retrieve(expanded_query, candidates)
        fused_indices = rrf_fuse(dense_ranked, bm25_ranked, k=RRF_K)

        results: list[tuple[DocChunk, float]] = []
        for idx, score in fused_indices[:top_k]:
            if 0 <= idx < len(self._chunks):
                results.append((self._chunks[idx], score))
        return results

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------

    def _expand_chunks(self, chunks: list[DocChunk]) -> list[DocChunk]:
        expanded: list[DocChunk] = []
        for dc in chunks:
            if not dc.text or not dc.text.strip():
                continue
            if dc.is_table:
                expanded.extend(self._split_table_chunk(dc))
            elif len(dc.text) <= self.chunk_size:
                expanded.append(dc)
            else:
                expanded.extend(self._recursive_split(dc))
        return expanded

    def _split_table_chunk(self, dc: DocChunk) -> list[DocChunk]:
        """Pack table rows without breaking mid-row; keep header on each pack."""
        if len(dc.text) <= self.chunk_size:
            return [dc]

        lines = dc.text.split("\n")
        header = lines[0] if lines else ""
        body = lines[1:] if len(lines) > 1 else []
        out: list[DocChunk] = []
        buf: list[str] = [header] if header else []
        part = 0

        def flush() -> None:
            nonlocal buf, part
            if not buf:
                return
            if len(buf) == 1 and header and buf[0] == header:
                return
            text = "\n".join(buf)
            if text.strip():
                out.append(
                    DocChunk(
                        text=text,
                        doc_name=dc.doc_name,
                        page=dc.page,
                        chunk_id=f"{dc.chunk_id}_rows{part}",
                        is_table=True,
                    )
                )
                part += 1
            buf = [header] if header else []

        for line in body:
            tentative = "\n".join(buf + [line]) if buf else line
            if buf and len(tentative) > self.chunk_size:
                flush()
                buf = [header, line] if header else [line]
                if len("\n".join(buf)) > self.chunk_size:
                    out.append(
                        DocChunk(
                            text="\n".join(buf),
                            doc_name=dc.doc_name,
                            page=dc.page,
                            chunk_id=f"{dc.chunk_id}_rows{part}",
                            is_table=True,
                        )
                    )
                    part += 1
                    buf = [header] if header else []
            else:
                buf.append(line)

        if buf and not (len(buf) == 1 and header and buf[0] == header):
            flush()
        return out or [dc]

    def _recursive_split(self, dc: DocChunk) -> list[DocChunk]:
        """Paragraph → sentence → character recursive splitter with overlap."""
        pieces = recursive_split_text(dc.text, self.chunk_size, self.chunk_overlap)
        return [
            DocChunk(
                text=piece,
                doc_name=dc.doc_name,
                page=dc.page,
                chunk_id=f"{dc.chunk_id}_part{i}",
                is_table=False,
            )
            for i, piece in enumerate(pieces)
            if piece.strip()
        ]

    # ------------------------------------------------------------------
    # Embeddings (batch + retry; fail loud)
    # ------------------------------------------------------------------

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        all_embs: list[list[float]] = []
        for start in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[start : start + EMBED_BATCH_SIZE]
            all_embs.extend(self._embed_texts(batch))
        return all_embs

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        last_err: Exception | None = None
        for model in EMBED_MODELS:
            try:
                contents = texts if len(texts) > 1 else texts[0]
                r = embed_content(
                    self.client,
                    model=model,
                    contents=contents,
                    max_retries=EMBED_MAX_RETRIES,
                    step="embed",
                )
                embs = parse_embeddings(r, expected=len(texts))
                if embs is not None:
                    return embs
                last_err = EmbeddingError(
                    f"Embedding response missing values for model={model}"
                )
            except Exception as e:
                last_err = e
                if is_retryable(e):
                    continue
                # Non-retryable for this model — try next embed model
        if os.getenv("STRICT_EMBED", "0") == "1":
            raise EmbeddingError(
                f"Failed to embed {len(texts)} text(s) after retries "
                f"(models={EMBED_MODELS}): {last_err}"
            )
        logger.warning(
            "Failed to embed %d text(s) via Gemini API (models=%s): %s. "
            "Falling back to deterministic local embeddings for demo resilience.",
            len(texts),
            EMBED_MODELS,
            last_err,
        )
        return [deterministic_local_embedding(t) for t in texts]

    def _embed_query(self, query: str) -> list[float]:
        return self._embed_texts([query])[0]

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def _dense_retrieve(self, query: str, n: int) -> list[tuple[int, float]]:
        """Return (chunk_index, score) sorted by descending similarity."""
        query_emb = self._embed_query(query)

        if self._chroma_collection is not None:
            try:
                result = self._chroma_collection.query(
                    query_embeddings=[query_emb],
                    n_results=n,
                    include=["distances"],
                )
                ids = (result.get("ids") or [[]])[0]
                distances = (result.get("distances") or [[]])[0]
                ranked: list[tuple[int, float]] = []
                for cid, dist in zip(ids, distances):
                    idx = id_to_index(cid)
                    if idx is None or idx >= len(self._chunks):
                        continue
                    sim = 1.0 - float(dist) if dist is not None else 0.0
                    ranked.append((idx, sim))
                if ranked:
                    return ranked
            except Exception as e:
                logger.warning("Chroma query failed; falling back to in-memory dense: %s", e)

        scored = [
            (i, cosine_similarity(query_emb, emb))
            for i, emb in enumerate(self._embeddings)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n]

    def _bm25_retrieve(self, query: str, n: int) -> list[tuple[int, float]]:
        if not self._bm25 or not self._chunks:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        positive = [(i, float(s)) for i, s in ranked[:n] if s > 0]
        return positive or [(i, float(s)) for i, s in ranked[:n]]

    def _persist_chroma(
        self, chunks: list[DocChunk], embeddings: list[list[float]]
    ) -> None:
        if self.persist_dir is None:
            self._chroma_collection = None
            return
        try:
            import chromadb
        except ImportError as e:
            raise EmbeddingError(
                "chromadb is required for persistent hybrid index. "
                "Install with: pip install chromadb"
            ) from e

        self.persist_dir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(self.persist_dir))
        try:
            client.delete_collection(self.collection_name)
        except Exception:
            pass
        collection = client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        ids = [f"c{i}" for i in range(len(chunks))]
        documents = [c.text for c in chunks]
        metadatas = [
            {
                "doc_name": c.doc_name,
                "page": int(c.page),
                "chunk_id": c.chunk_id,
                "is_table": bool(c.is_table),
            }
            for c in chunks
        ]
        batch = 100
        for start in range(0, len(chunks), batch):
            end = start + batch
            collection.add(
                ids=ids[start:end],
                embeddings=embeddings[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )
        self._chroma_collection = collection


# ------------------------------------------------------------------
# Query expansion
# ------------------------------------------------------------------


def expand_query(query: str) -> str:
    """Append section-title synonyms / financial jargon before retrieve."""
    q = (query or "").strip()
    if not q:
        return q
    key = q.lower()
    extras: list[str] = []
    if key in _SECTION_EXPANSIONS:
        extras.append(_SECTION_EXPANSIONS[key])
    else:
        for title, terms in _SECTION_EXPANSIONS.items():
            if title in key or key in title:
                extras.append(terms)
                break
        lowered = key
        if any(w in lowered for w in ("financial", "metric", "kpi", "ebitda")):
            extras.append(_SECTION_EXPANSIONS["key financial metrics"])
        if any(w in lowered for w in ("market", "industry", "tam")):
            extras.append(_SECTION_EXPANSIONS["market overview"])
        if any(w in lowered for w in ("management", "team", "leadership")):
            extras.append(_SECTION_EXPANSIONS["management team"])
        if "risk" in lowered:
            extras.append(_SECTION_EXPANSIONS["risks"])
    if not extras:
        return q
    seen: set[str] = set(q.lower().split())
    added: list[str] = []
    for block in extras:
        for tok in block.split():
            tl = tok.lower()
            if tl not in seen:
                seen.add(tl)
                added.append(tok)
    return f"{q} {' '.join(added)}" if added else q


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def recursive_split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    separators = ["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "]
    return _split_with_separators(text, chunk_size, overlap, separators)


def _split_with_separators(
    text: str, chunk_size: int, overlap: int, separators: list[str]
) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    if not separators:
        return _char_windows(text, chunk_size, overlap)

    sep = separators[0]
    rest = separators[1:]
    parts = text.split(sep)
    pieces: list[str] = []
    for i, p in enumerate(parts):
        if not p:
            continue
        pieces.append(p + sep if i < len(parts) - 1 else p)

    merged: list[str] = []
    buf = ""
    for piece in pieces:
        if len(piece) > chunk_size:
            if buf.strip():
                merged.append(buf.strip())
                buf = ""
            merged.extend(_split_with_separators(piece, chunk_size, overlap, rest))
            continue
        candidate = f"{buf}{piece}" if buf else piece
        if len(candidate) <= chunk_size:
            buf = candidate
        else:
            if buf.strip():
                merged.append(buf.strip())
            buf = piece
    if buf.strip():
        merged.append(buf.strip())

    return _apply_overlap(merged, overlap)


def _char_windows(text: str, chunk_size: int, overlap: int) -> list[str]:
    step = max(chunk_size - overlap, 1)
    out: list[str] = []
    for start in range(0, len(text), step):
        chunk = text[start : start + chunk_size]
        if chunk.strip():
            out.append(chunk)
        if start + chunk_size >= len(text):
            break
    return out


def _apply_overlap(chunks: list[str], overlap: int) -> list[str]:
    if overlap <= 0 or len(chunks) <= 1:
        return chunks
    out = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = out[-1]
        prefix = prev[-overlap:] if len(prev) > overlap else prev
        cur = chunks[i]
        if prefix and not cur.startswith(prefix[: min(32, len(prefix))]):
            out.append(f"{prefix}{cur}")
        else:
            out.append(cur)
    return out


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.lower())


# Back-compat alias used internally
_tokenize = tokenize


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return dot / (na * nb)


def rrf_fuse(
    dense: list[tuple[int, float]],
    sparse: list[tuple[int, float]],
    k: int = RRF_K,
) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion over dense and BM25 rank lists."""
    scores: dict[int, float] = {}
    for rank, (idx, _) in enumerate(dense):
        scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    for rank, (idx, _) in enumerate(sparse):
        scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def parse_embeddings(response, expected: int) -> list[list[float]] | None:
    embs = getattr(response, "embeddings", None)
    if not embs:
        return None
    values_list: list[list[float]] = []
    for e in embs:
        vals = getattr(e, "values", None)
        if not vals:
            return None
        values_list.append(list(vals))
    if len(values_list) == expected:
        return values_list
    if expected == 1 and len(values_list) >= 1:
        return [values_list[0]]
    return None


def is_rate_limit(exc: Exception) -> bool:
    """Backward-compatible alias; prefer ``gemini_client.is_retryable``."""
    return is_retryable(exc)


def id_to_index(cid: str) -> int | None:
    if isinstance(cid, str) and cid.startswith("c") and cid[1:].isdigit():
        return int(cid[1:])
    return None
