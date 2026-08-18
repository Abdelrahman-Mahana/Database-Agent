"""Unified QuerySpec Builder — Consolidates Intent, Semantic Understanding, and Planning."""
import re
from typing import Any, Dict, Optional, List, Set
from loguru import logger

from app.semantic.models import (
    QuerySpec, IntentType, ExecutionRoute, FilterCondition, SortCondition,
    OutputFormat, UnderstandingConfidence,
)
from app.semantic.synonyms import resolve_synonyms
from app.semantic.llm_understanding import LLMQueryUnderstander
from app.semantic.ambiguity_resolver import ambiguity_resolver, AmbiguityResolution
from app.utils.text_processor import classify_analysis_type, AnalysisType, COMPLEX_ANALYSIS_TYPES
from app.schema_catalog.models import SchemaCatalog
from app.config.settings import settings


class QuerySpecBuilder:
    """
    Unified QuerySpec Engine.
    Combines Intent Classification, Semantic Parsing, Business Synonym Resolution,
    and Planning Detection into a single, high-performance, single-pass pipeline.
    """

    _BUSINESS_MEASURE_TERMS = {
        "revenue", "sales", "profit", "income", "turnover", "earnings", "margin",
        "cost", "price", "amount", "total", "balance", "quantity", "volume",
        "إيراد", "إيرادات", "مبيعات", "ربح", "أرباح", "دخل", "مبلغ", "قيمة",
    }
    _TIME_CUES = {
        "year", "month", "week", "day", "date", "quarter", "since", "before", "after",
        "between", "during", "last", "recent", "today", "yesterday",
        "سنة", "شهر", "أسبوع", "يوم", "تاريخ", "ربع", "من", "إلى", "خلال", "آخر",
    }
    _FILTER_CUES = {
        "where", "only", "except", "excluding", "in ", "between", "greater", "less",
        "equal", "filter", "matching",
        "فقط", "ما عدا", "عدا", "بين", "أكبر", "أقل", "يساوي", "فلتر",
    }
    _AMBIGUITY_MARKERS = (
        "best", "top", "most", "compare", "vs", "versus", "trend", "why", "correlat",
        "أفضل", "أكثر", "قارن", "مقارنة", "اتجاه", "لماذا", "علاقة",
    )
    _CONFIDENCE_WEIGHTS = {
        "route": 0.15,
        "entity": 0.25,
        "metric": 0.20,
        "filter": 0.10,
        "time": 0.10,
        "aggregation": 0.10,
    }

    def __init__(self, fast_llm=None):
        self.fast_llm = fast_llm
        self.llm_understander = LLMQueryUnderstander(fast_llm) if fast_llm is not None else None

    def _score_entity_confidence(self, entities: List[str], analysis_type: AnalysisType) -> float:
        if entities:
            return min(0.95, 0.70 + min(0.25, len(entities) * 0.08))
        if analysis_type != AnalysisType.UNKNOWN:
            return 0.45
        return 0.25

    def _question_implies_measure(self, q_lower: str, aggregations: List[str], analysis_type: AnalysisType) -> bool:
        if aggregations:
            return True
        if analysis_type in (AnalysisType.AGGREGATION, AnalysisType.RANKING, AnalysisType.COMPARISON, AnalysisType.TREND):
            return True
        return any(term in q_lower for term in self._BUSINESS_MEASURE_TERMS)

    def _question_has_unmapped_measure_terms(
        self,
        q_lower: str,
        metrics: List[str],
        dimensions: List[str],
    ) -> bool:
        mapped_text = " ".join(metrics + dimensions).lower()
        for term in self._BUSINESS_MEASURE_TERMS:
            if term in q_lower and term not in mapped_text:
                return True
        return False

    def _score_metric_confidence(
        self,
        q_lower: str,
        metrics: List[str],
        aggregations: List[str],
        analysis_type: AnalysisType,
        dimensions: List[str],
    ) -> float:
        implies_measure = self._question_implies_measure(q_lower, aggregations, analysis_type)
        if implies_measure:
            if metrics:
                return 0.92
            if self._question_has_unmapped_measure_terms(q_lower, metrics, dimensions):
                return 0.35
            return 0.40
        if metrics:
            return 0.85
        return 0.78

    def _question_implies_grouping(self, q_lower: str, analysis_type: AnalysisType, dimensions: List[str]) -> bool:
        if dimensions:
            return True
        return analysis_type in (AnalysisType.RANKING, AnalysisType.COMPARISON, AnalysisType.AGGREGATION, AnalysisType.TREND)

    def _score_dimension_confidence_as_filter_proxy(
        self,
        q_lower: str,
        filters: List[FilterCondition],
    ) -> float:
        has_filter_cue = any(cue in q_lower for cue in self._FILTER_CUES)
        if has_filter_cue:
            return 0.90 if filters else 0.42
        if filters:
            return 0.88
        return 0.80

    def _score_time_confidence(self, q_lower: str, time_expressions: List[str], filters: List[FilterCondition]) -> float:
        has_time_cue = any(cue in q_lower for cue in self._TIME_CUES) or bool(re.search(r"\b(19\d\d|20\d\d)\b", q_lower))
        has_time_value = bool(time_expressions) or any(
            getattr(f, "raw_expression", "") and any(cue in getattr(f, "raw_expression", "").lower() for cue in ("year", "date", "month"))
            for f in filters
        )
        if has_time_cue:
            return 0.90 if has_time_value else 0.42
        if has_time_value:
            return 0.85
        return 0.80

    def _score_aggregation_confidence(self, q_lower: str, aggregations: List[str]) -> float:
        agg_cues = (
            r"\b(how many|count|number of|total|sum|average|avg|mean|highest|maximum|max|"
            r"lowest|minimum|min|most|least|كم|كم عدد|عدد|اجمالي|إجمالي|مجموع|متوسط|"
            r"أكبر|اكبر|أعلى|اعلى|أقل|اقل)\b"
        )
        has_agg_cue = bool(re.search(agg_cues, q_lower))
        if has_agg_cue:
            return 0.90 if aggregations else 0.38
        if aggregations:
            return 0.82
        return 0.76

    def _compute_ambiguity_penalty(
        self,
        q_lower: str,
        entities: List[str],
        metrics: List[str],
        dimensions: List[str],
    ) -> float:
        penalty = 0.0
        if any(marker in q_lower for marker in self._AMBIGUITY_MARKERS):
            penalty += 0.08
        if len(entities) >= 3 and not metrics:
            penalty += 0.07
        if not entities and not metrics:
            penalty += 0.10
        if self._question_has_unmapped_measure_terms(q_lower, metrics, dimensions):
            penalty += 0.15
        return min(0.35, penalty)

    def _compute_understanding_confidence(
        self,
        q_lower: str,
        route_confidence: float,
        analysis_type: AnalysisType,
        entities: List[str],
        metrics: List[str],
        dimensions: List[str],
        filters: List[FilterCondition],
        time_expressions: List[str],
        aggregations: List[str],
    ) -> UnderstandingConfidence:
        entity_confidence = self._score_entity_confidence(entities, analysis_type)
        metric_confidence = self._score_metric_confidence(
            q_lower, metrics, aggregations, analysis_type, dimensions,
        )
        filter_confidence = self._score_dimension_confidence_as_filter_proxy(q_lower, filters)
        time_confidence = self._score_time_confidence(q_lower, time_expressions, filters)
        aggregation_confidence = self._score_aggregation_confidence(q_lower, aggregations)
        ambiguity_penalty = self._compute_ambiguity_penalty(q_lower, entities, metrics, dimensions)

        weighted = (
            self._CONFIDENCE_WEIGHTS["route"] * route_confidence
            + self._CONFIDENCE_WEIGHTS["entity"] * entity_confidence
            + self._CONFIDENCE_WEIGHTS["metric"] * metric_confidence
            + self._CONFIDENCE_WEIGHTS["filter"] * filter_confidence
            + self._CONFIDENCE_WEIGHTS["time"] * time_confidence
            + self._CONFIDENCE_WEIGHTS["aggregation"] * aggregation_confidence
        )
        # Remaining 10% reflects semantic completeness after ambiguity discount.
        completeness = 0.10 * min(entity_confidence, metric_confidence, filter_confidence)
        overall = max(0.05, min(0.99, round(weighted + completeness - ambiguity_penalty, 3)))

        return UnderstandingConfidence(
            route_confidence=round(route_confidence, 3),
            entity_confidence=round(entity_confidence, 3),
            metric_confidence=round(metric_confidence, 3),
            filter_confidence=round(filter_confidence, 3),
            time_confidence=round(time_confidence, 3),
            aggregation_confidence=round(aggregation_confidence, 3),
            ambiguity_penalty=round(ambiguity_penalty, 3),
            overall=overall,
        )

    def _apply_confidence(self, spec: QuerySpec, q_lower: str, route_confidence: float) -> QuerySpec:
        breakdown = self._compute_understanding_confidence(
            q_lower=q_lower,
            route_confidence=route_confidence,
            analysis_type=spec.analysis_type,
            entities=spec.entities,
            metrics=spec.metrics,
            dimensions=spec.dimensions,
            filters=spec.filters,
            time_expressions=spec.time_expressions,
            aggregations=spec.aggregations,
        )
        spec.understanding_confidence = breakdown
        spec.confidence = breakdown.overall
        return spec

    def _question_has_explicit_table_reference(self, q_lower: str, db_ctx: Optional[Any]) -> bool:
        if db_ctx is None or not getattr(db_ctx, "table_names_set", None):
            return False

        words = set(re.findall(r'[\w\u0600-\u06FF]+', q_lower))
        # DatabaseContext may keep names as ``schema.table`` (PostgreSQL) or
        # as bare table names (SQLite).  A user who explicitly says
        # ``patient_model`` has supplied evidence for ``public.patient_model``
        # and must not be sent through the semantic ambiguity gate.
        lower_table_names = {
            t.lower().strip('"').split(".")[-1].strip('"')
            for t in db_ctx.table_names_set
        }
        for token in words:
            if token in lower_table_names:
                return True
            if token.endswith("s") and token[:-1] in lower_table_names:
                return True
            if (token + "s") in lower_table_names:
                return True
        return False

    def _explicit_table_references(self, q_lower: str, db_ctx: Optional[Any]) -> Set[str]:
        """Return canonical schema keys explicitly named in the question.

        This is deliberately evaluated before semantic retrieval. An exact table
        reference is stronger evidence than broad keyword hits such as
        ``records`` or one-letter column names.
        """
        if db_ctx is None or not getattr(db_ctx, "table_names_set", None):
            return set()

        words = set(re.findall(r'[\w\u0600-\u06FF]+', q_lower))
        matches: Set[str] = set()
        for table_name in db_ctx.table_names_set:
            bare_name = table_name.lower().strip('"').split(".")[-1].strip('"')
            if bare_name in words:
                matches.add(table_name)
        return matches

    @staticmethod
    def _column_is_explicitly_referenced(column_name: str, words: Set[str], q_lower: str) -> bool:
        column_lower = column_name.lower()
        return column_lower in words or (
            len(column_lower) >= 3
            and bool(re.search(rf"(?<!\w){re.escape(column_lower)}(?!\w)", q_lower))
        )

    def _resolve_data_ambiguity(
        self,
        question: str,
        q_lower: str,
        db_ctx: Optional[Any],
        catalog: Optional[SchemaCatalog],
        candidate_table_set: Set[str],
        metrics: List[str],
        dimensions: List[str],
    ) -> Optional[AmbiguityResolution]:
        if db_ctx is None or len(candidate_table_set) < 2:
            return None
        if self._question_has_explicit_table_reference(q_lower, db_ctx):
            return None

        # Multi-table intent is explicit here, so we should not interrupt with clarification.
        multi_table_cues = (
            " join ", " between ", " compare ", " vs ", " versus ", " and ",
            "العلاقة بين", "الفرق بين", "قارن بين", "مقارنة", "مع ",
        )
        if any(cue in f" {q_lower} " for cue in multi_table_cues):
            return None

        scored_candidates: List[Dict[str, Any]] = []
        cat = catalog or getattr(db_ctx, "catalog", None)
        if cat is not None:
            try:
                from app.schema_catalog.retrieval import HybridCandidateRetriever

                c_retriever = getattr(db_ctx, "candidate_retriever", None) or HybridCandidateRetriever(cat)
                retrieved = c_retriever.retrieve_candidate_tables(question, k=max(5, len(candidate_table_set)))
                for cand in retrieved:
                    if cand.table_name in candidate_table_set:
                        scored_candidates.append(
                            {
                                "name": cand.table_name,
                                "score": cand.score,
                                "reason": f"Matched via {', '.join(cand.match_sources) or 'hybrid retrieval'}",
                            }
                        )
            except Exception as e:
                logger.debug("Candidate retrieval for ambiguity detection skipped: %s", e)

        # Fallback for exact same bare column/metric name appearing in multiple tables.
        if len(scored_candidates) < 2:
            shared_columns: Dict[str, Set[str]] = {}
            for full_ref in metrics + dimensions:
                if "." not in full_ref:
                    continue
                table_name, column_name = full_ref.split(".", 1)
                shared_columns.setdefault(column_name.lower(), set()).add(table_name)

            ambiguous_columns = {
                col_name: tables
                for col_name, tables in shared_columns.items()
                if len(tables) >= 2
            }
            if not ambiguous_columns:
                return None

            for table_name in sorted(candidate_table_set):
                matched_cols = sorted(
                    col_name for col_name, tables in ambiguous_columns.items() if table_name in tables
                )
                if matched_cols:
                    scored_candidates.append(
                        {
                            "name": table_name,
                            "score": 1.0,
                            "reason": f"Matched ambiguous column(s): {', '.join(matched_cols[:2])}",
                        }
                    )

        if len(scored_candidates) < 2:
            return None

        resolution = ambiguity_resolver.resolve_table_ambiguity(question, scored_candidates, threshold_margin=0.15)
        return resolution if resolution.is_ambiguous else None

    def _apply_ambiguity_resolution(self, spec: QuerySpec, resolution: AmbiguityResolution) -> QuerySpec:
        spec.requires_clarification = True
        spec.clarification_prompt = resolution.clarification_prompt
        spec.ambiguity_candidates = [c.name for c in resolution.candidates]
        spec.ambiguity_evidence = resolution.evidence
        spec.confidence = min(spec.confidence, 0.35)
        if spec.understanding_confidence is not None:
            spec.understanding_confidence.ambiguity_penalty = max(
                spec.understanding_confidence.ambiguity_penalty, 0.35
            )
            spec.understanding_confidence.overall = spec.confidence
        return spec

    def _build_routed_spec(
        self,
        question: str,
        q_lower: str,
        db_ctx: Optional[Any] = None,
    ) -> tuple[QuerySpec, bool]:
        route, intent_type, route_confidence, route_reply = self._quick_route(q_lower, db_ctx)
        if route in (ExecutionRoute.CONVERSATION, ExecutionRoute.SCHEMA):
            spec = QuerySpec(
                raw_question=question,
                intent=intent_type,
                route=route,
                route_confidence=route_confidence,
                off_topic_response=route_reply,
                source="deterministic_router",
                analysis_type=AnalysisType.UNKNOWN,
            )
            return self._apply_confidence(spec, q_lower, route_confidence), False
        return QuerySpec(
            raw_question=question,
            intent=IntentType.DATABASE,
            route=ExecutionRoute.DATA_QUERY,
            route_confidence=route_confidence,
            source="unified_query_spec_builder",
            analysis_type=AnalysisType.UNKNOWN,
        ), True

    def _build_deterministic_data_spec(
        self,
        question: str,
        q_lower: str,
        route_confidence: float,
        db_ctx: Optional[Any] = None,
        catalog: Optional[SchemaCatalog] = None,
    ) -> QuerySpec:
        analysis_type = classify_analysis_type(question)
        entities: List[str] = []
        metrics: List[str] = []
        dimensions: List[str] = []
        candidate_table_set: Set[str] = set()

        schema = db_ctx.schema if db_ctx is not None else None
        if schema and db_ctx is not None:
            words = set(re.findall(r'[\w\u0600-\u06FF]+', q_lower))

            # Phase 1: Candidate table discovery (zero full-schema scanning)
            _MAX_CANDIDATE_TABLES = 5

            explicit_tables = self._explicit_table_references(q_lower, db_ctx)
            if explicit_tables:
                candidate_table_set = explicit_tables
                # Preserve explicitly referenced metric columns from related
                # tables (for example, "customers by orders.total_amount")
                # without letting generic words such as "records" introduce
                # unrelated tables or one-letter columns.
                for table_name in db_ctx.match_seed_tables_fast(
                    q_lower, max_tables=_MAX_CANDIDATE_TABLES
                ):
                    table_info = schema.get(table_name, {})
                    if any(
                        self._column_is_explicitly_referenced(col["name"], words, q_lower)
                        for col in table_info.get("columns", [])
                    ):
                        candidate_table_set.add(table_name)
            elif db_ctx.keyword_to_tables:
                candidate_table_set = db_ctx.match_seed_tables_fast(
                    q_lower, max_tables=_MAX_CANDIDATE_TABLES
                )

            if not candidate_table_set and (catalog or getattr(db_ctx, "catalog", None)):
                cat = catalog or db_ctx.catalog
                from app.schema_catalog.retrieval import HybridCandidateRetriever
                c_retriever = getattr(db_ctx, "candidate_retriever", None) or HybridCandidateRetriever(cat)
                cands = c_retriever.retrieve_candidate_tables(q_lower, k=_MAX_CANDIDATE_TABLES)
                candidate_table_set = {c.table_name for c in cands if c.table_name in schema}

            if not candidate_table_set:
                # O(W) query word lookup against pre-indexed table names set
                tbl_set = db_ctx.table_names_set if db_ctx.table_names_set else set(schema.keys())
                for w in words:
                    if w in tbl_set:
                        candidate_table_set.add(w)
                    elif (w + "s") in tbl_set:
                        candidate_table_set.add(w + "s")
                    elif w.endswith("s") and w[:-1] in tbl_set:
                        candidate_table_set.add(w[:-1])
                    if len(candidate_table_set) >= _MAX_CANDIDATE_TABLES:
                        break

            # Phase 2: Deep column scan on only the retrieved candidate tables
            for t in candidate_table_set:
                if t in schema:
                    entities.append(t)
                    table_info = schema[t]
                    for col in table_info.get("columns", []):
                        col_name = col["name"]
                        c_lower = col_name.lower()
                        is_explicit_column = self._column_is_explicitly_referenced(
                            col_name, words, q_lower
                        )
                        if is_explicit_column and c_lower not in ("id", "created_at"):
                            col_type = col.get("type", "").upper()
                            is_numeric = any(num_t in col_type for num_t in ("INT", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL", "REAL"))
                            full_ref = f"{t}.{col_name}"
                            if is_numeric:
                                if full_ref not in metrics:
                                    metrics.append(full_ref)
                            else:
                                if full_ref not in dimensions:
                                    dimensions.append(full_ref)

        aggregations: List[str] = []
        if re.search(r"\b(how many|count|number of|كم|كم عدد|عدد|احسب)\b", q_lower):
            aggregations.append("COUNT")
        if re.search(r"\b(total|sum|مجموع|اجمالي|إجمالي)\b", q_lower):
            aggregations.append("SUM")
        if re.search(r"\b(average|avg|mean|متوسط|معدل)\b", q_lower):
            aggregations.append("AVG")
        if re.search(r"\b(highest|maximum|max|most|اكبر|أكبر|اعلى|أعلى|اكثر|أكثر|اكتر|حد أقصى)\b", q_lower):
            aggregations.append("MAX")
        if re.search(r"\b(lowest|minimum|min|least|اصغر|أصغر|اقل|أقل|حد ادنى)\b", q_lower):
            aggregations.append("MIN")

        limit: Optional[int] = None
        limit_match = re.search(r"\b(?:top|first|limit|best|worst|اول|أول|افضل|أفضل|اسوأ|أسوأ|اعلى|أعلى)\s+(\d+)\b", q_lower)
        if not limit_match:
            limit_match = re.search(r"\b(\d+)\s+(?:top|best|worst|artists|tracks|customers|albums|افضل|أفضل|اسوأ|أسوأ|الاوائل|الأوائل)\b", q_lower)
        if limit_match:
            try:
                limit = int(limit_match.group(1))
            except ValueError:
                pass

        sorting: List[SortCondition] = []
        if re.search(r"\b(top|highest|best|most|اعلى|أعلى|افضل|أفضل|اكثر|أكثر|اكتر)\b", q_lower):
            sorting.append(SortCondition(direction="DESC"))
        elif re.search(r"\b(bottom|lowest|worst|least|اقل|أقل|اسوأ|أسوأ)\b", q_lower):
            sorting.append(SortCondition(direction="ASC"))

        time_expressions: List[str] = []
        year_matches = re.findall(r"\b(19\d\d|20\d\d)\b", question)
        time_expressions.extend(year_matches)

        filters: List[FilterCondition] = []
        for year in year_matches:
            filters.append(FilterCondition(operator="=", value=year, raw_expression=f"year = {year}"))

        expected_output = OutputFormat.TABLE
        if analysis_type == AnalysisType.COUNT or (aggregations == ["COUNT"] and not dimensions):
            expected_output = OutputFormat.SCALAR
        elif limit is not None or analysis_type == AnalysisType.RANKING:
            expected_output = OutputFormat.RANKING

        spec = QuerySpec(
            raw_question=question,
            intent=IntentType.DATABASE,
            route=ExecutionRoute.DATA_QUERY,
            route_confidence=route_confidence,
            analysis_type=analysis_type,
            entities=entities,
            metrics=metrics,
            dimensions=dimensions,
            filters=filters,
            time_expressions=time_expressions,
            aggregations=aggregations,
            sorting=sorting,
            limit=limit,
            expected_output=expected_output,
            requires_multi_step=analysis_type in COMPLEX_ANALYSIS_TYPES,
            source="unified_query_spec_builder",
        )

        if catalog is not None:
            try:
                spec = resolve_synonyms(question, catalog, spec)
            except Exception as e:
                logger.debug("Synonym resolution skipped in QuerySpecBuilder: %s", e)

        spec = self._apply_confidence(spec, q_lower, route_confidence)
        ambiguity_resolution = self._resolve_data_ambiguity(
            question=question,
            q_lower=q_lower,
            db_ctx=db_ctx,
            catalog=catalog,
            candidate_table_set=candidate_table_set,
            metrics=spec.metrics,
            dimensions=spec.dimensions,
        )
        if ambiguity_resolution is not None:
            spec = self._apply_ambiguity_resolution(spec, ambiguity_resolution)

        return spec

    def _merge_llm_and_deterministic_specs(
        self,
        llm_spec: QuerySpec,
        deterministic_spec: QuerySpec,
    ) -> QuerySpec:
        merged = llm_spec.model_copy(deep=True)
        merged.intent = deterministic_spec.intent
        merged.route = deterministic_spec.route
        merged.route_confidence = deterministic_spec.route_confidence
        merged.off_topic_reason = deterministic_spec.off_topic_reason
        merged.off_topic_response = deterministic_spec.off_topic_response
        merged.entities = llm_spec.entities or deterministic_spec.entities
        merged.metrics = llm_spec.metrics or deterministic_spec.metrics
        merged.dimensions = llm_spec.dimensions or deterministic_spec.dimensions
        merged.filters = llm_spec.filters or deterministic_spec.filters
        merged.time_expressions = llm_spec.time_expressions or deterministic_spec.time_expressions
        merged.aggregations = llm_spec.aggregations or deterministic_spec.aggregations
        merged.sorting = llm_spec.sorting or deterministic_spec.sorting
        merged.limit = llm_spec.limit if llm_spec.limit is not None else deterministic_spec.limit
        merged.expected_output = llm_spec.expected_output or deterministic_spec.expected_output
        merged.requires_multi_step = llm_spec.requires_multi_step or deterministic_spec.requires_multi_step
        merged.plan_steps = llm_spec.plan_steps or deterministic_spec.plan_steps
        merged.business_goal = llm_spec.business_goal or deterministic_spec.business_goal
        merged.source = "llm_query_spec_builder"
        merged.requires_clarification = deterministic_spec.requires_clarification
        merged.clarification_prompt = deterministic_spec.clarification_prompt
        merged.ambiguity_candidates = deterministic_spec.ambiguity_candidates
        merged.ambiguity_evidence = deterministic_spec.ambiguity_evidence
        return merged

    async def build_spec_async(
        self,
        question: str,
        db_ctx: Optional[Any] = None,
        conversation_history: str = "",
        catalog: Optional[SchemaCatalog] = None,
    ) -> QuerySpec:
        if not question or not question.strip():
            return QuerySpec(raw_question=question or "", intent=IntentType.OFF_TOPIC)

        q = question.strip()
        q_lower = q.lower()

        routed_spec, should_build_data_spec = self._build_routed_spec(q, q_lower, db_ctx)
        if not should_build_data_spec:
            return routed_spec

        deterministic_spec = self._build_deterministic_data_spec(
            question=q,
            q_lower=q_lower,
            route_confidence=routed_spec.route_confidence,
            db_ctx=db_ctx,
            catalog=catalog,
        )

        if not settings.use_llm_understanding or self.llm_understander is None:
            return deterministic_spec
        if deterministic_spec.requires_clarification:
            return deterministic_spec

        schema = db_ctx.schema if db_ctx is not None else None
        try:
            llm_spec = await self.llm_understander.understand(
                question=q,
                schema=schema,
                conversation_history=conversation_history,
                catalog=catalog,
            )
        except Exception as e:
            logger.warning("Async LLM understanding path failed, using deterministic QuerySpec: %s", e)
            llm_spec = None

        if llm_spec is None:
            return deterministic_spec

        merged_spec = self._merge_llm_and_deterministic_specs(llm_spec, deterministic_spec)
        if catalog is not None:
            try:
                merged_spec = resolve_synonyms(q, catalog, merged_spec)
            except Exception as e:
                logger.debug("Synonym resolution skipped after LLM understanding: %s", e)
        return merged_spec

    def _quick_route(
        self,
        q_lower: str,
        db_ctx: Optional[Any] = None,
    ) -> tuple[ExecutionRoute, IntentType, float, Optional[str]]:
        """
        Decide the user's desired interaction mode before any schema grounding or SQL.

        Priority:
        1) greetings / normal conversation
        2) schema/metadata explanation
        3) real database-data requests
        4) conversation fallback for ambiguous/general questions

        Uses the pre-built inverted keyword index in DatabaseContext for
        O(W) semantic-anchor detection (W = words in question) instead of
        scanning every table/column name in the full schema dict.
        """
        normalized = re.sub(r"\s+", " ", q_lower).strip()
        words = set(re.findall(r'[\w\u0600-\u06FF]+', normalized))

        # Greetings: keep backward-compatible OFF_TOPIC intent but route as conversation.
        greeting_phrases = {
            "hi", "hello", "hey", "good morning", "good evening", "thanks",
            "thank you", "who are you", "what can you do",
            "مرحبا", "أهلا", "اهلا", "السلام عليكم", "شكرا", "من انت", "من أنت",
            "ممكن تساعدني",
        }
        clean_no_punct = re.sub(r"[^\w\s\u0600-\u06FF]", " ", q_lower).strip()
        clean_normalized = re.sub(r"\s+", " ", clean_no_punct)

        if any(p == clean_normalized for p in greeting_phrases) or any(clean_normalized.startswith(p + " ") for p in ("hi", "hello", "hey", "مرحبا", "اهلا", "أهلا", "thanks", "thank you")):
            is_ar = any("\u0600" <= c <= "\u06FF" for c in normalized)
            reply = (
                "أهلاً بيك! أنا مساعد قواعد بيانات تفاعلي. اسألني عن البيانات أو الجداول أو أي شيء عام، وأنا أحدد لك الطريقة المناسبة للإجابة."
                if is_ar else
                "Hello! I'm a conversational database assistant. Ask me about your data, schema, or anything general, and I'll choose the right way to help."
            )
            return ExecutionRoute.CONVERSATION, IntentType.OFF_TOPIC, 0.99, reply

        schema_terms = {
            "schema", "columns", "fields", "primary key", "foreign key",
            "relationship", "relationships", "database structure", "database schema",
            "describe table", "show tables", "list tables", "table details",
            "database overview", "describe database",
            "اشرح الجدول", "اشرح الجداول", "اوصف الجداول", "وصف الجداول",
            "اشرح قاعدة البيانات", "اشرح قواعد البيانات", "وصف قاعدة البيانات",
            "وصف قواعد البيانات", "هيكل قاعدة البيانات", "هيكل البيانات",
            "أعمدة", "اعمدة", "علاقة", "علاقات", "المفتاح الأساسي", "المفتاح الأجنبي",
            "مفتاح أساسي", "مفتاح أجنبي",
        }
        schema_cues = {
            "schema", "table", "tables", "column", "columns", "field", "fields",
            "database structure", "database schema", "structure", "relationships",
            "جدول", "جداول", "الجدول", "الجداول", "عمود", "أعمدة", "اعمدة",
            "هيكل", "علاقة", "علاقات", "مفتاح",
        }
        explain_cues = {
            "explain", "describe", "overview", "structure", "what tables", "which tables",
            "اشرح", "شرح", "اوصف", "وصف", "تشرح", "تشرحلي", "اشرحلي", "اوصفلي", "موجودة", "الموجودة", "عندك", "دي", "هذه",
        }
        connected_db_cues = {
            "this database", "the database", "these tables", "current database", "available tables",
            "قاعدة البيانات دي", "قواعد البيانات دي", "قاعدة البيانات الموجودة", "قواعد البيانات الموجودة",
            "الجداول دي", "الجداول الموجودة", "الجداول عندك", "البيانات الموجودة",
            "المتصلة", "الحالية",
        }

        has_explicit_schema = any(term in normalized for term in schema_terms)
        has_schema_pair = bool(words.intersection(schema_cues)) and bool(words.intersection(explain_cues))
        has_connected_schema = any(term in normalized for term in connected_db_cues)
        # O(W) semantic anchor detection via the pre-built inverted keyword index.
        # The index covers table names, column names, and glossary synonyms.
        has_semantic_anchor = False
        if db_ctx is not None and db_ctx.keyword_to_tables:
            fast_matches = db_ctx.match_seed_tables_fast(normalized, max_tables=1)
            has_semantic_anchor = bool(fast_matches)
        elif db_ctx is not None and db_ctx.table_names_set:
            # Fallback: check table_names_set membership (still O(W), not O(T))
            lower_table_names = {t.lower() for t in db_ctx.table_names_set}
            for token in words:
                if token in db_ctx.table_names_set or token in lower_table_names:
                    has_semantic_anchor = True
                    break

        relationship_language = (
            "difference between" in normalized
            or "compare table" in normalized
            or "relationship between" in normalized
            or "الفرق بين" in normalized
            or "قارن بين" in normalized
            or "العلاقة بين" in normalized
        )
        data_cues = {
            "count", "how many", "number of", "sum", "total", "average", "avg",
            "max", "min", "highest", "lowest", "top", "bottom", "most", "least",
            "show", "list", "find", "get", "fetch", "search", "give me", "retrieve",
            "data", "records", "rows", "customers", "students", "orders", "sales",
            "كم", "كام", "كم عدد", "عدد", "اجمالي", "إجمالي", "مجموع", "متوسط",
            "احسب", "هات", "هاتلي", "طلع", "وريني", "اعرض", "بيانات", "سجلات",
            "طلاب", "الطلاب", "عملاء", "العملاء", "طلبات", "مبيعات", "أعلى", "اعلى",
            "أقل", "اقل", "أفضل", "افضل",
        }
        has_data_cue = any(cue in normalized for cue in data_cues)

        business_metric_terms = {
            "revenue", "sales", "profit", "profits", "income", "cost", "costs",
            "expense", "expenses", "margin", "gmv", "arr", "mrr", "kpi", "kpis",
            "الإيرادات", "الايرادات", "إيرادات", "ايرادات", "المبيعات", "مبيعات",
            "الأرباح", "الارباح", "أرباح", "ارباح", "الربح", "ربح",
            "الدخل", "دخل", "التكلفة", "تكلفة", "المصاريف", "مصاريف",
            "الهامش", "هامش",
        }
        has_business_metric = any(term in normalized for term in business_metric_terms)

        if not (has_semantic_anchor and has_data_cue):
            if has_explicit_schema or has_schema_pair or has_connected_schema or ((has_semantic_anchor or "جدول" in normalized or "جداول" in normalized or "table" in normalized) and relationship_language):
                return ExecutionRoute.SCHEMA, IntentType.SCHEMA, 0.97, None

        analysis_signal = classify_analysis_type(normalized) != AnalysisType.UNKNOWN
        database_semantics = has_semantic_anchor or has_business_metric

        if database_semantics and (has_data_cue or analysis_signal or has_business_metric):
            return ExecutionRoute.DATA_QUERY, IntentType.DATABASE, 0.96, None
        if analysis_signal and has_data_cue:
            return ExecutionRoute.DATA_QUERY, IntentType.DATABASE, 0.93, None
        if has_data_cue and db_ctx is not None:
            return ExecutionRoute.DATA_QUERY, IntentType.DATABASE, 0.90, None

        # Out-of-domain, general, or ambiguous requests receive a deterministic database-scoped message
        is_ar = any("\u0600" <= c <= "\u06FF" for c in normalized)
        scoped_reply = (
            "أنا مساعد متخصص في استعلام وتحليل قواعد البيانات. يمكنني مساعدتك في استعراض الجداول، حساب المؤشرات، وكتابة استعلامات SQL. يرجى توجيه سؤالك حول قاعدة البيانات أو البيانات المتصلة."
            if is_ar else
            "I am specialized in database analysis and querying. I can help you explore tables, compute metrics, write SQL queries, or generate data reports. Please ask a question related to your database or data."
        )
        return ExecutionRoute.CONVERSATION, IntentType.OFF_TOPIC, 0.95, scoped_reply

    def _quick_intent(self, q_lower: str, schema: Optional[Dict[str, Any]] = None) -> Optional[tuple[IntentType, str]]:
        """Fast 0-token rule-based intent checker."""
        words = set(re.findall(r'[\w\u0600-\u06FF]+', q_lower))

        # 1. Greetings & general conversational
        greetings = {
            "hi", "hello", "hey", "good morning", "good evening", "who are you",
            "what can you do", "help", "thanks", "thank you", "tell me a joke",
            "مرحبا", "اهلا", "أهلا", "السلام عليكم", "من انت", "من أنت", "شكرا", "صباح الخير", "مساء الخير"
        }
        greeting_words = {"hi", "hello", "hey", "مرحبا", "اهلا", "أهلا", "شكرا", "thanks"}
        if words.intersection(greetings) or words.intersection(greeting_words) or any(q_lower.startswith(g) for g in ("hi", "hello", "hey", "مرحبا", "اهلا", "أهلا")):
            if not words.intersection({"table", "tables", "data", "select", "count", "show", "artist", "customer", "sales", "invoice", "جدول", "جداول", "بيانات", "مبيعات", "عملاء"}):
                is_ar = any("\u0600" <= c <= "\u06FF" for c in q_lower)
                greeting_reply = (
                    "مرحباً بك! أنا مساعد قواعد البيانات الذكي، يمكنني مساعدتك في استخراج البيانات، كتابة استعلامات SQL، وتحليل الأرقام والمؤشرات. كيف يمكنني خدمتك اليوم؟"
                    if is_ar else
                    "Hello! I am your AI Database Assistant. I can help you query, analyze, and visualize your database. How can I help you today?"
                )
                return IntentType.OFF_TOPIC, greeting_reply

        # 2. Explicit schema exploration queries
        schema_kw = {"show tables", "list tables", "describe table", "schema", "database schema", "show schema", "ما هي الجداول", "هيكل البيانات", "عرض الجداول"}
        if any(kw in q_lower for kw in schema_kw):
            return IntentType.SCHEMA, ""

        return None

    def build_spec(
        self,
        question: str,
        db_ctx: Optional[Any] = None,
        conversation_history: str = "",
        catalog: Optional[SchemaCatalog] = None,
    ) -> QuerySpec:
        """
        Build the deterministic compatibility QuerySpec synchronously.

        Accepts a DatabaseContext (db_ctx) instead of a raw schema dict.
        Canonical request paths must call ``build_spec_async`` so configured
        LLM-assisted understanding has the same behavior for every request
        provenance. This method remains only for synchronous compatibility
        adapters.

        Entity/metric/dimension extraction uses the pre-built inverted keyword
        index for O(W) candidate table discovery, then deep-scans only the
        ≤5 candidate tables' columns — never the full schema.
        """
        if not question or not question.strip():
            return QuerySpec(raw_question=question or "", intent=IntentType.OFF_TOPIC)

        q = question.strip()
        q_lower = q.lower()

        routed_spec, should_build_data_spec = self._build_routed_spec(q, q_lower, db_ctx)
        if not should_build_data_spec:
            return routed_spec

        return self._build_deterministic_data_spec(
            question=q,
            q_lower=q_lower,
            route_confidence=routed_spec.route_confidence,
            db_ctx=db_ctx,
            catalog=catalog,
        )
