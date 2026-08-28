"""Data models for the persisted Schema Catalog (Normalized Entity System).

Supports both:
1. Normalized relational records for granular indexing, partial retrieval,
   and enterprise scale (10,000+ tables).
2. Fast in-memory TableProfile / ColumnProfile lookups for query generation.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional, List, Dict


# -----------------------------------------------------------------------------
# 1. Normalized Relational Catalog Entities
# -----------------------------------------------------------------------------

@dataclass
class DatabaseConnectionRecord:
    """Connection identity, dialect, and profiling timestamps."""
    connection_id: str
    database_name: str = "Database"
    tenant_id: Optional[str] = None
    dialect: str = "sql"
    fingerprint: str = ""
    version: str = "1.0"
    last_introspected_at: float = 0.0
    last_profiled_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatabaseConnectionRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SchemaObjectRecord:
    """Represents a table, view, or materialized entity."""
    object_id: str                          # e.g. "fingerprint:schema.table" or "table"
    fingerprint: str
    schema_name: str = "public"
    object_name: str = ""
    object_type: str = "table"               # table, view, materialized_view
    row_count_estimate: Optional[int] = None
    description: Optional[str] = None
    status: str = "active"                   # active, deprecated, hidden
    fk_degree: int = 0
    last_profiled_at: Optional[float] = None
    profile_status: str = "unprofiled"       # unprofiled, profiling, profiled, stale

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SchemaObjectRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ColumnRecord:
    """Normalized column metadata, statistics, and semantic attributes."""
    column_id: str                          # e.g. "object_id:column_name"
    object_id: str
    fingerprint: str
    name: str
    normalized_name: str = ""
    data_type: str = "TEXT"
    nullable: bool = True
    primary_key: bool = False
    is_foreign_key: bool = False
    semantic_type: Optional[str] = None      # identifier, currency, timestamp, category, metric, text
    description: Optional[str] = None
    synonyms: list[str] = field(default_factory=list)
    null_fraction: Optional[float] = None
    distinct_estimate: Optional[int] = None
    samples: list[str] = field(default_factory=list)
    date_range: Optional[str] = None

    def __post_init__(self):
        if not self.normalized_name:
            self.normalized_name = re.sub(r'[^a-zA-Z0-9_]+', '_', self.name.lower()).strip('_')

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ColumnRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RelationshipRecord:
    """Foreign key and inferred semantic relationship between objects."""
    relationship_id: str
    fingerprint: str
    source_object: str
    source_column: str
    target_object: str
    target_column: str
    relationship_type: str = "foreign_key"   # foreign_key, inferred_name_match, composite_fk
    confidence: float = 1.0                  # 1.0 for explicit DB FK, 0.7-0.9 for inferred
    source: str = "db_introspection"         # db_introspection, learned_repair, llm_glossary

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RelationshipRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class IndexStatsRecord:
    """Index definition and selectivity metadata."""
    index_id: str
    object_id: str
    fingerprint: str
    index_name: str
    columns: list[str] = field(default_factory=list)
    uniqueness: bool = False
    selectivity_hints: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "IndexStatsRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class AliasTermRecord:
    """Business alias or search synonym mapping to a canonical object or column."""
    alias_id: str
    fingerprint: str
    canonical_id: str                       # references object_id or column_id
    entity_type: str = "table"               # "table" or "column"
    term: str = ""
    language: str = "en"
    source: str = "llm_glossary"            # llm_glossary, user_defined, learned_repair
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AliasTermRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CatalogVersionRecord:
    """Catalog build history, versioning, and profile freshness tracking."""
    version_id: str
    fingerprint: str
    version: int = 1
    change_timestamp: float = field(default_factory=time.time)
    build_status: str = "completed"          # initializing, structural_ready, profiling, completed, failed
    profile_freshness_status: str = "unprofiled"  # fresh, partially_profiled, unprofiled, stale
    tables_count: int = 0
    columns_count: int = 0
    profiled_tables_count: int = 0
    last_introspected_at: float = 0.0
    last_profiled_at: Optional[float] = None
    job_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CatalogVersionRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# -----------------------------------------------------------------------------
# 2. In-Memory Profiles & High-Level SchemaCatalog
# -----------------------------------------------------------------------------

@dataclass
class ColumnProfile:
    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    is_foreign_key: bool = False
    samples: list[str] = field(default_factory=list)
    date_range: Optional[str] = None
    distinct_count: Optional[int] = None
    null_fraction: Optional[float] = None
    description: Optional[str] = None
    synonyms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ColumnProfile":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_column_record(self, fingerprint: str, object_name: str) -> ColumnRecord:
        obj_id = f"{fingerprint}:{object_name}"
        col_id = f"{obj_id}:{self.name}"
        return ColumnRecord(
            column_id=col_id,
            object_id=obj_id,
            fingerprint=fingerprint,
            name=self.name,
            data_type=self.type,
            nullable=self.nullable,
            primary_key=self.primary_key,
            is_foreign_key=self.is_foreign_key,
            samples=self.samples,
            date_range=self.date_range,
            distinct_estimate=self.distinct_count,
            null_fraction=self.null_fraction,
            description=self.description,
            synonyms=self.synonyms,
        )


@dataclass
class TableProfile:
    name: str
    columns: list[ColumnProfile] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[dict[str, Any]] = field(default_factory=list)
    indexes: list[dict[str, Any]] = field(default_factory=list)
    row_count: Optional[int] = None
    fk_degree: int = 0
    profiled: bool = False
    last_profiled_at: Optional[float] = None
    profile_status: str = "unprofiled"  # unprofiled, profiling, profiled, stale
    description: Optional[str] = None
    synonyms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TableProfile":
        cols = [ColumnProfile.from_dict(c) for c in d.get("columns", [])]
        kwargs = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "columns"}
        return cls(columns=cols, **kwargs)

    @property
    def primary_date_column(self) -> Optional[str]:
        """Detect the primary date column for time-series / trend analyses."""
        date_candidates = ("invoice_date", "order_date", "created_at", "date", "invoicedate", "orderdate", "transaction_date")
        col_names = {c.name.lower(): c.name for c in self.columns}
        for cand in date_candidates:
            if cand in col_names:
                return col_names[cand]
        for c in self.columns:
            if "date" in c.name.lower() or "time" in c.name.lower():
                return c.name
        return None

    @property
    def primary_metric_column(self) -> Optional[str]:
        """Detect the primary financial or volume metric column."""
        metric_candidates = ("amount_total", "total", "amount", "total_amount", "price", "unitprice", "line_total", "balance", "revenue")
        col_names = {c.name.lower(): c.name for c in self.columns}
        for cand in metric_candidates:
            if cand in col_names:
                return col_names[cand]
        for c in self.columns:
            if c.type and any(t in c.type.lower() for t in ("numeric", "float", "double", "decimal", "real")):
                if not c.primary_key and not c.is_foreign_key and not c.name.lower().endswith(("_id", "id")):
                    return c.name
        return None

    @property
    def status_column(self) -> Optional[str]:
        """Detect status or state filter column."""
        status_candidates = ("state", "status", "stage", "is_active", "active")
        col_names = {c.name.lower(): c.name for c in self.columns}
        for cand in status_candidates:
            if cand in col_names:
                return col_names[cand]
        return None

    def to_schema_object_record(self, fingerprint: str) -> SchemaObjectRecord:
        obj_id = f"{fingerprint}:{self.name}"
        return SchemaObjectRecord(
            object_id=obj_id,
            fingerprint=fingerprint,
            schema_name="public",
            object_name=self.name,
            object_type="table",
            row_count_estimate=self.row_count,
            description=self.description,
            status="active",
            fk_degree=self.fk_degree,
            last_profiled_at=self.last_profiled_at,
            profile_status="profiled" if (self.profiled or self.row_count is not None) else self.profile_status,
        )


@dataclass
class SchemaCatalog:
    """Full persisted profile of one database version (keyed by fingerprint)."""
    fingerprint: str
    dialect: str
    database_name: str
    tables: dict[str, TableProfile] = field(default_factory=dict)
    built_at: float = 0.0
    glossary_enriched: bool = False
    glossary_version: int = 0
    embeddings_built: bool = False
    embedding_model: Optional[str] = None
    learned_corrections: list[dict] = field(default_factory=list)

    # Optional normalized entity collections (populated on demand)
    connection_info: Optional[DatabaseConnectionRecord] = None
    normalized_relationships: list[RelationshipRecord] = field(default_factory=list)
    normalized_aliases: list[AliasTermRecord] = field(default_factory=list)
    version_info: Optional[CatalogVersionRecord] = None

    _synonym_index: Optional[dict[str, list[tuple[str, Optional[str]]]]] = field(default=None, repr=False, compare=False)

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

    def _ensure_synonym_index(self) -> dict[str, list[tuple[str, Optional[str]]]]:
        """Build an inverted dictionary index of all synonyms once in RAM."""
        if self._synonym_index is not None:
            return self._synonym_index

        index: dict[str, list[tuple[str, Optional[str]]]] = {}
        for tname, tprof in self.tables.items():
            for s in tprof.synonyms:
                s_l = s.strip().lower()
                if s_l:
                    index.setdefault(s_l, []).append((tname, None))
            for col in tprof.columns:
                for s in col.synonyms:
                    s_l = s.strip().lower()
                    if s_l:
                        index.setdefault(s_l, []).append((tname, col.name))

        self._synonym_index = index
        return index

    def find_by_synonym(self, term: str) -> list[tuple[str, Optional[str]]]:
        """Return [(table_name, column_name_or_None), ...] matching a business term in O(1)."""
        term_l = term.strip().lower()
        if not term_l:
            return []
        index = self._ensure_synonym_index()
        return index.get(term_l, [])

    def get_freshness_report(self, max_profile_age_seconds: float = 86400.0) -> dict[str, Any]:
        """Generate a structured profile freshness and coverage summary."""
        now = time.time()
        total_tables = len(self.tables)
        total_cols = sum(len(t.columns) for t in self.tables.values())
        profiled_tables = 0
        stale_tables = 0
        unprofiled_tables = 0
        latest_profile_ts: Optional[float] = None

        for t in self.tables.values():
            is_prof = t.profiled or t.row_count is not None or t.profile_status == "profiled"
            if is_prof:
                profiled_tables += 1
                ts = t.last_profiled_at or self.built_at
                if latest_profile_ts is None or (ts and ts > latest_profile_ts):
                    latest_profile_ts = ts
                if ts and (now - ts) > max_profile_age_seconds:
                    stale_tables += 1
            else:
                unprofiled_tables += 1

        if total_tables == 0:
            status = "empty"
        elif profiled_tables == total_tables and stale_tables == 0:
            status = "fresh"
        elif profiled_tables > 0 and stale_tables > 0:
            status = "stale"
        elif profiled_tables > 0:
            status = "partially_profiled"
        else:
            status = "unprofiled"

        return {
            "status": status,
            "total_tables": total_tables,
            "total_columns": total_cols,
            "profiled_tables": profiled_tables,
            "unprofiled_tables": unprofiled_tables,
            "stale_tables": stale_tables,
            "last_introspected_at": self.built_at,
            "last_profiled_at": latest_profile_ts,
            "glossary_version": self.glossary_version,
        }

    def is_stale(self, ttl_seconds: float = 86400.0) -> bool:
        """Check if catalog metadata or profiling is older than the TTL."""
        if not self.built_at:
            return True
        return (time.time() - self.built_at) > ttl_seconds

    def bump_version(self, build_status: str = "completed", job_id: Optional[str] = None) -> CatalogVersionRecord:
        """Explicitly increment catalog version and generate new version record."""
        self.glossary_version += 1
        freshness = self.get_freshness_report()
        ver_rec = CatalogVersionRecord(
            version_id=f"ver_{self.fingerprint[:12]}_{self.glossary_version}",
            fingerprint=self.fingerprint,
            version=self.glossary_version,
            change_timestamp=time.time(),
            build_status=build_status,
            profile_freshness_status=freshness["status"],
            tables_count=freshness["total_tables"],
            columns_count=freshness["total_columns"],
            profiled_tables_count=freshness["profiled_tables"],
            last_introspected_at=self.built_at,
            last_profiled_at=freshness["last_profiled_at"],
            job_id=job_id,
        )
        self.version_info = ver_rec
        return ver_rec

    def to_normalized_records(self) -> dict[str, list[Any]]:
        """Deconstruct SchemaCatalog into normalized relational entity records."""
        fp = self.fingerprint
        freshness = self.get_freshness_report()
        connection = DatabaseConnectionRecord(
            connection_id=f"conn_{fp[:12]}",
            database_name=self.database_name,
            tenant_id=None,
            dialect=self.dialect,
            fingerprint=fp,
            version=str(self.glossary_version),
            last_introspected_at=self.built_at,
            last_profiled_at=freshness["last_profiled_at"],
        )

        objects: list[SchemaObjectRecord] = []
        columns: list[ColumnRecord] = []
        relationships: list[RelationshipRecord] = []
        indexes: list[IndexStatsRecord] = []
        aliases: list[AliasTermRecord] = []

        for tname, tprof in self.tables.items():
            obj = tprof.to_schema_object_record(fp)
            objects.append(obj)

            # Columns
            for col in tprof.columns:
                col_rec = col.to_column_record(fp, tname)
                columns.append(col_rec)
                for syn in col.synonyms:
                    aliases.append(AliasTermRecord(
                        alias_id=f"alias_{fp[:8]}_{col_rec.column_id}_{syn}",
                        fingerprint=fp,
                        canonical_id=col_rec.column_id,
                        entity_type="column",
                        term=syn,
                    ))

            # Table aliases
            for syn in tprof.synonyms:
                aliases.append(AliasTermRecord(
                    alias_id=f"alias_{fp[:8]}_{obj.object_id}_{syn}",
                    fingerprint=fp,
                    canonical_id=obj.object_id,
                    entity_type="table",
                    term=syn,
                ))

            # Relationships / FKs
            for idx, fk in enumerate(tprof.foreign_keys):
                constrained_cols = fk.get("constrained_columns", [])
                referred_table = fk.get("referred_table", "")
                referred_cols = fk.get("referred_columns", [])
                src_col = constrained_cols[0] if constrained_cols else ""
                tgt_col = referred_cols[0] if referred_cols else ""
                rel_id = f"rel_{fp[:8]}_{tname}_{src_col}_{referred_table}_{tgt_col}"
                relationships.append(RelationshipRecord(
                    relationship_id=rel_id,
                    fingerprint=fp,
                    source_object=tname,
                    source_column=src_col,
                    target_object=referred_table,
                    target_column=tgt_col,
                    relationship_type="foreign_key",
                    confidence=1.0,
                    source="db_introspection",
                ))

            # Indexes
            for idx, ix in enumerate(tprof.indexes):
                ix_name = ix.get("name") or f"idx_{tname}_{idx}"
                indexes.append(IndexStatsRecord(
                    index_id=f"ix_{fp[:8]}_{tname}_{ix_name}",
                    object_id=obj.object_id,
                    fingerprint=fp,
                    index_name=ix_name,
                    columns=ix.get("column_names", []),
                    uniqueness=ix.get("unique", False),
                ))

        version_rec = self.version_info or CatalogVersionRecord(
            version_id=f"ver_{fp[:12]}_{self.glossary_version}",
            fingerprint=fp,
            version=self.glossary_version,
            change_timestamp=self.built_at or time.time(),
            build_status="completed",
            profile_freshness_status=freshness["status"],
            tables_count=freshness["total_tables"],
            columns_count=freshness["total_columns"],
            profiled_tables_count=freshness["profiled_tables"],
            last_introspected_at=self.built_at,
            last_profiled_at=freshness["last_profiled_at"],
        )

        return {
            "connection": [connection],
            "objects": objects,
            "columns": columns,
            "relationships": relationships,
            "indexes": indexes,
            "aliases": aliases,
            "version": [version_rec],
        }

    @classmethod
    def from_normalized_records(
        cls,
        connection: DatabaseConnectionRecord,
        objects: list[SchemaObjectRecord],
        columns: list[ColumnRecord],
        relationships: list[RelationshipRecord],
        indexes: list[IndexStatsRecord],
        aliases: list[AliasTermRecord],
        version: Optional[CatalogVersionRecord] = None,
        built_at: float = 0.0,
    ) -> "SchemaCatalog":
        """Reconstruct SchemaCatalog from normalized records."""
        # Group columns by object_id
        cols_by_obj: dict[str, list[ColumnProfile]] = {}
        for c in columns:
            col_prof = ColumnProfile(
                name=c.name,
                type=c.data_type,
                nullable=c.nullable,
                primary_key=c.primary_key,
                is_foreign_key=c.is_foreign_key,
                samples=c.samples,
                date_range=c.date_range,
                distinct_count=c.distinct_estimate,
                null_fraction=c.null_fraction,
                description=c.description,
                synonyms=c.synonyms,
            )
            cols_by_obj.setdefault(c.object_id, []).append(col_prof)

        # Group foreign keys by source_object
        fks_by_table: dict[str, list[dict[str, Any]]] = {}
        for r in relationships:
            fks_by_table.setdefault(r.source_object, []).append({
                "constrained_columns": [r.source_column] if r.source_column else [],
                "referred_table": r.target_object,
                "referred_columns": [r.target_column] if r.target_column else [],
            })

        # Group indexes by object_id
        idxs_by_obj: dict[str, list[dict[str, Any]]] = {}
        for ix in indexes:
            idxs_by_obj.setdefault(ix.object_id, []).append({
                "name": ix.index_name,
                "column_names": ix.columns,
                "unique": ix.uniqueness,
            })

        # Build table profiles
        tables: dict[str, TableProfile] = {}
        for obj in objects:
            t_cols = cols_by_obj.get(obj.object_id, [])
            pk_cols = [c.name for c in t_cols if c.primary_key]
            t_fks = fks_by_table.get(obj.object_name, [])
            t_idxs = idxs_by_obj.get(obj.object_id, [])
            is_prof = (obj.row_count_estimate is not None) or (obj.profile_status == "profiled")

            tprof = TableProfile(
                name=obj.object_name,
                columns=t_cols,
                primary_key=pk_cols,
                foreign_keys=t_fks,
                indexes=t_idxs,
                row_count=obj.row_count_estimate,
                fk_degree=obj.fk_degree,
                profiled=is_prof,
                last_profiled_at=obj.last_profiled_at,
                profile_status=obj.profile_status or ("profiled" if is_prof else "unprofiled"),
                description=obj.description,
                synonyms=[],
            )
            tables[obj.object_name] = tprof

        # Attach aliases
        for a in aliases:
            if a.entity_type == "table":
                # Find table
                for t in tables.values():
                    if a.canonical_id.endswith(f":{t.name}") or a.canonical_id == t.name:
                        if a.term not in t.synonyms:
                            t.synonyms.append(a.term)
            elif a.entity_type == "column":
                for t in tables.values():
                    for col in t.columns:
                        if a.canonical_id.endswith(f":{t.name}:{col.name}") or a.canonical_id.endswith(f":{col.name}"):
                            if a.term not in col.synonyms:
                                col.synonyms.append(a.term)

        v_num = version.version if version else 0
        return cls(
            fingerprint=connection.fingerprint,
            dialect=connection.dialect,
            database_name=connection.database_name or connection.connection_id,
            tables=tables,
            built_at=built_at or connection.last_introspected_at,
            glossary_enriched=v_num > 0,
            glossary_version=v_num,
            connection_info=connection,
            normalized_relationships=relationships,
            normalized_aliases=aliases,
            version_info=version,
        )
