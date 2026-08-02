"""Phase 3 — retrieval for large schemas (50+ tables).

The grounding engine's literal name/value matching (grounding_engine.py)
works well up to a few dozen tables — beyond that, its fallback for "no
seed table matched" was `get_most_central_tables()` (pure FK-degree
ranking), which has no idea what the question is actually about; it just
returns whatever tables happen to be the most connected, every time.

This module replaces that blind fallback — when a glossary-enriched Schema
Catalog is available — with a proper (if simple) relevance ranking: a
pure-Python TF-IDF + cosine-similarity retriever over each table's
description/synonyms/column names. No new dependencies (no numpy, no
sentence-transformers, no network call to an embedding API) — this is
intentional: adding a heavyweight embedding stack is real complexity and
real cost for what is, in practice, a bag-of-words matching problem against
short table/column descriptions. If a deployment later wants real semantic
embeddings for a very large (200+ table) schema, this class's `top_k`
interface is the seam to swap the scoring function behind.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional

from loguru import logger

from app.schema_catalog.models import SchemaCatalog
from app.core.config import settings

_TOKEN_RE = re.compile(r"[\w\u0600-\u06FF]+", re.UNICODE)
_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "and", "or", "to", "is", "are",
    "table", "column", "id",  # generic schema noise words that appear in ~every table
}


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


def _table_document(table_name: str, catalog: SchemaCatalog) -> str:
    """Build the bag-of-words 'document' representing one table: its name,
    description, synonyms, and column names/descriptions/synonyms."""
    tprof = catalog.tables[table_name]
    parts = [table_name, tprof.description or "", " ".join(tprof.synonyms)]
    for col in tprof.columns:
        parts.append(col.name)
        parts.append(col.description or "")
        parts.append(" ".join(col.synonyms))
    return " ".join(parts)


class TfidfTableRetriever:
    """Ranks tables by relevance to a free-text question using TF-IDF."""

    def __init__(self, catalog: SchemaCatalog):
        self.catalog = catalog
        self._table_names = list(catalog.tables.keys())
        self._doc_tokens: dict[str, list[str]] = {
            t: _tokenize(_table_document(t, catalog)) for t in self._table_names
        }
        self._df: Counter = Counter()
        for tokens in self._doc_tokens.values():
            for term in set(tokens):
                self._df[term] += 1
        n_docs = max(1, len(self._table_names))
        self._idf: dict[str, float] = {
            term: math.log(1 + n_docs / df) for term, df in self._df.items()
        }
        self._doc_vectors: dict[str, dict[str, float]] = {
            t: self._tfidf_vector(tokens) for t, tokens in self._doc_tokens.items()
        }

    def _tfidf_vector(self, tokens: list[str]) -> dict[str, float]:
        if not tokens:
            return {}
        tf = Counter(tokens)
        max_tf = max(tf.values())
        return {
            term: (0.5 + 0.5 * count / max_tf) * self._idf.get(term, 0.0)
            for term, count in tf.items()
        }

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot = sum(a[t] * b[t] for t in common)
        norm_a = math.sqrt(sum(v * v for v in a.values()))
        norm_b = math.sqrt(sum(v * v for v in b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def top_k(self, question: str, k: int = 12) -> list[str]:
        """Return up to `k` table names ranked by relevance to `question`.

        Falls back to an empty list (letting the caller decide the next
        fallback, e.g. FK-centrality) if the question shares no vocabulary
        at all with any table's document — better than confidently
        returning irrelevant top-ranked noise.
        """
        q_tokens = _tokenize(question)
        if not q_tokens:
            return []
        q_vector = self._tfidf_vector(q_tokens)
        scored = [(t, self._cosine(q_vector, self._doc_vectors.get(t, {}))) for t in self._table_names]
        scored = [(t, s) for t, s in scored if s > 0]
        if not scored:
            return []
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [t for t, _ in scored[:k]]


def retrieve_relevant_tables(
    question: str,
    catalog: Optional[SchemaCatalog],
    k: int = 12,
) -> list[str]:
    """Convenience entry point used by the grounding engine.

    Returns [] (meaning: "no opinion, use the next fallback") when there's
    no usable catalog/glossary yet, or when nothing scored above zero.

    Phase 3: when `settings.schema_retrieval_method == "embedding"` and the
    catalog actually has precomputed table embeddings, tries real semantic
    (cosine-similarity) retrieval first. Any failure there (embeddings not
    built yet for this catalog, embedding API unreachable at query time,
    no vocabulary overlap) transparently falls through to the TF-IDF
    retriever below - this function's return contract never changes.
    """
    if catalog is None or not catalog.glossary_enriched or not catalog.tables:
        return []

    if settings.schema_retrieval_method == "embedding" and catalog.embeddings_built:
        try:
            from app.schema_catalog.embedding_retrieval import EmbeddingTableRetriever
            hits = EmbeddingTableRetriever(catalog).top_k(question, k=k)
            if hits:
                return hits
        except Exception as e:
            logger.debug("Embedding retrieval failed, falling back to TF-IDF: %s", e)

    retriever = TfidfTableRetriever(catalog)
    return retriever.top_k(question, k=k)
