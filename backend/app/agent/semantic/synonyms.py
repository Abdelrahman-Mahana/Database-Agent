"""Business-glossary synonym resolution (Phase 2 of the rebuild plan).

`SemanticQueryParser.parse()` already extracts entities/metrics/dimensions
by literally matching table/column *names* against the question text. That
misses business language: a user asking about "الإيراد" or "revenue" gets
nothing if the actual column is `Total` or `UnitPrice * Quantity`.

This module closes that gap using the one-time glossary built in
`app/schema_catalog/glossary.py` (see CatalogBuilder.merge_glossary) — pure
dict lookups, zero extra LLM calls per question.
"""
from __future__ import annotations

import re
from typing import Optional

from app.models.schema_catalog.models import SchemaCatalog
from app.agent.semantic.models import QueryUnderstanding

# Split on whitespace and exclude common Arabic/English punctuation to get candidate
# phrases (unigrams + bigrams) worth checking against the glossary.
_TOKEN_RE = re.compile(r"[\w\u0621-\u064A\u0660-\u0669]+", re.UNICODE)


def _candidate_phrases(question: str) -> list[str]:
    tokens = _TOKEN_RE.findall(question.lower())
    phrases = list(tokens)
    phrases += [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]
    return phrases


def resolve_synonyms(question: str, catalog: Optional[SchemaCatalog], understanding: QueryUnderstanding) -> QueryUnderstanding:
    """Enrich a QueryUnderstanding in-place with glossary-resolved entities/metrics.

    No-op (returns `understanding` unchanged) if no enriched catalog is
    available yet — callers should always be safe to pass `catalog=None`.
    """
    if catalog is None or not catalog.glossary_enriched:
        return understanding

    for phrase in _candidate_phrases(question):
        for table_name, column_name in catalog.find_by_synonym(phrase):
            if column_name is None:
                if table_name not in understanding.entities:
                    understanding.entities.append(table_name)
                continue
            ref = f"{table_name}.{column_name}"
            col_type = ""
            tprof = catalog.tables.get(table_name)
            if tprof:
                for c in tprof.columns:
                    if c.name == column_name:
                        col_type = c.type.upper()
                        break
            is_numeric = any(t in col_type for t in ("INT", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL", "REAL"))
            bucket = understanding.metrics if is_numeric else understanding.dimensions
            if ref not in bucket:
                bucket.append(ref)
            if table_name not in understanding.entities:
                understanding.entities.append(table_name)

    return understanding
