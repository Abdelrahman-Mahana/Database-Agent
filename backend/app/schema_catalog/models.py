"""Data models for the persisted Schema Catalog (Phase 1 of the rebuild plan).

The catalog is a one-time-per-database-version "profile" of the schema:
structural facts (columns, FKs, indexes, row counts, cardinality) plus an
optional business glossary (human descriptions + synonyms) enriched once by
an LLM and re-used for free on every subsequent question.

This is intentionally a plain dataclass/dict model (no pydantic dependency
here) so it stays cheap to serialize to/from JSON on disk.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class ColumnProfile:
    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    is_foreign_key: bool = False
    samples: list[str] = field(default_factory=list)
    date_range: Optional[str] = None
    distinct_count: Optional[int] = None      # cardinality — None if not computed
    null_fraction: Optional[float] = None
    # --- Business/semantic layer (filled once by glossary enrichment) ---
    description: Optional[str] = None
    synonyms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ColumnProfile":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class TableProfile:
    name: str
    columns: list[ColumnProfile] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[dict[str, Any]] = field(default_factory=list)
    indexes: list[dict[str, Any]] = field(default_factory=list)
    row_count: Optional[int] = None
    fk_degree: int = 0  # number of relationships touching this table (join-graph centrality)
    # --- Business/semantic layer ---
    description: Optional[str] = None
    synonyms: list[str] = field(default_factory=list)
    # --- Phase 3: semantic retrieval ---
    # Precomputed embedding vector of this table's "document" (name +
    # description + synonyms + column names/descriptions/synonyms), filled
    # once by CatalogBuilder.ensure_table_embeddings(). None until that
    # explicit enrichment step has run for this catalog.
    embedding: Optional[list[float]] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TableProfile":
        cols = [ColumnProfile.from_dict(c) for c in d.get("columns", [])]
        kwargs = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "columns"}
        return cls(columns=cols, **kwargs)


@dataclass
class SchemaCatalog:
    """Full persisted profile of one database version (keyed by fingerprint)."""
    fingerprint: str
    dialect: str
    database_name: str
    tables: dict[str, TableProfile] = field(default_factory=dict)
    built_at: float = 0.0
    glossary_enriched: bool = False   # True once the one-time LLM enrichment pass has run
    glossary_version: int = 0         # bump when glossary is regenerated/edited
    # --- Phase 3: semantic retrieval ---
    embeddings_built: bool = False    # True once every table has a precomputed embedding
    embedding_model: Optional[str] = None  # which model produced them (mismatch -> stale)
    # --- Phase 5: learned corrections ---
    # Audit trail of synonyms learned from successful auto-repairs (Phase 5),
    # e.g. {"kind": "column", "table": "Invoice", "column": "Total",
    # "learned_synonym": "grand_total", "learned_at": 1234567.0}. Purely for
    # observability/debugging - the actual effect is the synonym appended to
    # the relevant TableProfile/ColumnProfile.synonyms list.
    learned_corrections: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "dialect": self.dialect,
            "database_name": self.database_name,
            "tables": {name: t.to_dict() for name, t in self.tables.items()},
            "built_at": self.built_at,
            "glossary_enriched": self.glossary_enriched,
            "glossary_version": self.glossary_version,
            "embeddings_built": self.embeddings_built,
            "embedding_model": self.embedding_model,
            "learned_corrections": self.learned_corrections,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SchemaCatalog":
        tables = {name: TableProfile.from_dict(t) for name, t in d.get("tables", {}).items()}
        return cls(
            fingerprint=d["fingerprint"],
            dialect=d.get("dialect", "sql"),
            database_name=d.get("database_name", "Database"),
            tables=tables,
            built_at=d.get("built_at", 0.0),
            glossary_enriched=d.get("glossary_enriched", False),
            glossary_version=d.get("glossary_version", 0),
            embeddings_built=d.get("embeddings_built", False),
            embedding_model=d.get("embedding_model"),
            learned_corrections=d.get("learned_corrections", []),
        )

    # --- Convenience lookups used by the synonym resolver / grounding engine ---

    def find_by_synonym(self, term: str) -> list[tuple[str, Optional[str]]]:
        """Return [(table_name, column_name_or_None), ...] matching a business term."""
        term_l = term.strip().lower()
        if not term_l:
            return []
        hits: list[tuple[str, Optional[str]]] = []
        for tname, tprof in self.tables.items():
            if term_l in [s.lower() for s in tprof.synonyms]:
                hits.append((tname, None))
            for col in tprof.columns:
                if term_l in [s.lower() for s in col.synonyms]:
                    hits.append((tname, col.name))
        return hits
