"""Schema Grounding Gate — Prevents ungrounded / hallucinated entities, metrics, and columns.

Validates that all entities, dimensions, metrics, and filter columns extracted by
the LLM or heuristics strictly exist in the database schema or catalog before
allowing them into the QuerySpec or Semantic Contract.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger

from app.models.schema_catalog.models import SchemaCatalog
from app.agent.semantic.models import QuerySpec, FilterCondition


class SchemaGroundingGate:
    """Enforces strict schema grounding on entities, metrics, dimensions, and filters."""

    def __init__(self):
        pass

    def get_known_schema_tables(
        self,
        schema: Optional[Dict[str, Any]],
        catalog: Optional[SchemaCatalog] = None,
    ) -> Dict[str, str]:
        """Returns map of normalized table name -> canonical table name."""
        known: Dict[str, str] = {}
        if catalog and hasattr(catalog, "tables"):
            for t in catalog.tables.keys():
                short = t.split(".")[-1].lower()
                known[short] = t
                known[t.lower()] = t

        if schema:
            for t in schema.keys():
                short = t.split(".")[-1].lower()
                known[short] = t
                known[t.lower()] = t

        return known

    def get_known_schema_columns(
        self,
        schema: Optional[Dict[str, Any]],
        catalog: Optional[SchemaCatalog] = None,
    ) -> Dict[str, Set[str]]:
        """Returns map of canonical table name -> set of lowercase column names."""
        known: Dict[str, Set[str]] = {}
        if catalog and hasattr(catalog, "tables"):
            for t, prof in catalog.tables.items():
                cols = {c.name.lower() for c in prof.columns}
                short = t.split(".")[-1].lower()
                known[short] = cols
                known[t.lower()] = cols

        if schema:
            for t, info in schema.items():
                cols = set()
                if isinstance(info, dict):
                    cols = {c.get("name", "").lower() for c in info.get("columns", []) if isinstance(c, dict)}
                    if not cols:
                        cols = {str(c).lower() for c in info.get("columns", [])}
                elif isinstance(info, list):
                    cols = {c.get("name", "").lower() for c in info if isinstance(c, dict)}
                short = t.split(".")[-1].lower()
                known[short] = cols
                known[t.lower()] = cols

        return known

    def filter_grounded_entities(
        self,
        entities: List[str],
        schema: Optional[Dict[str, Any]],
        catalog: Optional[SchemaCatalog] = None,
    ) -> List[str]:
        """Keep only entities that match real tables in the schema/catalog."""
        if not schema and not catalog:
            return entities

        known_tables = self.get_known_schema_tables(schema, catalog)
        if not known_tables:
            return entities

        grounded: List[str] = []
        for ent in entities:
            if not isinstance(ent, str) or not ent.strip():
                continue
            e_clean = ent.strip()
            e_lower = e_clean.lower()
            short = e_lower.split(".")[-1]

            # 1. Exact or short match
            if short in known_tables:
                canonical = known_tables[short]
                if canonical not in grounded:
                    grounded.append(canonical)
                continue
            elif e_lower in known_tables:
                canonical = known_tables[e_lower]
                if canonical not in grounded:
                    grounded.append(canonical)
                continue

            # 2. Singular / Plural match
            singular = short[:-1] if short.endswith("s") else short
            plural = short + "s" if not short.endswith("s") else short
            if singular in known_tables:
                canonical = known_tables[singular]
                if canonical not in grounded:
                    grounded.append(canonical)
                continue
            elif plural in known_tables:
                canonical = known_tables[plural]
                if canonical not in grounded:
                    grounded.append(canonical)
                continue

            # 3. Check catalog aliases if available
            if catalog and hasattr(catalog, "normalized_aliases"):
                for alias_entry in catalog.normalized_aliases:
                    if hasattr(alias_entry, "alias") and alias_entry.alias.lower() == e_lower:
                        target = getattr(alias_entry, "target_table", None)
                        if target and target in known_tables:
                            canonical = known_tables[target]
                            if canonical not in grounded:
                                grounded.append(canonical)
                            break

            logger.debug("Rejected ungrounded LLM entity: '%s' (not in schema/catalog)", ent)

        return grounded

    def filter_grounded_dimensions(
        self,
        dimensions: List[str],
        candidate_tables: List[str],
        schema: Optional[Dict[str, Any]],
        catalog: Optional[SchemaCatalog] = None,
    ) -> List[str]:
        """Keep only dimensions that exist as valid columns in candidate or schema tables."""
        if not schema and not catalog:
            return dimensions

        known_cols_by_table = self.get_known_schema_columns(schema, catalog)
        all_cols = {c for cols in known_cols_by_table.values() for c in cols}
        if not all_cols:
            return dimensions

        grounded: List[str] = []
        for dim in dimensions:
            if not isinstance(dim, str) or not dim.strip():
                continue
            d_clean = dim.strip()
            d_lower = d_clean.lower()

            # Handle table.column or column
            if "." in d_lower:
                parts = d_lower.split(".")
                tbl_part, col_part = parts[0], parts[-1]
                if tbl_part in known_cols_by_table and col_part in known_cols_by_table[tbl_part]:
                    grounded.append(d_clean)
                    continue
                elif col_part in all_cols:
                    grounded.append(col_part)
                    continue
            else:
                # Check candidate tables first
                found = False
                for ct in candidate_tables:
                    ct_short = ct.split(".")[-1].lower()
                    if ct_short in known_cols_by_table and d_lower in known_cols_by_table[ct_short]:
                        grounded.append(d_clean)
                        found = True
                        break
                if found:
                    continue

                # Check all schema tables
                if d_lower in all_cols:
                    grounded.append(d_clean)
                    continue

                # Check if it's a temporal grain dimension (year, month, date)
                if d_lower in ("year", "month", "quarter", "day", "date", "period", "سنة", "شهر", "يوم", "تاريخ"):
                    grounded.append(d_clean)
                    continue

            logger.debug("Rejected ungrounded LLM dimension: '%s' (not in schema/catalog)", dim)

        return grounded

    def ground_query_spec(
        self,
        spec: QuerySpec,
        schema: Optional[Dict[str, Any]],
        catalog: Optional[SchemaCatalog] = None,
    ) -> QuerySpec:
        """Filter ungrounded entities and dimensions from QuerySpec."""
        if not schema and not catalog:
            return spec

        grounded_entities = self.filter_grounded_entities(spec.entities, schema, catalog)
        grounded_dimensions = self.filter_grounded_dimensions(
            spec.dimensions,
            candidate_tables=grounded_entities or spec.entities,
            schema=schema,
            catalog=catalog,
        )

        # Mutate or copy spec with grounded items
        spec.entities = grounded_entities
        spec.dimensions = grounded_dimensions
        return spec


# Global singleton
schema_grounding_gate = SchemaGroundingGate()
