"""Prompt Builder for SQL generation and repair."""
from typing import Any, Dict, Optional, List
from langchain_core.prompts import PromptTemplate
from app.agent.llm.prompts import SQL_ZERO_SHOT_TEMPLATE, SQL_FIX_TEMPLATE
from app.agent.semantic.models import QueryUnderstanding
from app.services.sql.dialect_rules import get_dialect_guidelines
from app.utils.text_processor import build_temporal_grounding_hint
from app.agent.semantic.database_knowledge_store import database_knowledge_store


class SQLPromptBuilder:
    """Formats structured prompts for initial SQL generation and self-healing repair."""

    def __init__(self):
        self.zero_shot_template = SQL_ZERO_SHOT_TEMPLATE
        self.fix_template = PromptTemplate(
            input_variables=["schema", "question", "sql", "error", "dialect_guidelines", "semantic_constraints"],
            template=SQL_FIX_TEMPLATE
        )

    def _format_semantic_constraints(
        self,
        schema_text: str,
        question: str,
        conversation_history: str = "",
        query_understanding: Optional[Any] = None,
        dialect: str = "sqlite",
        db_identifier: str = "",
    ) -> str:
        """Format strict semantic contract, grounding constraints, domain knowledge, and temporal hints."""
        parts = []

        hint = build_temporal_grounding_hint(question, schema_text)
        if hint:
            parts.append(hint)

        if conversation_history:
            parts.append(f"<conversation_history>\n{conversation_history}\n</conversation_history>")

        # 1. Format Strict Semantic Contract & Grounding Constraints
        if query_understanding:
            constraints = []
            if getattr(query_understanding, "entities", None):
                constraints.append(f"- Entities / Tables: {', '.join(query_understanding.entities)}")

            contract = getattr(query_understanding, "semantic_contract", None) or (
                query_understanding.to_semantic_contract()
                if hasattr(query_understanding, "to_semantic_contract")
                else None
            )

            if contract:
                # Target Grain
                if contract.grain:
                    grain_type_str = contract.grain.grain_type.value if hasattr(contract.grain.grain_type, "value") else str(contract.grain.grain_type)
                    constraints.append(f"- Output Grain: {grain_type_str.upper()} ({contract.grain.description})")

                # Measures and exact aggregation formulas from Enterprise Metric Registry
                target_measures = (contract.measures if contract and contract.measures else getattr(query_understanding, "target_metrics", []))
                if target_measures:
                    m_list = []
                    for m in target_measures:
                        f_type = m.formula_type.value if hasattr(m.formula_type, "value") else str(m.formula_type)
                        raw_col = m.source_column or m.metric_id
                        tbl = f"{m.source_table}." if m.source_table and not ("." in raw_col or "(" in raw_col) else ""
                        if m.expression and ("(" in m.expression or "*" in m.expression):
                            expr = m.expression
                        elif f_type.lower() == "count_distinct":
                            expr = f"COUNT(DISTINCT {tbl}{raw_col})"
                        else:
                            expr = f"{f_type.upper()}({tbl}{raw_col})"
                        m_list.append(f"{m.display_name or m.metric_id} -> {expr}")
                    constraints.append(f"- Required Measures / Aggregations: {'; '.join(m_list)}")

                # Grouping dimensions
                if contract.dimensions:
                    d_list = []
                    for d in contract.dimensions:
                        tbl = f"{d.source_table}." if d.source_table else ""
                        col = d.source_column or d.dimension_id
                        d_list.append(f"{tbl}{col}")
                    constraints.append(f"- Required Dimensions / GROUP BY: {', '.join(d_list)}")

                # Temporal Scope & Time Bounds
                if contract.time_spec and (contract.time_spec.start_date or contract.time_spec.end_date):
                    t_col = contract.time_spec.time_column or "date"
                    t_tbl = f"{contract.time_spec.source_table}." if contract.time_spec.source_table else ""
                    bounds = []
                    if contract.time_spec.start_date:
                        bounds.append(f"{t_tbl}{t_col} >= '{contract.time_spec.start_date}'")
                    if contract.time_spec.end_date:
                        bounds.append(f"{t_tbl}{t_col} <= '{contract.time_spec.end_date}'")
                    constraints.append(f"- Temporal Scope: {' AND '.join(bounds)} ({contract.time_spec.raw_expression})")

                # Mandatory Typed Filter Predicates
                if contract.filters:
                    f_list = [f.to_sql_predicate() for f in contract.filters]
                    constraints.append(f"- Mandatory Filter Predicates: {' AND '.join(f_list)}")

                # Sorting and Limit
                if contract.sorting:
                    s_list = [f"{s.target} {s.direction}" for s in contract.sorting]
                    constraints.append(f"- Ordering: {', '.join(s_list)}")
                if contract.limit:
                    constraints.append(f"- Limit: {contract.limit}")
                if contract.expected_output_shape:
                    constraints.append(f"- Expected Output Shape: {contract.expected_output_shape.upper()}")

            else:
                # Fallback to standard QuerySpec fields
                if getattr(query_understanding, "metrics", None):
                    constraints.append(f"- Metrics / Aggregations: {', '.join(query_understanding.metrics)}")
                if getattr(query_understanding, "dimensions", None):
                    constraints.append(f"- Grouping / Dimensions: {', '.join(query_understanding.dimensions)}")
                if getattr(query_understanding, "filters", None):
                    flist = [f"{f.column} {f.operator} {f.value}" for f in query_understanding.filters if getattr(f, "column", None)]
                    if flist:
                        constraints.append(f"- Mandatory Filters: {', '.join(flist)}")
                if getattr(query_understanding, "sorting", None):
                    slist = [f"{s.column} {s.direction}" for s in query_understanding.sorting if getattr(s, "column", None)]
                    if slist:
                        constraints.append(f"- Ordering: {', '.join(slist)}")
                if getattr(query_understanding, "limit", None):
                    constraints.append(f"- Limit: {query_understanding.limit}")

            if constraints:
                plan_block = "\n".join(["[Semantic Query Plan & Grounding Constraints]"] + constraints)
                parts.append(plan_block)

        # 2. Extract and inject relevant Database Domain Knowledge & Golden Few-Shots
        knowledge_block = database_knowledge_store.format_prompt_knowledge_section(
            question=question,
            db_identifier=db_identifier or dialect,
        )
        if knowledge_block:
            parts.append(knowledge_block)

        return "\n\n".join(parts).strip()

    def build_generation_input(
        self,
        schema_text: str,
        question: str,
        conversation_history: str = "",
        query_understanding: Optional[QueryUnderstanding] = None,
        dialect: str = "sqlite",
        db_identifier: str = "",
    ) -> Dict[str, Any]:
        """Build input payload for the SQL generation LLM chain with strict grounding & domain intelligence."""
        context_str = self._format_semantic_constraints(
            schema_text=schema_text,
            question=question,
            conversation_history=conversation_history,
            query_understanding=query_understanding,
            dialect=dialect,
            db_identifier=db_identifier,
        )
        dialect_guidelines = get_dialect_guidelines(dialect)

        return {
            "schema": schema_text,
            "question": question,
            "conversation_history": context_str,
            "dialect_guidelines": dialect_guidelines,
        }

    def build_fix_input(
        self,
        schema_text: str,
        question: str,
        failed_sql: str,
        error: str,
        dialect: str = "sqlite",
        query_understanding: Optional[Any] = None,
        conversation_history: str = "",
        db_identifier: str = "",
    ) -> Dict[str, Any]:
        """Build input payload for the SQL fix/repair LLM chain with full semantic adherence context."""
        context_str = self._format_semantic_constraints(
            schema_text=schema_text,
            question=question,
            conversation_history=conversation_history,
            query_understanding=query_understanding,
            dialect=dialect,
            db_identifier=db_identifier,
        )
        dialect_guidelines = get_dialect_guidelines(dialect)
        return {
            "schema": schema_text,
            "question": question,
            "sql": failed_sql,
            "error": error,
            "dialect_guidelines": dialect_guidelines,
            "semantic_constraints": context_str,
        }
