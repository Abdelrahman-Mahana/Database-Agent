"""Phase 3 (real semantic retrieval) — embedding-based table retrieval.

`retrieval.py`'s own docstring names this exact seam: "If a deployment later
wants real semantic embeddings for a very large schema, this class's
`top_k` interface is the seam to swap the scoring function behind." This
module is that swap.

Design choices, and why:

- Table embeddings are precomputed ONCE per catalog (`ensure_table_embeddings`,
  explicit + async, mirrors `glossary.build_glossary`'s "never implicitly
  inside the hot path" rule) and persisted on `TableProfile.embedding` via
  the catalog's existing disk persistence - never recomputed per-question.
- The QUESTION embedding is computed at query time, synchronously, because
  `SchemaGroundingEngine.build_grounded_schema` (the caller) is itself a
  plain sync method called without `await` from `analyst_agent.py`. Rather
  than change that call chain for this one feature, embedding a single
  short question via one blocking HTTP call (typically to a local Ollama
  server) is cheap and simple. Any failure (offline, model not pulled,
  provider misconfigured) returns None and the caller falls back to TF-IDF
  - same fail-open philosophy as the rest of the grounding pipeline.
- No numpy / vector-DB dependency added: cosine similarity over a few dozen
  to a few hundred table vectors is trivial in pure Python, and adding
  FAISS/pgvector for that scale would be complexity with no payoff (they
  start mattering at thousands of vectors, not dozens of tables).
"""
from __future__ import annotations

import math
from typing import Optional

import httpx
from loguru import logger

from app.schema_catalog.models import SchemaCatalog
from app.schema_catalog.retrieval import _table_document  # reuse the exact same document text as TF-IDF
from app.core.config import settings


# --- Embedding clients ----------------------------------------------------

def _embed_via_ollama(texts: list[str]) -> Optional[list[list[float]]]:
    """Blocking call to a local/remote Ollama server's /api/embeddings.

    Ollama's embeddings endpoint takes one prompt per call (no native batch
    endpoint on older versions), so this loops - fine for catalog-build-time
    (dozens of tables, done once) and for single-question embedding.
    """
    base_url = settings.ollama_base_url.rstrip("/")
    vectors: list[list[float]] = []
    try:
        with httpx.Client(timeout=settings.embedding_request_timeout_seconds) as client:
            for text in texts:
                resp = client.post(
                    f"{base_url}/api/embeddings",
                    json={"model": settings.embedding_model, "prompt": text},
                )
                resp.raise_for_status()
                data = resp.json()
                vec = data.get("embedding")
                if not vec:
                    return None
                vectors.append(vec)
        return vectors
    except Exception as e:
        logger.debug("Ollama embedding call failed: %s", e)
        return None


def _embed_via_openai_compatible(texts: list[str]) -> Optional[list[list[float]]]:
    """Blocking call to any OpenAI-style POST /embeddings endpoint."""
    base_url = (settings.embedding_base_url or "").rstrip("/")
    if not base_url:
        logger.debug("EMBEDDING_BASE_URL not set for openai_compatible embedding provider.")
        return None
    headers = {"Authorization": f"Bearer {settings.embedding_api_key}"} if settings.embedding_api_key else {}
    try:
        with httpx.Client(timeout=settings.embedding_request_timeout_seconds) as client:
            resp = client.post(
                f"{base_url}/embeddings",
                headers=headers,
                json={"model": settings.embedding_model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
            items = sorted(data.get("data", []), key=lambda d: d.get("index", 0))
            vectors = [item["embedding"] for item in items]
            return vectors if len(vectors) == len(texts) else None
    except Exception as e:
        logger.debug("OpenAI-compatible embedding call failed: %s", e)
        return None


def _embed_texts(texts: list[str]) -> Optional[list[list[float]]]:
    if not texts:
        return []
    if settings.embedding_provider == "openai_compatible":
        return _embed_via_openai_compatible(texts)
    return _embed_via_ollama(texts)


def embed_question_sync(question: str) -> Optional[list[float]]:
    """Embed a single question. Returns None on any failure (caller falls back)."""
    vectors = _embed_texts([question])
    return vectors[0] if vectors else None


# --- Precomputing table embeddings (explicit, offline step) ---------------

async def ensure_table_embeddings(catalog: SchemaCatalog, force: bool = False) -> SchemaCatalog:
    """Compute + persist an embedding for every table's document, once.

    No-ops (returns immediately) if the catalog already has embeddings from
    the currently configured model, unless `force=True`. Safe to call
    repeatedly (e.g. as part of the same admin action that runs
    `build_glossary`) — running it after the glossary step means the
    embedded "document" includes the human descriptions/synonyms too, which
    materially improves retrieval quality over embedding raw column names alone.
    """
    if catalog.embeddings_built and catalog.embedding_model == settings.embedding_model and not force:
        return catalog

    table_names = list(catalog.tables.keys())
    documents = [_table_document(t, catalog) for t in table_names]
    vectors = _embed_texts(documents)
    if vectors is None:
        logger.warning(
            "Table embedding computation failed (provider=%s, model=%s) — "
            "schema retrieval will keep using TF-IDF/FK-centrality fallback.",
            settings.embedding_provider, settings.embedding_model,
        )
        return catalog

    for tname, vec in zip(table_names, vectors):
        catalog.tables[tname].embedding = vec

    catalog.embeddings_built = True
    catalog.embedding_model = settings.embedding_model
    logger.info("Computed embeddings for %d tables using %s/%s", len(table_names), settings.embedding_provider, settings.embedding_model)
    return catalog


# --- Retrieval --------------------------------------------------------------

def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingTableRetriever:
    """Ranks tables by cosine similarity between the question's embedding and
    each table's precomputed embedding. Mirrors `TfidfTableRetriever`'s
    `top_k(question, k)` interface exactly."""

    def __init__(self, catalog: SchemaCatalog):
        self.catalog = catalog
        self._table_vectors = {
            tname: tprof.embedding for tname, tprof in catalog.tables.items() if tprof.embedding
        }

    def top_k(self, question: str, k: int = 12) -> list[str]:
        if not self._table_vectors:
            return []
        q_vec = embed_question_sync(question)
        if q_vec is None:
            return []
        scored = [(t, _cosine(q_vec, vec)) for t, vec in self._table_vectors.items()]
        scored = [(t, s) for t, s in scored if s > 0]
        if not scored:
            return []
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [t for t, _ in scored[:k]]
