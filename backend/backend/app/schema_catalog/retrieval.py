"""Multi-Signal Hybrid Retrieval Engine for Schema Catalog.

Combines:
1. Lexical Index (BM25 / TF-IDF token scoring)
2. Vector ANN Index (Dense embedding semantic similarity via FAISS)
3. Alias Index (Fast business glossary & synonym exact/n-gram lookup)

Provides hierarchical candidate retrieval:
- Stage 1: Table Candidate Retrieval
- Stage 2: Column Candidate Retrieval & Role Classification
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from loguru import logger

from app.schema_catalog.models import SchemaCatalog
from app.config.settings import settings

_TOKEN_RE = re.compile(r"[a-zA-Z0-9\u0600-\u06FF]+", re.UNICODE)
_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "and", "or", "to", "is", "are",
    "table", "column", "id", "data", "database", "find", "get", "show", "list",
}


def _tokenize(text: str) -> list[str]:
    clean_text = text.replace("_", " ").replace("-", " ").lower()
    return [t for t in _TOKEN_RE.findall(clean_text) if t not in _STOPWORDS and len(t) > 1]


def _table_document(table_name: str, catalog: SchemaCatalog) -> str:
    """Build the bag-of-words 'document' representing one table: its name,
    description, synonyms, and column names/descriptions/synonyms."""
    tprof = catalog.tables.get(table_name)
    if not tprof:
        return table_name
    parts = [table_name, tprof.description or "", " ".join(tprof.synonyms)]
    for col in tprof.columns:
        parts.append(col.name)
        parts.append(col.description or "")
        parts.append(" ".join(col.synonyms))
    return " ".join(parts)


@dataclass
class CandidateTable:
    """Represents a retrieved table candidate with multi-signal score breakdown."""
    table_name: str
    score: float
    lexical_score: float = 0.0
    vector_score: float = 0.0
    alias_score: float = 0.0
    match_sources: list[str] = field(default_factory=list)


@dataclass
class CandidateColumn:
    """Represents a retrieved column candidate with semantic role classification."""
    table_name: str
    column_name: str
    score: float
    data_type: str = ""
    is_pk: bool = False
    is_fk: bool = False
    role: str = "generic"  # "metric", "dimension", "join_key", "filter"
    match_sources: list[str] = field(default_factory=list)


class AliasIndex:
    """Fast in-memory inverted index for business glossary terms, synonyms, and aliases."""

    def __init__(self, catalog: SchemaCatalog):
        self.catalog = catalog
        self._table_aliases: dict[str, dict[str, float]] = {}
        self._col_aliases: dict[str, dict[tuple[str, str], float]] = {}
        self._build_index()

    def _build_index(self) -> None:
        for tname, tprof in self.catalog.tables.items():
            t_lower = tname.lower()
            t_norm = t_lower.replace("_", " ")
            self._add_table_alias(t_norm, tname, 1.0)
            if t_lower != t_norm:
                self._add_table_alias(t_lower, tname, 1.0)

            # PostgreSQL catalog keys may be schema-qualified (for example
            # ``public.patient_model``), while users normally name the table
            # as ``patient_model``. Index both forms while retaining the
            # canonical qualified key in retrieval results. If a bare name
            # exists in several schemas, the ambiguity gate receives all of
            # those evidence-backed alternatives.
            bare_name = t_lower.rsplit(".", 1)[-1]
            bare_norm = bare_name.replace("_", " ")
            self._add_table_alias(bare_norm, tname, 1.0)
            if bare_name != bare_norm:
                self._add_table_alias(bare_name, tname, 1.0)
            qualified_norm = t_lower.replace(".", " ").replace("_", " ")
            self._add_table_alias(qualified_norm, tname, 1.0)

            for syn in tprof.synonyms:
                s_norm = syn.lower().replace("_", " ")
                self._add_table_alias(s_norm, tname, 0.95)

            for col in tprof.columns:
                c_lower = col.name.lower()
                c_norm = c_lower.replace("_", " ")
                self._add_col_alias(c_norm, tname, col.name, 1.0)
                if c_lower != c_norm:
                    self._add_col_alias(c_lower, tname, col.name, 1.0)

                for syn in col.synonyms:
                    cs_norm = syn.lower().replace("_", " ")
                    self._add_col_alias(cs_norm, tname, col.name, 0.95)

        alias_list = getattr(self.catalog, "normalized_aliases", None) or getattr(self.catalog, "aliases", None)
        if alias_list:
            for alias_rec in alias_list:
                term_norm = alias_rec.term.lower().replace("_", " ")
                conf = getattr(alias_rec, "confidence", 0.9) or 0.9
                if alias_rec.entity_type == "table":
                    self._add_table_alias(term_norm, alias_rec.canonical_id, conf)
                elif alias_rec.entity_type == "column":
                    parts = alias_rec.canonical_id.split(".")
                    if len(parts) == 2:
                        self._add_col_alias(term_norm, parts[0], parts[1], conf)

    def _add_table_alias(self, term: str, table_name: str, confidence: float) -> None:
        if not term:
            return
        entry = self._table_aliases.setdefault(term, {})
        entry[table_name] = max(entry.get(table_name, 0.0), confidence)

    def _add_col_alias(self, term: str, table_name: str, col_name: str, confidence: float) -> None:
        if not term:
            return
        entry = self._col_aliases.setdefault(term, {})
        key = (table_name, col_name)
        entry[key] = max(entry.get(key, 0.0), confidence)

    def lookup_tables(self, question: str) -> list[tuple[str, float]]:
        """Look up matching tables from question n-grams and tokens in O(W) time."""
        q_clean = question.replace("_", " ").replace("-", " ").lower()
        q_tokens = _tokenize(q_clean)
        if not q_tokens:
            return []

        matches: dict[str, float] = {}

        # Generate 1-gram, 2-gram, 3-gram phrases from question tokens
        n_tokens = len(q_tokens)
        ngrams: list[str] = []
        for i in range(n_tokens):
            ngrams.append(q_tokens[i])
            if i + 1 < n_tokens:
                ngrams.append(f"{q_tokens[i]} {q_tokens[i+1]}")
            if i + 2 < n_tokens:
                ngrams.append(f"{q_tokens[i]} {q_tokens[i+1]} {q_tokens[i+2]}")

        # Add Arabic conjunction/article variations (e.g., "و", "ال", "وال")
        for ng in list(ngrams):
            if ng.startswith("و") and len(ng) > 3:
                ngrams.append(ng[1:])
            if ng.startswith("ال") and len(ng) > 4:
                ngrams.append(ng[2:])
            if ng.startswith("وال") and len(ng) > 5:
                ngrams.append(ng[3:])

        for ng in ngrams:
            if ng in self._table_aliases:
                for tname, conf in self._table_aliases[ng].items():
                    matches[tname] = max(matches.get(tname, 0.0), conf)

        return sorted(matches.items(), key=lambda x: x[1], reverse=True)

    def lookup_columns(self, question: str, table_names: Optional[list[str]] = None) -> list[tuple[str, str, float]]:
        """Look up matching columns within candidate tables in O(W) time."""
        q_clean = question.replace("_", " ").replace("-", " ").lower()
        q_tokens = _tokenize(q_clean)
        if not q_tokens:
            return []

        matches: dict[tuple[str, str], float] = {}
        allowed_tables = set(table_names) if table_names else None

        n_tokens = len(q_tokens)
        ngrams: list[str] = []
        for i in range(n_tokens):
            ngrams.append(q_tokens[i])
            if i + 1 < n_tokens:
                ngrams.append(f"{q_tokens[i]} {q_tokens[i+1]}")
            if i + 2 < n_tokens:
                ngrams.append(f"{q_tokens[i]} {q_tokens[i+1]} {q_tokens[i+2]}")

        for ng in list(ngrams):
            if ng.startswith("و") and len(ng) > 3:
                ngrams.append(ng[1:])
            if ng.startswith("ال") and len(ng) > 4:
                ngrams.append(ng[2:])
            if ng.startswith("وال") and len(ng) > 5:
                ngrams.append(ng[3:])

        for ng in ngrams:
            if ng in self._col_aliases:
                for (tname, cname), conf in self._col_aliases[ng].items():
                    if allowed_tables is None or tname in allowed_tables:
                        matches[(tname, cname)] = max(matches.get((tname, cname), 0.0), conf)

        results = [(t, c, score) for (t, c), score in matches.items()]
        return sorted(results, key=lambda x: x[2], reverse=True)


class TfidfTableRetriever:
    """Ranks tables by relevance to a free-text question using inverted index TF-IDF."""

    def __init__(self, catalog: SchemaCatalog):
        self.catalog = catalog
        self._table_names = list(catalog.tables.keys())
        self._doc_tokens: dict[str, list[str]] = {}
        self._df: Counter = Counter()

        for tname in self._table_names:
            tokens = _tokenize(_table_document(tname, catalog))
            self._doc_tokens[tname] = tokens
            for term in set(tokens):
                self._df[term] += 1

        n_docs = max(1, len(self._table_names))
        self._idf: dict[str, float] = {
            term: math.log(1 + n_docs / df) for term, df in self._df.items()
        }

        # Build Inverted Index: term -> list[(tname, tfidf_weight)] & precompute doc norms
        self._inverted_index: dict[str, list[tuple[str, float]]] = {}
        self._doc_norms: dict[str, float] = {}

        for tname, tokens in self._doc_tokens.items():
            if not tokens:
                self._doc_norms[tname] = 0.0
                continue
            tf = Counter(tokens)
            max_tf = max(tf.values())
            norm_sq = 0.0
            for term, count in tf.items():
                w = (0.5 + 0.5 * count / max_tf) * self._idf.get(term, 0.0)
                norm_sq += w * w
                self._inverted_index.setdefault(term, []).append((tname, w))
            self._doc_norms[tname] = math.sqrt(norm_sq)

    def _tfidf_vector(self, tokens: list[str]) -> dict[str, float]:
        if not tokens:
            return {}
        tf = Counter(tokens)
        max_tf = max(tf.values())
        return {
            term: (0.5 + 0.5 * count / max_tf) * self._idf.get(term, 0.0)
            for term, count in tf.items()
        }

    def top_k_with_scores(self, question: str, k: int = 12) -> list[tuple[str, float]]:
        """Return up to `k` (table_name, score) tuples using inverted index scoring in O(|Q|) time."""
        q_tokens = _tokenize(question)
        if not q_tokens:
            return []
        q_vector = self._tfidf_vector(q_tokens)
        if not q_vector:
            return []

        # Accumulate dot product only for tables containing query terms (O(|Q| * avg_df))
        accum: dict[str, float] = {}
        for term, q_w in q_vector.items():
            postings = self._inverted_index.get(term)
            if postings:
                for tname, doc_w in postings:
                    accum[tname] = accum.get(tname, 0.0) + (q_w * doc_w)

        if not accum:
            return []

        q_norm = math.sqrt(sum(w * w for w in q_vector.values()))
        if q_norm == 0:
            return []

        scored = [
            (t, dot / (q_norm * self._doc_norms[t]))
            for t, dot in accum.items()
            if self._doc_norms.get(t, 0) > 0
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]

    def top_k(self, question: str, k: int = 12) -> list[str]:
        """Return up to `k` table names ranked by relevance to `question`."""
        scored = self.top_k_with_scores(question, k=k)
        return [t for t, _ in scored]


class HybridCandidateRetriever:
    """
    Multi-Signal Hybrid Candidate Retrieval:
    - Lexical Index (TF-IDF / BM25)
    - Vector ANN Index (Dense semantic embeddings via FAISS)
    - Alias Index (Glossary & Synonyms)
    Combines signals via reciprocal rank fusion and weighted scoring.
    """

    def __init__(
        self,
        catalog: SchemaCatalog,
        tfidf_retriever: Optional[TfidfTableRetriever] = None,
        embedding_retriever: Optional[Any] = None,
        alias_index: Optional[AliasIndex] = None,
    ):
        self.catalog = catalog
        self.tfidf_retriever = tfidf_retriever or TfidfTableRetriever(catalog)
        self.alias_index = alias_index or AliasIndex(catalog)
        self.embedding_retriever = embedding_retriever

    def retrieve_candidate_tables(
        self,
        question: str,
        k: int = 5,
        vector_candidates: Optional[list[str]] = None,
    ) -> list[CandidateTable]:
        """Synchronous multi-signal table candidate retrieval."""
        alias_matches = self.alias_index.lookup_tables(question)
        lexical_matches = self.tfidf_retriever.top_k_with_scores(question, k=k * 2)

        vector_hits = vector_candidates or []
        if not vector_hits and self.catalog.embeddings_built:
            try:
                from app.schema_catalog.embedding_retrieval import EmbeddingTableRetriever
                emb_ret = self.embedding_retriever or EmbeddingTableRetriever(self.catalog)
                vector_hits = emb_ret.top_k(question, k=k * 2)
            except Exception as e:
                logger.debug("Sync vector ANN retrieval skipped: %s", e)

        return self._fuse_signals(question, alias_matches, lexical_matches, vector_hits, k=k)

    async def retrieve_candidate_tables_async(
        self,
        question: str,
        k: int = 5,
    ) -> list[CandidateTable]:
        """Asynchronous multi-signal table candidate retrieval."""
        alias_matches = self.alias_index.lookup_tables(question)
        lexical_matches = self.tfidf_retriever.top_k_with_scores(question, k=k * 2)

        vector_hits = []
        if self.catalog.embeddings_built:
            try:
                from app.schema_catalog.embedding_retrieval import EmbeddingTableRetriever
                emb_ret = self.embedding_retriever or EmbeddingTableRetriever(self.catalog)
                vector_hits = await emb_ret.top_k_async(question, k=k * 2)
            except Exception as e:
                logger.debug("Async vector ANN retrieval skipped: %s", e)

        return self._fuse_signals(question, alias_matches, lexical_matches, vector_hits, k=k)

    def _fuse_signals(
        self,
        question: str,
        alias_matches: list[tuple[str, float]],
        lexical_matches: list[tuple[str, float]],
        vector_hits: list[str],
        k: int = 5,
    ) -> list[CandidateTable]:
        """Fuse alias, lexical, and vector ANN signals."""
        table_map: dict[str, CandidateTable] = {}

        # 1. Alias Index Matches (High Precision)
        for tname, score in alias_matches:
            if tname not in self.catalog.tables:
                continue
            cand = table_map.setdefault(tname, CandidateTable(table_name=tname, score=0.0))
            cand.alias_score = score
            cand.score += score * 1.5
            cand.match_sources.append("alias")

        # 2. Lexical Index Matches
        for tname, score in lexical_matches:
            if tname not in self.catalog.tables:
                continue
            cand = table_map.setdefault(tname, CandidateTable(table_name=tname, score=0.0))
            cand.lexical_score = score
            cand.score += score * 1.0
            cand.match_sources.append("lexical")

        # 3. Vector ANN Hits (Rank-based scoring)
        for rank, tname in enumerate(vector_hits):
            if tname not in self.catalog.tables:
                continue
            cand = table_map.setdefault(tname, CandidateTable(table_name=tname, score=0.0))
            vec_score = 1.0 / (1.0 + rank * 0.2)
            cand.vector_score = vec_score
            cand.score += vec_score * 0.8
            cand.match_sources.append("vector_ann")

        candidates = list(table_map.values())
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:k]

    def retrieve_candidate_columns(
        self,
        question: str,
        candidate_tables: list[str],
        k_per_table: int = 10,
    ) -> list[CandidateColumn]:
        """Stage 2: Retrieve and rank candidate columns within the candidate tables."""
        q_tokens = set(_tokenize(question))
        q_lower = question.lower()
        alias_col_matches = self.alias_index.lookup_columns(question, table_names=candidate_tables)
        alias_col_map = {(t, c): s for t, c, s in alias_col_matches}

        NUMERIC_TYPES = {"INT", "INTEGER", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL", "REAL", "BIGINT", "SMALLINT", "MONEY"}
        col_results: list[CandidateColumn] = []

        for tname in candidate_tables:
            tprof = self.catalog.tables.get(tname)
            if not tprof:
                continue

            for col in tprof.columns:
                score = 0.0
                sources = []
                c_clean = col.name.lower().replace("_", " ")
                c_tokens = set(_tokenize(col.name))

                # Exact or token match
                if col.name.lower() in q_lower or c_clean in q_lower:
                    score += 1.0
                    sources.append("exact_column")
                elif c_tokens & q_tokens:
                    overlap_ratio = len(c_tokens & q_tokens) / max(1, len(c_tokens))
                    score += 0.7 * overlap_ratio
                    sources.append("token_column")

                # Alias / synonym match
                if (tname, col.name) in alias_col_map:
                    a_score = alias_col_map[(tname, col.name)]
                    score += a_score * 1.2
                    sources.append("alias_column")

                # Role classification
                c_type_upper = (col.type or "").upper()
                is_num = any(nt in c_type_upper for nt in NUMERIC_TYPES)
                role = "generic"
                if col.primary_key:
                    role = "join_key"
                    score += 0.3  # slight boost for primary keys
                elif col.is_foreign_key:
                    role = "join_key"
                    score += 0.3
                elif is_num and not col.name.lower().endswith("id"):
                    role = "metric"
                elif not is_num:
                    role = "dimension"

                if score > 0 or col.primary_key or col.is_foreign_key:
                    col_results.append(
                        CandidateColumn(
                            table_name=tname,
                            column_name=col.name,
                            score=score,
                            data_type=col.type,
                            is_pk=col.primary_key,
                            is_fk=col.is_foreign_key,
                            role=role,
                            match_sources=sources,
                        )
                    )

        col_results.sort(key=lambda c: (c.score, c.is_pk or c.is_fk), reverse=True)
        return col_results


def retrieve_relevant_tables(
    question: str,
    catalog: Optional[SchemaCatalog],
    k: int = 12,
    cached_retriever: Optional[TfidfTableRetriever] = None,
    cached_embedding_retriever: Optional[Any] = None,
    cached_alias_index: Optional[AliasIndex] = None,
) -> list[str]:
    """Hybrid Retrieval (Lexical + Vector ANN + Alias Index)."""
    if catalog is None or not catalog.tables:
        return []

    tfidf = cached_retriever or getattr(catalog, "_cached_tfidf_retriever", None)
    if tfidf is None:
        tfidf = TfidfTableRetriever(catalog)
        try:
            catalog._cached_tfidf_retriever = tfidf
        except Exception:
            pass

    alias_idx = cached_alias_index or getattr(catalog, "_cached_alias_index", None)
    if alias_idx is None:
        alias_idx = AliasIndex(catalog)
        try:
            catalog._cached_alias_index = alias_idx
        except Exception:
            pass

    retriever = HybridCandidateRetriever(
        catalog,
        tfidf_retriever=tfidf,
        embedding_retriever=cached_embedding_retriever,
        alias_index=alias_idx,
    )
    candidates = retriever.retrieve_candidate_tables(question, k=k)
    return [c.table_name for c in candidates]


async def retrieve_relevant_tables_async(
    question: str,
    catalog: Optional[SchemaCatalog],
    k: int = 12,
    cached_retriever: Optional[TfidfTableRetriever] = None,
    cached_embedding_retriever: Optional[Any] = None,
    cached_alias_index: Optional[AliasIndex] = None,
) -> list[str]:
    """Async Hybrid Retrieval (Lexical + Vector ANN + Alias Index)."""
    if catalog is None or not catalog.tables:
        return []

    tfidf = cached_retriever or getattr(catalog, "_cached_tfidf_retriever", None)
    if tfidf is None:
        tfidf = TfidfTableRetriever(catalog)
        try:
            catalog._cached_tfidf_retriever = tfidf
        except Exception:
            pass

    alias_idx = cached_alias_index or getattr(catalog, "_cached_alias_index", None)
    if alias_idx is None:
        alias_idx = AliasIndex(catalog)
        try:
            catalog._cached_alias_index = alias_idx
        except Exception:
            pass

    retriever = HybridCandidateRetriever(
        catalog,
        tfidf_retriever=tfidf,
        embedding_retriever=cached_embedding_retriever,
        alias_index=alias_idx,
    )
    candidates = await retriever.retrieve_candidate_tables_async(question, k=k)
    return [c.table_name for c in candidates]
