"""LLM-based Query Understanding Node (Rebuild Plan - Phase 1).

Replaces keyword/regex pattern-matching (`SemanticQueryParser.parse` +
`classify_analysis_type`) with a single structured-output LLM call that
*reasons* about the question instead of matching fixed phrases.

Design constraints this file honors (from the rebuild roadmap):
- This is an ADAPTER: `understand()` returns the exact same `QueryUnderstanding`
  model the regex parser returns, so every downstream consumer (schema
  grounding, planner trigger, SQL generation) is unaffected.
- This layer NEVER decides SQL safety - that stays 100% deterministic
  (sqlglot AST validation) elsewhere and is untouched.
- On any failure (LLM error, malformed JSON, low self-reported confidence)
  this returns `None` so the caller (HybridQueryUnderstander) falls back to
  the deterministic regex parser. This module never raises to the caller.
"""
import json
from typing import Any, Dict, Optional

from loguru import logger
from langchain_core.prompts import PromptTemplate

from app.llm.prompts import QUERY_UNDERSTANDING_TEMPLATE
from app.semantic.models import (
    QueryUnderstanding,
    SortCondition,
    OutputFormat,
)
from app.utils.text_processor import AnalysisType, extract_json_text
from app.config.settings import settings

_VALID_ANALYSIS_TYPES = {t.value for t in AnalysisType}
_VALID_AGGREGATIONS = {"COUNT", "SUM", "AVG", "MAX", "MIN"}


def _table_summary(
    schema: Optional[Dict[str, Any]],
    question: str = "",
    catalog=None,
) -> str:
    """Compact table/column listing for the prompt.

    For large schemas (> settings.llm_prompt_max_tables tables), we cannot
    dump every table into the prompt — that exceeds LLM payload limits
    (e.g. Groq's 413 Payload Too Large). Instead we select only the most
    relevant tables using, in priority order:
      1. TF-IDF retrieval from the Schema Catalog (if a glossary exists)
      2. Keyword matching against table/column names from the question
      3. FK-centrality fallback (most-connected tables)
    Small schemas (≤ threshold) are sent in full, unchanged from before.
    """
    if not schema:
        return "No tables available"

    max_tables = settings.llm_prompt_max_tables
    max_cols = settings.llm_prompt_max_cols_per_table

    if len(schema) <= max_tables:
        # Small schema: send everything (original behavior)
        parts = []
        for table_name, info in schema.items():
            cols = [c["name"] for c in info.get("columns", [])[:max_cols]]
            cols_str = ", ".join(cols)
            if len(info.get("columns", [])) > max_cols:
                cols_str += ", ..."
            parts.append(f"- {table_name} ({cols_str})")
        return "\n".join(parts)

    # --- Large schema: relevance-based filtering ---
    selected_tables: list[str] = []

    # 1. Try TF-IDF retrieval from catalog (best quality)
    if question and catalog is not None:
        try:
            from app.schema_catalog.retrieval import retrieve_relevant_tables
            retrieved = retrieve_relevant_tables(question, catalog, k=max_tables)
            if retrieved:
                selected_tables = [t for t in retrieved if t in schema]
        except Exception:
            pass

    # 2. If catalog retrieval didn't produce enough, supplement with
    #    keyword matching against table/column names
    if len(selected_tables) < 20 and question:
        q_lower = question.lower()
        for table_name in schema:
            if table_name in selected_tables:
                continue
            t_lower = table_name.lower()
            # Match table name or its singular/plural forms
            if (
                t_lower in q_lower
                or any(form in q_lower for form in (
                    t_lower + "s", t_lower + "es",
                    t_lower[:-1] + "ies" if t_lower.endswith("y") else "",
                    t_lower[:-1] if t_lower.endswith("s") else "",
                ))
            ):
                selected_tables.append(table_name)
            else:
                # Match column names
                for col in schema[table_name].get("columns", []):
                    col_lower = col["name"].lower()
                    if len(col_lower) > 3 and col_lower in q_lower:
                        selected_tables.append(table_name)
                        break
            if len(selected_tables) >= max_tables:
                break

    # 3. If still nothing, fallback to FK-centrality (most connected tables)
    if not selected_tables:
        try:
            from app.database.context import db_context_manager
            from app.schema_grounding.schema_intelligence import compute_structural_schema_fingerprint
            fp = compute_structural_schema_fingerprint(schema)
            ctx = db_context_manager.get(fp)
            if ctx and ctx.relationship_graph:
                graph = ctx.relationship_graph
            else:
                from app.schema_grounding.relationship_graph import SchemaRelationshipGraph
                graph = SchemaRelationshipGraph(schema)
            selected_tables = list(graph.get_most_central_tables(limit=max_tables))
        except Exception:
            # Last resort: take first max_tables alphabetically
            selected_tables = sorted(schema.keys())[:max_tables]

    # Cap to max_tables
    selected_tables = selected_tables[:max_tables]

    parts = []
    for table_name in selected_tables:
        info = schema.get(table_name, {})
        cols = [c["name"] for c in info.get("columns", [])[:max_cols]]
        cols_str = ", ".join(cols)
        if len(info.get("columns", [])) > max_cols:
            cols_str += ", ..."
        parts.append(f"- {table_name} ({cols_str})")

    header = f"[Showing {len(selected_tables)} most relevant tables out of {len(schema)} total]"
    return f"{header}\n" + "\n".join(parts)


