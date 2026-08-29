"""Semantic Contract Builder.

Constructs, grounds, validates answerability, and freezes a SemanticContract
prior to SQL generation.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from loguru import logger

from app.agent.semantic.models import (
    SemanticContract, SemanticGrain, GrainType, MetricSpec, DimensionSpec,
    TimeSpec, FilterSpec, SortSpec, FormulaType, FilterOperator,
)
from app.agent.semantic.models import business_metric_registry
from app.agent.semantic.resolvers import time_resolver
from app.agent.semantic.resolvers import filter_resolver


class SemanticContractBuilder:
    """
    Constructs a deterministic, schema-grounded, and frozen SemanticContract.
    """

    def build_contract(
        self,
        question: str,
        schema: Optional[Dict[str, Any]] = None,
        candidate_tables: Optional[List[str]] = None,
        raw_entities: Optional[List[str]] = None,
        raw_metrics: Optional[List[str]] = None,
        raw_dimensions: Optional[List[str]] = None,
        raw_filters: Optional[List[Any]] = None,
        raw_sorting: Optional[List[Any]] = None,
        limit: Optional[int] = None,
        intent: str = "database",
        route: str = "data_query",
        analysis_type: str = "unknown",
        requires_clarification: bool = False,
        clarification_prompt: Optional[str] = None,
        ambiguity_candidates: Optional[List[str]] = None,
    ) -> SemanticContract:
        """Build and freeze a SemanticContract."""
        q_clean = (question or "").strip()
        q_lower = q_clean.lower()
        candidate_tables = candidate_tables or []
        raw_entities = raw_entities or []
        raw_metrics = raw_metrics or []
        raw_dimensions = raw_dimensions or []
        raw_filters = raw_filters or []
        raw_sorting = raw_sorting or []

        # 1. Resolve Measures / Metrics via Business Metric Registry
        measures: List[MetricSpec] = []
        # Check explicit metric strings first
        for m_text in raw_metrics:
            spec = business_metric_registry.resolve_metric(m_text, schema, candidate_tables)
            if spec and not any(m.metric_id == spec.metric_id for m in measures):
                measures.append(spec)

        # Check full question text if no metric found yet
        if not measures:
            spec = business_metric_registry.resolve_metric(q_clean, schema, candidate_tables)
            if spec:
                measures.append(spec)

        # Fallback metric if question requested count / aggregation
        if not measures and any(kw in q_lower for kw in ("count", "number of", "how many", "كم عدد", "عدد")):
            # Count metric
            target_t = candidate_tables[0] if candidate_tables else (raw_entities[0] if raw_entities else None)
            measures.append(MetricSpec(
                metric_id="count",
                display_name="Total Count",
                formula_type=FormulaType.COUNT,
                source_table=target_t,
                source_column="*",
                expression="COUNT(*)",
            ))

        # 2. Resolve Temporal Specification via TimeResolver
        time_spec = time_resolver.resolve_time(q_clean, schema, candidate_tables)

        # 3. Resolve Grouping Dimensions
        dimensions: List[DimensionSpec] = []
        for dim_text in raw_dimensions:
            target_t, target_col = self._ground_dimension(dim_text, schema, candidate_tables)
            if target_col is not None or schema is None:
                dimensions.append(DimensionSpec(
                    dimension_id=dim_text.lower().replace(" ", "_"),
                    display_name=dim_text,
                    source_table=target_t,
                    source_column=target_col or dim_text,
                ))
            else:
                logger.debug("Omitted ungrounded dimension '%s' from Semantic Contract", dim_text)


        # If time grain detected without explicit dimension, add temporal dimension
        if time_spec and time_spec.granularity and not any(d.temporal_grain for d in dimensions):
            dimensions.append(DimensionSpec(
                dimension_id=f"time_{time_spec.granularity.lower()}",
                display_name=f"Period ({time_spec.granularity})",
                source_table=time_spec.source_table,
                source_column=time_spec.time_column,
                temporal_grain=time_spec.granularity,
            ))

        # 4. Resolve Typed Filter Predicates via FilterResolver
        filters = filter_resolver.resolve_filters(raw_filters, schema, candidate_tables)

        # 5. Resolve Sorting
        sorting: List[SortSpec] = []
        for s in raw_sorting:
            col = getattr(s, "column", None) or (s.get("column") if isinstance(s, dict) else str(s))
            direction = getattr(s, "direction", "DESC") or (s.get("direction") if isinstance(s, dict) else "DESC")
            if col:
                sorting.append(SortSpec(
                    target=col,
                    direction=direction.upper(),
                    is_metric=any(m.metric_id in col.lower() or (m.source_column and m.source_column.lower() in col.lower()) for m in measures),
                ))

        # 6. Deduce Logical Grain & Output Shape
        primary_entity = raw_entities[0] if raw_entities else (candidate_tables[0] if candidate_tables else None)
        grain = self._deduce_grain(dimensions, measures, time_spec, primary_entity)
        
        # Deduce Output Shape
        if grain.grain_type == GrainType.SCALAR:
            expected_shape = "scalar"
        elif limit and (sorting or "top" in q_lower or "أفضل" in q_lower or "أعلى" in q_lower):
            expected_shape = "ranking"
        elif time_spec and time_spec.granularity:
            expected_shape = "time_series"
        elif len(dimensions) > 0:
            expected_shape = "table"
        else:
            expected_shape = "table"

        # 7. Check Answerability
        is_answerable = True
        unsupported_reason = None
        if schema is not None and len(schema) == 0:
            is_answerable = False
            unsupported_reason = "The database schema is empty or inaccessible."


        # 8. Create Contract and Freeze
        contract = SemanticContract(
            raw_question=question,
            normalized_question=q_clean,
            intent=intent,
            route=route,
            primary_entity=primary_entity,
            grain=grain,
            measures=measures,
            dimensions=dimensions,
            time_spec=time_spec,
            filters=filters,
            sorting=sorting,
            limit=limit,
            expected_output_shape=expected_shape,
            analysis_type=analysis_type,
            is_answerable=is_answerable,
            unsupported_reason=unsupported_reason,
            requires_clarification=requires_clarification,
            clarification_prompt=clarification_prompt,
            ambiguity_candidates=ambiguity_candidates or [],
        )

        # Freeze the contract (locks attributes and produces deterministic SHA256 hash)
        contract.freeze()
        return contract

    def _deduce_grain(
        self,
        dimensions: List[DimensionSpec],
        measures: List[MetricSpec],
        time_spec: Optional[TimeSpec],
        primary_entity: Optional[str],
    ) -> SemanticGrain:
        """Deduce mathematical grain from dimensions and metrics."""
        if not dimensions and measures:
            return SemanticGrain(
                grain_type=GrainType.SCALAR,
                primary_entity=primary_entity,
                grain_keys=[],
                description="Single aggregated scalar output across entire dataset",
            )
        elif len(dimensions) == 1:
            d = dimensions[0]
            if d.temporal_grain:
                return SemanticGrain(
                    grain_type=GrainType.TEMPORAL_GRAIN,
                    primary_entity=primary_entity,
                    grain_keys=[d.source_column or d.dimension_id],
                    description=f"One record per time period ({d.temporal_grain})",
                )
            return SemanticGrain(
                grain_type=GrainType.ENTITY_GRAIN,
                primary_entity=primary_entity or d.dimension_id,
                grain_keys=[d.source_column or d.dimension_id],
                description=f"One record per {d.display_name or d.dimension_id}",
            )
        elif len(dimensions) > 1:
            return SemanticGrain(
                grain_type=GrainType.MULTIDIMENSIONAL,
                primary_entity=primary_entity,
                grain_keys=[d.source_column or d.dimension_id for d in dimensions],
                description=f"One record per combination of ({', '.join(d.display_name or d.dimension_id for d in dimensions)})",
            )
        else:
            return SemanticGrain(
                grain_type=GrainType.LIST_GRAIN,
                primary_entity=primary_entity,
                grain_keys=[],
                description=f"List of individual {primary_entity or 'records'}",
            )

    def _ground_dimension(
        self,
        dim_text: str,
        schema: Optional[Dict[str, Any]],
        candidate_tables: Optional[List[str]],
    ) -> tuple[Optional[str], Optional[str]]:
        """Find matching table and column for dimension, rejecting hallucinated dimensions."""
        if not schema or not dim_text:
            return None, dim_text

        dim_lower = dim_text.lower().strip()
        schema_tables = {t.lower(): t for t in schema.keys()}
        short_schema_tables = {t.split(".")[-1].lower(): t for t in schema.keys()}

        # 1. Qualified dimension, e.g. "customers.country"
        if "." in dim_lower:
            parts = dim_lower.split(".")
            tbl_hint, col_hint = parts[0], parts[-1]
            real_tbl = schema_tables.get(tbl_hint) or short_schema_tables.get(tbl_hint)
            if real_tbl:
                tinfo = schema.get(real_tbl) or {}
                cols = [c.get("name") if isinstance(c, dict) else str(c) for c in tinfo.get("columns", [])]
                for c in cols:
                    if c.lower() == col_hint:
                        return real_tbl, c

        # 2. Prioritized search tables
        search_tables = []
        if candidate_tables:
            for ct in candidate_tables:
                ct_clean = ct.lower().strip()
                if ct_clean in schema_tables:
                    search_tables.append(schema_tables[ct_clean])
                elif ct_clean in short_schema_tables:
                    search_tables.append(short_schema_tables[ct_clean])

        if not search_tables:
            search_tables = list(schema.keys())

        # Exact column name match
        for table_name in search_tables:
            table_info = schema.get(table_name) or {}
            columns = []
            if isinstance(table_info, dict):
                columns = [col.get("name") if isinstance(col, dict) else str(col) for col in table_info.get("columns", [])]
            elif isinstance(table_info, list):
                columns = [c.get("name") if isinstance(c, dict) else str(c) for c in table_info]

            for c in columns:
                if c.lower() == dim_lower:
                    return table_name, c

        # Substring match
        for table_name in search_tables:
            table_info = schema.get(table_name) or {}
            columns = [col.get("name") if isinstance(col, dict) else str(col) for col in table_info.get("columns", [])]
            for c in columns:
                if dim_lower in c.lower() or c.lower() in dim_lower:
                    return table_name, c

        # Temporal grain identifiers
        if dim_lower in ("year", "month", "quarter", "day", "date", "period", "سنة", "شهر", "يوم", "تاريخ"):
            return None, dim_text

        # If not found in schema, return None, None to prevent hallucinated columns
        return None, None


# Global builder singleton
semantic_contract_builder = SemanticContractBuilder()

