"""Schema-level learning from execution feedback (Rebuild Plan — Phase 5).

The roadmap's own example for this phase: "if the model was corrected once
that a given column means a certain thing, remember it for next time."
This module is that mechanism, scoped tightly to the one place in the
pipeline where we have unambiguous ground truth for such a correction:
`SQLGenerator.execute_with_repair` succeeding on attempt N>0 means the
identifier named in attempt N-1's error message was wrong, and whatever
replaced it in the now-succeeding SQL was right.

This is deliberately NOT the same thing as `app/services/long_term_memory.py`
(saved queries / user preferences, per-user, opt-in). This is per-DATABASE,
automatic, and shared across every user of that database - it strengthens
the same schema catalog/glossary Phase 1 and Phase 3 already read from, so
the benefit compounds: the very next question (from anyone) that uses the
same wrong term gets it resolved by the glossary/synonym layer before ever
reaching SQL generation.

Safety/scope boundaries:
  - Purely additive (appends a synonym) - never overwrites or deletes an
    existing description/synonym a human glossary pass wrote.
  - Only accepts a correction when the "fixed" identifier can be matched
    with reasonable confidence AND is textually present in the SQL that
    actually succeeded - both conditions must hold, or nothing is learned.
  - Fire-and-forget / best-effort: any failure here is logged and swallowed.
    It must never affect the user-facing answer that already succeeded.
"""
from __future__ import annotations

import difflib
import re
import time
from typing import Optional

from loguru import logger

from app.services.sql_service import SchemaService
from app.models.schema_catalog.catalog_builder import CatalogBuilder
from app.utils.error_parser import extract_missing_identifier

_MATCH_CUTOFF = 0.6


def _identifiers_in_sql(sql: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql))


async def record_repair_correction(schema_service: SchemaService, failed_error: str, corrected_sql: str) -> None:
    """Best-effort: if `failed_error` named a missing table/column and the
    now-succeeding `corrected_sql` clearly used a specific real name instead,
    persist that as a learned synonym on the schema catalog.

    Safe to call unconditionally after every successful repair - it's a
    no-op whenever the error doesn't match a known "unknown identifier"
    shape, or no confident single replacement can be identified.
    """
    try:
        kind, wrong_name = extract_missing_identifier(failed_error)
        if not wrong_name:
            return

        catalog_builder = CatalogBuilder(schema_service)
        catalog = catalog_builder.get_or_build()
        sql_identifiers = _identifiers_in_sql(corrected_sql)

        if kind == "table":
            # Best real-table match to the wrong name, but only accept it if
            # that exact table name is actually used in the SQL that worked.
            candidates = [t for t in catalog.tables.keys() if t in sql_identifiers]
            best = difflib.get_close_matches(wrong_name, candidates, n=1, cutoff=_MATCH_CUTOFF)
            if not best:
                return
            table_name = best[0]
            profile = catalog.tables[table_name]
            if wrong_name.lower() in {s.lower() for s in profile.synonyms} or wrong_name.lower() == table_name.lower():
                return
            profile.synonyms.append(wrong_name)
            catalog.learned_corrections.append({
                "kind": "table", "table": table_name, "learned_synonym": wrong_name, "learned_at": time.time(),
            })
            catalog.glossary_version += 1
            catalog_builder.save(catalog)
            logger.info("Learned: '%s' is a synonym for table '%s' (from a successful auto-repair).", wrong_name, table_name)
            return

        if kind == "column":
            # A column name can exist on more than one table - only accept a
            # match on a table+column pair that's both a close match to the
            # wrong name AND literally present in the SQL that worked, so we
            # don't guess wrong when the same column name is shared.
            best_match: Optional[tuple[str, str]] = None
            best_ratio = 0.0
            for table_name, profile in catalog.tables.items():
                if table_name not in sql_identifiers:
                    continue
                for col in profile.columns:
                    if col.name not in sql_identifiers:
                        continue
                    ratio = difflib.SequenceMatcher(None, wrong_name.lower(), col.name.lower()).ratio()
                    if ratio >= _MATCH_CUTOFF and ratio > best_ratio:
                        best_ratio = ratio
                        best_match = (table_name, col.name)
            if not best_match:
                return
            table_name, column_name = best_match
            column = next(c for c in catalog.tables[table_name].columns if c.name == column_name)
            if wrong_name.lower() in {s.lower() for s in column.synonyms} or wrong_name.lower() == column_name.lower():
                return
            column.synonyms.append(wrong_name)
            catalog.learned_corrections.append({
                "kind": "column", "table": table_name, "column": column_name,
                "learned_synonym": wrong_name, "learned_at": time.time(),
            })
            catalog.glossary_version += 1
            catalog_builder.save(catalog)
            logger.info(
                "Learned: '%s' is a synonym for column '%s.%s' (from a successful auto-repair).",
                wrong_name, table_name, column_name,
            )
    except Exception as e:
        # Learning is pure enrichment on top of an answer that already
        # succeeded - it must never surface as a user-facing failure.
        logger.debug("Schema-learning from repair skipped (non-fatal): %s", e)