def _derive_expected_output(analysis_type: AnalysisType, aggregations: list, dimensions: list, limit: Optional[int]) -> OutputFormat:
    """Same derivation rule the regex parser uses, kept identical for consistency."""
    if analysis_type == AnalysisType.COUNT or (aggregations == ["COUNT"] and not dimensions):
        return OutputFormat.SCALAR
    if limit is not None or analysis_type == AnalysisType.RANKING:
        return OutputFormat.RANKING
    if analysis_type == AnalysisType.TREND:
        return OutputFormat.TIME_SERIES
    if analysis_type == AnalysisType.LOOKUP and not dimensions:
        return OutputFormat.LIST
    return OutputFormat.TABLE


class LLMQueryUnderstander:
    """Structured-output LLM reasoning node for query understanding."""

    def __init__(self, fast_llm):
        self.fast_llm = fast_llm
        self.chain = (
            PromptTemplate(
                input_variables=["table_names", "question", "conversation_history"],
                template=QUERY_UNDERSTANDING_TEMPLATE,
            )
            | self.fast_llm
        )

    async def understand(
        self,
        question: str,
        schema: Optional[Dict[str, Any]] = None,
        conversation_history: str = "",
        catalog=None,
    ) -> Optional[QueryUnderstanding]:
        """Return a QueryUnderstanding via LLM reasoning, or None on any failure/low confidence."""
        if not question or not question.strip():
            return None

        try:
            response = await self.chain.ainvoke({
                "table_names": _table_summary(schema, question=question, catalog=catalog),
                "question": question,
                "conversation_history": conversation_history,
            })
            data = json.loads(extract_json_text(response.content))
        except Exception as e:
            logger.warning("LLM query understanding failed, will fall back to regex parser: %s", e)
            return None

        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        if confidence < settings.llm_understanding_min_confidence:
            logger.info(
                "LLM understanding confidence %.2f below threshold %.2f, falling back to regex.",
                confidence, settings.llm_understanding_min_confidence,
            )
            return None

        analysis_type_raw = str(data.get("analysis_type", "unknown")).lower()
        if analysis_type_raw not in _VALID_ANALYSIS_TYPES:
            analysis_type_raw = "unknown"
        analysis_type = AnalysisType(analysis_type_raw)

        entities = [e for e in data.get("entities", []) if isinstance(e, str)]
        metrics = [m for m in data.get("metrics", []) if isinstance(m, str)]
        dimensions = [d for d in data.get("dimensions", []) if isinstance(d, str)]
        aggregations = [a for a in data.get("aggregations", []) if isinstance(a, str) and a.upper() in _VALID_AGGREGATIONS]
        aggregations = [a.upper() for a in aggregations]

        limit = data.get("limit")
        try:
            limit = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            limit = None

        sort_direction = data.get("sort_direction")
        sorting = []
        if sort_direction in ("DESC", "ASC"):
            sorting.append(SortCondition(direction=sort_direction))

        time_expressions = [t for t in data.get("time_expressions", []) if isinstance(t, str)]
        business_goal = data.get("business_goal") if isinstance(data.get("business_goal"), str) else None
        requires_multi_step = bool(data.get("requires_multi_step", False))

        expected_output = _derive_expected_output(analysis_type, aggregations, dimensions, limit)

        try:
            return QueryUnderstanding(
                raw_question=question.strip(),
                analysis_type=analysis_type,
                entities=entities,
                metrics=metrics,
                dimensions=dimensions,
                filters=[],
                time_expressions=time_expressions,
                aggregations=aggregations,
                sorting=sorting,
                limit=limit,
                expected_output=expected_output,
                requires_multi_step=requires_multi_step,
                confidence=confidence,
                source="llm",
                business_goal=business_goal,
            )
        except Exception as e:
            logger.warning("LLM understanding produced an invalid QueryUnderstanding, falling back: %s", e)
            return None
