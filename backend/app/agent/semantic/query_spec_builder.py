"""Unified QuerySpec Builder — Consolidates Intent, Semantic Understanding, and Planning."""
import re
from typing import Any, Dict, Optional, List, Set
from loguru import logger

from app.agent.semantic.models import (
    QuerySpec, IntentType, ExecutionRoute, FilterCondition, SortCondition,
    OutputFormat, UnderstandingConfidence, AnalysisLevel, AnalysisOperation,
    infer_analysis_profile,
)
from app.agent.semantic.models import business_metric_registry
from app.agent.semantic.resolvers import resolve_synonyms
from app.agent.semantic.llm_understanding import LLMQueryUnderstander
from app.agent.semantic.resolvers import ambiguity_resolver, AmbiguityResolution
from app.utils.helpers import classify_analysis_type, AnalysisType, COMPLEX_ANALYSIS_TYPES
from app.models.schema_catalog.models import SchemaCatalog
from app.core.config.settings import settings


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

    def __init__(self, fast_llm=None, llm_understander: Optional[LLMQueryUnderstander] = None):
        self.fast_llm = fast_llm
        if llm_understander is not None:
            self.llm_understander = llm_understander
        else:
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

        words = set(re.findall(r'[a-zA-Z0-9_\u0621-\u064A]+', q_lower))
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

        words = set(re.findall(r'[a-zA-Z0-9_\u0621-\u064A]+', q_lower))
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
                from app.models.schema_catalog.retrieval import HybridCandidateRetriever

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
            analysis_profile = infer_analysis_profile(question, analysis_type=AnalysisType.UNKNOWN)
            spec = QuerySpec(
                raw_question=question,
                intent=intent_type,
                route=route,
                route_confidence=route_confidence,
                off_topic_response=route_reply,
                source="deterministic_router",
                analysis_type=AnalysisType.UNKNOWN,
                analysis_required=analysis_profile["analysis_required"],
                analysis_level=analysis_profile["analysis_level"],
                analysis_goal=analysis_profile["analysis_goal"],
                operations=analysis_profile["operations"],
                comparisons=analysis_profile["comparisons"],
                statistical_methods=analysis_profile["statistical_methods"],
                expected_findings=analysis_profile["expected_findings"],
                constraints=analysis_profile["constraints"],
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
            words = set(re.findall(r'[a-zA-Z0-9_\u0621-\u064A]+', q_lower))

            # Phase 1: Candidate table discovery (zero full-schema scanning)
            _MAX_CANDIDATE_TABLES = 5
            has_business_anchor = False

            explicit_tables = self._explicit_table_references(q_lower, db_ctx)
            if explicit_tables:
                candidate_table_set.update(explicit_tables)

            def add_table_anchor(*bare_names: str) -> None:
                nonlocal has_business_anchor
                for bare_name in bare_names:
                    for table_name in (bare_name, f"public.{bare_name}"):
                        if table_name in schema:
                            candidate_table_set.add(table_name)
                            has_business_anchor = True

            if not explicit_tables:
                if any(term in q_lower for term in ("invoice", "invoices", "bill", "bills", "فاتورة", "فواتير", "الفاتورة", "الفواتير")):
                    add_table_anchor("account_move", "account_move_line", "account_invoice")
                if any(term in q_lower for term in ("sale", "sales", "revenue", "مبيعات", "المبيعات", "إيرادات", "الايرادات", "أرباح", "ارباح")):
                    add_table_anchor("account_move", "account_move_line", "sale_order", "sale_order_line")
                if any(term in q_lower for term in ("customer", "customers", "client", "clients", "partner", "عميل", "عملاء", "العميل", "العملاء", "زبون", "زبائن", "شركاء")):
                    add_table_anchor("res_partner")
                if any(term in q_lower for term in ("company", "companies", "الشركات", "شركات", "شركة")):
                    add_table_anchor("res_company")
                    if "insurance" in q_lower:
                        add_table_anchor("insurance_company")
                if any(term in q_lower for term in ("patient", "patients", "المرضى", "مرضى", "مريض")):
                    add_table_anchor("patient_model", "res_partner")
                if any(term in q_lower for term in ("doctor", "doctors", "الأطباء", "اطباء", "أطباء", "دكتور", "طبيب")):
                    add_table_anchor("doctor_model", "res_partner")
                if any(term in q_lower for term in ("product", "products", "item", "items", "منتج", "منتجات", "أدوية", "دواء", "أصناف")):
                    add_table_anchor("product_template", "product_product")
                if any(term in q_lower for term in ("booking", "bookings", "reservation", "حجز", "حجوزات")):
                    add_table_anchor("booking_model", "reservation_model")
                if any(term in q_lower for term in ("doctor_services", "خدمات الأطباء", "خدمات الاطباء")):
                    add_table_anchor("doctor_services_model")

            if explicit_tables:
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
                candidate_table_set.update(
                    db_ctx.match_seed_tables_fast(q_lower, max_tables=_MAX_CANDIDATE_TABLES)
                )

            if not candidate_table_set and (catalog or getattr(db_ctx, "catalog", None)):
                cat = catalog or db_ctx.catalog
                from app.models.schema_catalog.retrieval import HybridCandidateRetriever
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

        # Resolve decoupled business metrics from Enterprise Metric Registry
        resolved_business_metrics = business_metric_registry.resolve_metrics(
            question, schema=schema, candidate_tables=entities
        )
        for r_metric in resolved_business_metrics:
            if r_metric.source_table and r_metric.source_column:
                full_ref = f"{r_metric.source_table}.{r_metric.source_column}"
                if full_ref not in metrics:
                    metrics.append(full_ref)
                if r_metric.source_table not in entities:
                    entities.append(r_metric.source_table)

        # Detect grouping & breakdown cues (e.g. "حسب الحالة", "per customer", "by status")
        has_grouping_cue = bool(re.search(
            r"\b(by|per|group by|breakdown by|حسب|لكل|توزيع|توزيعة|موزعة|مقسمة|تصنيف)\b",
            q_lower
        ))
        if has_grouping_cue:
            if analysis_type in (AnalysisType.COUNT, AnalysisType.UNKNOWN):
                analysis_type = AnalysisType.AGGREGATION
            # Deep scan for grouping dimension keywords (e.g. state, status, type, category, date, month)
            common_dim_synonyms = {
                "state": "state", "status": "status", "الحالة": "state", "حالة": "state",
                "type": "type", "النوع": "type", "نوع": "type",
                "category": "category", "الفئة": "category", "التصنيف": "category",
                "country": "country", "الدولة": "country", "البلد": "country",
                "city": "city", "المدينة": "city", "المحافظة": "city",
                "month": "month", "الشهر": "month", "شهر": "month",
                "year": "year", "السنة": "year", "سنة": "year",
                "partner": "partner_id", "العميل": "partner_id", "عميل": "partner_id",
            }
            for syn_term, col_target in common_dim_synonyms.items():
                if syn_term in q_lower or f"({col_target})" in q_lower:
                    for t in (entities or list(schema.keys()) if schema else []):
                        if schema and t in schema:
                            col_names = {c["name"].lower(): c["name"] for c in schema[t].get("columns", [])}
                            if col_target in col_names:
                                full_ref = f"{t}.{col_names[col_target]}"
                                if full_ref not in dimensions:
                                    dimensions.append(full_ref)
                                break

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

        # Advanced Time Resolution via TimeResolver
        from app.agent.semantic.resolvers import time_resolver
        resolved_time = time_resolver.resolve_time(question, schema=db_ctx.schema if db_ctx else None, candidate_tables=entities)
        if resolved_time and resolved_time.raw_expression and resolved_time.raw_expression not in time_expressions:
            time_expressions.append(resolved_time.raw_expression)

        filters: List[FilterCondition] = []
        for year in year_matches:
            filters.append(FilterCondition(operator="=", value=year, raw_expression=f"year = {year}"))

        expected_output = OutputFormat.TABLE

        if not dimensions and (analysis_type == AnalysisType.COUNT or (aggregations == ["COUNT"] and not metrics)):
            expected_output = OutputFormat.SCALAR
        elif limit is not None or analysis_type == AnalysisType.RANKING:
            expected_output = OutputFormat.RANKING

        analysis_profile = infer_analysis_profile(question, analysis_type=analysis_type, aggregations=aggregations)
        spec = QuerySpec(
            raw_question=question,
            intent=IntentType.DATABASE,
            route=ExecutionRoute.DATA_QUERY,
            route_confidence=route_confidence,
            analysis_type=analysis_type,
            entities=entities,
            metrics=metrics,
            target_metrics=resolved_business_metrics,
            dimensions=dimensions,
            filters=filters,
            time_expressions=time_expressions,
            aggregations=aggregations,
            sorting=sorting,
            limit=limit,
            expected_output=expected_output,
            analysis_required=analysis_profile["analysis_required"],
            analysis_level=analysis_profile["analysis_level"],
            analysis_goal=analysis_profile["analysis_goal"],
            operations=analysis_profile["operations"],
            comparisons=analysis_profile["comparisons"],
            statistical_methods=analysis_profile["statistical_methods"],
            expected_findings=analysis_profile["expected_findings"],
            constraints=analysis_profile["constraints"],
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

        # Build and freeze the formal Semantic Contract
        schema_dict = db_ctx.schema if db_ctx is not None else None
        spec.to_semantic_contract(schema=schema_dict)

        return spec

    def _merge_llm_and_deterministic_specs(
        self,
        llm_spec: QuerySpec,
        deterministic_spec: QuerySpec,
        schema: Optional[Dict[str, Any]] = None,
        catalog: Optional[SchemaCatalog] = None,
    ) -> QuerySpec:
        from app.agent.semantic.grounding_gate import schema_grounding_gate

        # Strict Schema Grounding: filter out any LLM hallucinated tables/columns
        grounded_llm_entities = schema_grounding_gate.filter_grounded_entities(
            llm_spec.entities, schema=schema, catalog=catalog
        )
        grounded_llm_dimensions = schema_grounding_gate.filter_grounded_dimensions(
            llm_spec.dimensions,
            candidate_tables=grounded_llm_entities or deterministic_spec.entities,
            schema=schema,
            catalog=catalog,
        )

        merged = llm_spec.model_copy(deep=True)
        merged.intent = deterministic_spec.intent
        merged.route = deterministic_spec.route
        merged.route_confidence = deterministic_spec.route_confidence
        merged.off_topic_reason = deterministic_spec.off_topic_reason
        merged.off_topic_response = deterministic_spec.off_topic_response
        if deterministic_spec.expected_output == OutputFormat.SCALAR and deterministic_spec.aggregations == ["COUNT"]:
            merged.entities = deterministic_spec.entities or grounded_llm_entities
            merged.dimensions = deterministic_spec.dimensions
            merged.metrics = deterministic_spec.metrics
        else:
            merged.entities = grounded_llm_entities or deterministic_spec.entities
            merged.metrics = llm_spec.metrics or deterministic_spec.metrics
            merged.dimensions = grounded_llm_dimensions or deterministic_spec.dimensions
        merged.filters = llm_spec.filters or deterministic_spec.filters
        merged.time_expressions = llm_spec.time_expressions or deterministic_spec.time_expressions
        merged.aggregations = llm_spec.aggregations or deterministic_spec.aggregations
        merged.sorting = llm_spec.sorting or deterministic_spec.sorting
        merged.limit = llm_spec.limit if llm_spec.limit is not None else deterministic_spec.limit
        merged.expected_output = llm_spec.expected_output or deterministic_spec.expected_output
        merged.requires_multi_step = llm_spec.requires_multi_step or deterministic_spec.requires_multi_step
        merged.plan_steps = llm_spec.plan_steps or deterministic_spec.plan_steps
        merged.analysis_type = llm_spec.analysis_type if llm_spec.analysis_type != AnalysisType.UNKNOWN else deterministic_spec.analysis_type
        merged.analysis_required = llm_spec.analysis_required if llm_spec.analysis_required is not None else deterministic_spec.analysis_required
        merged.analysis_level = llm_spec.analysis_level if llm_spec.analysis_level != AnalysisLevel.RETRIEVAL else deterministic_spec.analysis_level
        merged.analysis_goal = llm_spec.analysis_goal or deterministic_spec.analysis_goal
        merged.operations = llm_spec.operations or deterministic_spec.operations
        merged.comparisons = llm_spec.comparisons or deterministic_spec.comparisons
        merged.statistical_methods = llm_spec.statistical_methods or deterministic_spec.statistical_methods
        merged.expected_findings = llm_spec.expected_findings or deterministic_spec.expected_findings
        merged.constraints = llm_spec.constraints or deterministic_spec.constraints
        merged.business_goal = llm_spec.business_goal or deterministic_spec.business_goal or llm_spec.analysis_goal
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
            final_spec = deterministic_spec
        else:
            merged_spec = self._merge_llm_and_deterministic_specs(
                llm_spec, deterministic_spec, schema=schema, catalog=catalog
            )
            if catalog is not None:
                try:
                    merged_spec = resolve_synonyms(q, catalog, merged_spec)
                except Exception as e:
                    logger.debug("Synonym resolution skipped after LLM understanding: %s", e)
            final_spec = merged_spec


        enriched = self._enrich_with_conversational_context(final_spec, q, conversation_history, catalog)
        schema_dict = db_ctx.schema if db_ctx is not None else None
        enriched.to_semantic_contract(schema=schema_dict)
        return enriched


    def _enrich_with_conversational_context(
        self,
        spec: QuerySpec,
        question: str,
        conversation_history: str = "",
        catalog: Optional[SchemaCatalog] = None,
    ) -> QuerySpec:
        """Resolve conversational coreferences, pronoun references, and follow-up drilldown filters."""
        if not conversation_history or not conversation_history.strip():
            return spec

        q_lower = question.lower()
        hist_lower = conversation_history.lower()

        # Check for relative / follow-up cues
        follow_up_cues = (
            "منهم", "فيهم", "فيه", "الشهر ده", "الفترة دي", "السنة دي", "العملاء", "أعلى شهر", "أقل شهر",
            "them", "in it", "in that", "that month", "that year", "that period", "highest month", "lowest month"
        )
        is_follow_up = any(cue in q_lower for cue in follow_up_cues)
        if not is_follow_up:
            return spec

        # Extract dates mentioned in previous history (e.g. 2024-07, 2025-02)
        past_dates = re.findall(r"\b(20\d\d[-/](?:0[1-9]|1[0-2]))\b", conversation_history)
        if past_dates:
            target_date = past_dates[-1]  # Most recent date in context
            # If current question specifically mentions "الشهر ده" or "فيهم"
            if any(k in q_lower for k in ("الشهر ده", "فيهم", "منهم", "فيه", "that month", "in it", "أعلى شهر", "تفاصيل")):
                if target_date not in spec.time_expressions:
                    spec.time_expressions.append(target_date)
                if not any(f.value == target_date or str(f.value).startswith(target_date) for f in spec.filters):
                    spec.filters.append(FilterCondition(
                        column="date",
                        operator="LIKE",
                        value=f"{target_date}%",
                        raw_expression=f"month = '{target_date}'"
                    ))

        # Extract previous tables mentioned in history if adding customer drilldown
        if any(c in q_lower for c in ("عملاء", "العملاء", "customer", "customers", "client", "clients")):
            if "res_partner" not in spec.entities and "account_move" in hist_lower:
                if "res_partner" not in spec.entities:
                    spec.entities.append("res_partner")
                if "account_move" not in spec.entities:
                    spec.entities.append("account_move")
            elif "Customer" not in spec.entities and "invoice" in hist_lower:
                if "Customer" not in spec.entities:
                    spec.entities.append("Customer")
                if "Invoice" not in spec.entities:
                    spec.entities.append("Invoice")

        return spec

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
        clean_text = re.sub(r'[؟،؛ـ!?.,:;\'"()\[\]{}`]', ' ', q_lower)
        normalized = re.sub(r"\s+", " ", clean_text).strip()
        words = set(re.findall(r'[a-zA-Z0-9_\u0621-\u064A]+', normalized))

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
                "أهلاً بك! 👋\n\nأنا مساعدك الذكي الخاص بقواعد البيانات. أنا هنا لمساعدتك في استكشاف بياناتك وتحليلها بكل سهولة.\n\nيمكنك أن تسألني بأي طريقة (حتى العامية!) عن أي شيء، مثل:\n- 📊 **تحليل البيانات:** (مثال: *كام حساب عندنا في النظام؟*)\n- 🔍 **فهم الجداول:** (مثال: *إيه الجداول المتاحة في الداتا بيز؟*)\n- 💡 **أسئلة عامة:** وسأقوم بالرد عليك تلقائياً بأفضل طريقة.\n\nكيف يمكنني مساعدتك اليوم؟ 🚀"
                if is_ar else
                "Hello! 👋\n\nI'm your intelligent database assistant. I'm here to help you explore and analyze your data seamlessly.\n\nFeel free to ask me anything in plain English, such as:\n- 📊 **Data Analysis:** (e.g., *How many accounts are in the system?*)\n- 🔍 **Schema Exploration:** (e.g., *What tables do we have in the database?*)\n- 💡 **General Questions:** And I'll automatically choose the best way to answer.\n\nHow can I help you today? 🚀"
            )
            return ExecutionRoute.CONVERSATION, IntentType.OFF_TOPIC, 0.99, reply

        schema_terms = {
            "schema", "columns", "fields", "primary key", "foreign key",
            "relationships between tables", "database structure", "database schema",
            "describe table", "show tables", "list tables", "table details",
            "database overview", "describe database",
            "اشرح الجدول", "اشرح الجداول", "اوصف الجداول", "وصف الجداول",
            "اشرح قاعدة البيانات", "اشرح قواعد البيانات", "وصف قاعدة البيانات",
            "وصف قواعد البيانات", "هيكل قاعدة البيانات", "هيكل البيانات",
            "أعمدة", "اعمدة", "علاقات الجداول", "علاقات بين الجداول", "المفتاح الأساسي", "المفتاح الأجنبي",
            "مفتاح أساسي", "مفتاح أجنبي",
        }
        schema_cues = {
            "schema", "table", "tables", "column", "columns", "field", "fields",
            "database structure", "database schema", "structure", "relationships",
            "database", "data",
            "جدول", "جداول", "الجدول", "الجداول", "عمود", "أعمدة", "اعمدة",
            "هيكل", "علاقة", "علاقات", "مفتاح", "مفاتيح",
            "البيانات", "بيانات", "الداتا", "داتا", "الداتابيز", "داتابيز",
        }
        explain_cues = {
            "explain", "describe", "overview", "structure", "what tables", "which tables",
            "explore", "profile", "details", "inspect", "about", "about table", "about the table",
            "definition", "keys", "foreign keys", "columns", "fields",
            "tell me", "what is", "what are", "show me",
            "اشرح", "شرح", "اوصف", "وصف", "تشرح", "تشرحلي", "اشرحلي", "اوصفلي", "موجودة", "الموجودة", "عندك", "دي", "هذه",
            "استكشف", "استكشاف", "استكشفلي", "استعرض", "استعراض", "تفاصيل", "معلومات", "عن", "بالكامل", "خصائص", "مكونات",
            "فهمني", "فهّمني", "قولي", "قوللي", "وريني", "ورّيني", "عرفني", "كلمني",
            "ايه", "إيه", "ايه هي", "إيه هي", "ايه هو", "إيه هو",
        }
        connected_db_cues = {
            "this database", "the database", "these tables", "current database", "available tables",
            "connected database", "connected to", "your database", "your data",
            "قاعدة البيانات دي", "قواعد البيانات دي", "قاعدة البيانات الموجودة", "قواعد البيانات الموجودة",
            "الجداول دي", "الجداول الموجودة", "الجداول عندك", "البيانات الموجودة",
            "المتصلة", "الحالية",
            "متصل بيها", "متصلة بيها", "متصل بها", "متصلة بها",
            "الداتا دي", "البيانات دي", "اللي عندك", "عندك ايه", "عندك إيه",
            "الداتا عندك", "البيانات عندك", "الداتابيز دي", "الداتابيز عندك",
            "اشرحلي البيانات", "اشرح لي البيانات", "اشرحلي الداتا", "اشرح لي الداتا",
            "فهمني البيانات", "فهمني الداتا", "وريني البيانات", "وريني الداتا",
            "عرفني بالبيانات", "كلمني عن البيانات", "كلمني عن الداتا",
        }

        has_explicit_schema = any(term in normalized for term in schema_terms)
        has_schema_pair = (
            bool(words.intersection(schema_cues)) and bool(words.intersection(explain_cues))
        ) or any(
            phrase in normalized
            for phrase in (
                "what tables", "which tables", "available tables",
                "what columns", "which columns", "available columns",
            )
        )
        has_connected_schema = any(term in normalized for term in connected_db_cues)
        explicit_table_explore = bool(re.search(
            r"\b(ask\s+ai\s+about|explain\s+table|explore\s+table|describe\s+table|table\s+details|profile\s+table|inspect\s+table)\b|"
            r"(?:استكشف|استكشاف|حلل\s+واستكشف|اشرح|اوصف|تفاصيل|معلومات\s+عن|استعراض)\s+(?:جدول|الجدول|جداول|الجداول)\b",
            normalized,
            re.I
        ))
        # O(W) semantic anchor detection via the pre-built inverted keyword index.
        # The index covers table names, column names, and glossary synonyms.
        has_semantic_anchor = False
        if db_ctx is not None and db_ctx.keyword_to_tables:
            fast_matches = db_ctx.match_seed_tables_fast(normalized, max_tables=1)
            has_semantic_anchor = bool(fast_matches)
        elif db_ctx is not None and db_ctx.table_names_set:
            lower_table_names = {t.lower() for t in db_ctx.table_names_set}
            bare_table_names = {t.lower().strip('"').split(".")[-1].strip('"') for t in db_ctx.table_names_set}
            for token in words:
                if token in db_ctx.table_names_set or token in lower_table_names or token in bare_table_names:
                    has_semantic_anchor = True
                    break

        common_business_entities = {
            "customer", "customers", "client", "clients", "invoice", "invoices", "order", "orders",
            "sales", "product", "products", "employee", "employees", "user", "users", "partner", "partners",
            "account", "accounts",
            "عميل", "العميل", "عملاء", "العملاء", "زبون", "زبائن", "فاتورة", "فواتير", "الفاتورة", "الفواتير",
            "طلب", "طلبات", "مبيعات", "المبيعات", "منتج", "منتجات", "المنتجات", "موظف", "موظفين",
            "حساب", "الحساب", "حسابات", "الحسابات",
        }
        if not has_semantic_anchor and bool(words.intersection(common_business_entities)):
            has_semantic_anchor = True

        relationship_language = (
            "difference between" in normalized
            or "compare table" in normalized
            or "relationship between" in normalized
            or "الفرق بين" in normalized
            or "قارن بين" in normalized
            or "العلاقة بين" in normalized
            or "الفرق" in words
            or "بينه وبين" in normalized
            or "بينها وبين" in normalized
            or "ايه الفرق" in normalized
            or "إيه الفرق" in normalized
        )
        data_cues = {
            "count", "how many", "number of", "sum", "total", "average", "avg",
            "max", "min", "highest", "lowest", "top", "bottom", "most", "least",
            "show", "list", "find", "get", "fetch", "search", "give me", "retrieve",
            "who", "which", "data", "records", "rows", "customers", "students", "orders", "sales",
            "analyze", "analysis", "performance", "forecast", "predict", "trend", "correlation", "correlate", "anomaly", "outlier",
            "كم", "كام", "كم عدد", "عدد", "اجمالي", "إجمالي", "مجموع", "متوسط",
            "احسب", "هات", "هاتلي", "طلع", "وريني", "اعرض", "بيانات", "سجلات",
            "طلاب", "الطلاب", "عملاء", "العملاء", "طلبات", "مبيعات", "أعلى", "اعلى",
            "أقل", "اقل", "أفضل", "افضل", "أكثر", "اكثر", "أكبر", "اكبر", "أول", "اول",
            "من هم", "من هو", "ترتيب", "توب",
            "حلل", "تحليل", "أداء", "اداء", "توقع", "تنبؤ", "علاقة", "ارتباط", "شاذة", "قيم شاذة",
        }
        has_data_cue = any(
            (cue in words if " " not in cue else bool(re.search(rf"\b{re.escape(cue)}\b", normalized)))
            for cue in data_cues
        )

        business_metric_terms = {
            "revenue", "sales", "profit", "profits", "income", "cost", "costs",
            "expense", "expenses", "margin", "gmv", "arr", "mrr", "kpi", "kpis",
            "الإيرادات", "الايرادات", "إيرادات", "ايرادات", "المبيعات", "مبيعات",
            "الأرباح", "الارباح", "أرباح", "ارباح", "الربح", "ربح",
            "الدخل", "دخل", "التكلفة", "تكلفة", "المصاريف", "مصاريف",
            "الهامش", "هامش",
        }
        has_business_metric = any(
            (term in words if " " not in term else term in normalized)
            for term in business_metric_terms
        )

        # Composite phrase detection for "explain the data" style questions
        # that combine an explain cue with a database/data reference.
        _explain_data_phrases = (
            "اشرحلي البيانات", "اشرح لي البيانات", "اشرحلي الداتا", "اشرح لي الداتا",
            "اشرحلي الجداول", "اشرح لي الجداول", "اشرح الجداول", "اشرح الجدول",
            "فهمني البيانات", "فهمني الداتا", "فهمني الجداول",
            "وريني البيانات", "وريني الداتا", "وريني الجداول",
            "عرفني بالبيانات", "كلمني عن البيانات", "كلمني عن الداتا",
            "الجداول المتصلة", "الجداول دي", "البيانات المتصلة",
            "عندك ايه في", "عندك إيه في", "ايه اللي عندك", "إيه اللي عندك",
            "explain the data", "explain this database", "describe the data",
            "explain tables", "explain connected tables", "describe tables",
            "tell me about the data", "what data do you have",
            "show me the database", "what's in the database",
        )
        has_explain_data_phrase = any(phrase in normalized for phrase in _explain_data_phrases)

        is_schema_request = (
            has_explicit_schema
            or has_schema_pair
            or has_connected_schema
            or explicit_table_explore
            or has_explain_data_phrase
            or ((has_semantic_anchor or "جدول" in words or "جداول" in words or "table" in words) and relationship_language)
            or ((words.intersection(schema_cues) or has_semantic_anchor) and words.intersection(explain_cues))
        )

        if is_schema_request and not has_business_metric:
            return ExecutionRoute.SCHEMA, IntentType.SCHEMA, 0.98, None

        analysis_signal = (classify_analysis_type(normalized) != AnalysisType.UNKNOWN) or (classify_analysis_type(q_lower) != AnalysisType.UNKNOWN)
        database_semantics = has_semantic_anchor or has_business_metric

        if database_semantics and (has_data_cue or analysis_signal or has_business_metric):
            return ExecutionRoute.DATA_QUERY, IntentType.DATABASE, 0.96, None
        if database_semantics:
            return ExecutionRoute.DATA_QUERY, IntentType.DATABASE, 0.94, None
        if analysis_signal and has_data_cue:
            return ExecutionRoute.DATA_QUERY, IntentType.DATABASE, 0.92, None

        # Out-of-domain, general, or ambiguous requests receive a database-aware reply
        # that includes real context about the connected database instead of a generic message.
        is_ar = any("\u0600" <= c <= "\u06FF" for c in normalized)
        scoped_reply = self._build_database_aware_fallback(is_ar, db_ctx)
        return ExecutionRoute.CONVERSATION, IntentType.OFF_TOPIC, 0.95, scoped_reply

    @staticmethod
    def _build_database_aware_fallback(is_ar: bool, db_ctx: Optional[Any] = None) -> str:
        """Construct a conversational reply that contextually reflects the connected database."""
        table_count = 0
        key_tables = []
        if db_ctx is not None and getattr(db_ctx, "schema", None):
            schema = db_ctx.schema
            table_count = len(schema)
            # Pick up to 4 prominent tables
            all_tables = [t.split(".")[-1] for t in schema.keys()]
            # Filter out technical / lookup tables if possible
            prominent = [t for t in all_tables if not t.startswith("res_") and not t.startswith("ir_")]
            key_tables = (prominent or all_tables)[:4]

        if is_ar:
            if table_count > 0:
                tables_preview = "، ".join(f"`{t}`" for t in key_tables)
                return (
                    f"أنا مساعد ذكي متخصص في تحليل واستعلام قواعد البيانات (قاعدة البيانات المتصلة حالياً "
                    f"تحتوي على **{table_count} جداول** مثل: {tables_preview}).\n\n"
                    f"💡 **كيف يمكنني مساعدتك؟**\n"
                    f"- يمكنك أن تطلب مني: «**اشرحلي الجداول المتصلة بالتفصيل**» لمعرفة هيكل البيانات.\n"
                    f"- أو سؤال عن الأرقام مثل: «**ما هي أعلى المبيعات؟**» أو «**كم عدد السجلات؟**».\n"
                    f"- أو كتابة واستخراج أي استعلام SQL تحتاجه بدقة."
                )
            return (
                "أنا مساعد متخصص في استعلام وتحليل قواعد البيانات. يمكنني مساعدتك في استعراض الجداول، "
                "حساب المؤشرات، واستخراج البيانات وكتابة استعلامات SQL. يرجى توجيه سؤالك حول قاعدة البيانات أو البيانات المتصلة."
            )

        if table_count > 0:
            tables_preview = ", ".join(f"`{t}`" for t in key_tables)
            return (
                f"I am your AI Database Analyst connected to the current database "
                f"(containing **{table_count} tables**, including: {tables_preview}).\n\n"
                f"💡 **How I can help:**\n"
                f"- Ask «**Explain the connected database structure**» for an in-depth breakdown.\n"
                f"- Query analytical metrics, e.g. «**What are the top sales?**» or «**Total count of records**».\n"
                f"- Extract data or write precise SQL queries."
            )
        return (
            "I specialize in database analysis and querying. I can help you explore tables, "
            "compute metrics, write SQL queries, or generate data reports. Please ask a question related to your database or data."
        )

    def _quick_intent(self, q_lower: str, schema: Optional[Dict[str, Any]] = None) -> Optional[tuple[IntentType, str]]:
        """Fast 0-token rule-based intent checker."""
        words = set(re.findall(r'[a-zA-Z0-9_\u0621-\u064A]+', q_lower))

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

        spec = self._build_deterministic_data_spec(
            question=q,
            q_lower=q_lower,
            route_confidence=routed_spec.route_confidence,
            db_ctx=db_ctx,
            catalog=catalog,
        )
        enriched = self._enrich_with_conversational_context(spec, q, conversation_history, catalog)
        schema_dict = db_ctx.schema if db_ctx is not None else None
        enriched.to_semantic_contract(schema=schema_dict)
        return enriched

