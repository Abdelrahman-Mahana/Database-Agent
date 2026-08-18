"""Deterministic Semantic Query Parser."""
import re
from typing import Any, Dict, List, Optional
from app.semantic.models import (
    QueryUnderstanding,
    FilterCondition,
    SortCondition,
    OutputFormat,
)
from app.utils.text_processor import classify_analysis_type, AnalysisType


class SemanticQueryParser:
    """
    Deterministic rule-based parser for extracting structured semantic intent
    from natural language questions using rules and database schema metadata.
    """

    def parse(self, question: str, schema: Optional[Dict[str, Any]] = None) -> QueryUnderstanding:
        """
        Parse a natural language question into a QueryUnderstanding object.

        Args:
            question: Natural language user query.
            schema: Discovered database schema dict (from SchemaService).

        Returns:
            QueryUnderstanding: Structured semantic query representation.
        """
        if not question or not question.strip():
            return QueryUnderstanding(raw_question=question or "")

        q = question.strip()
        q_lower = q.lower()

        # 1. Classify Analysis Type
        analysis_type = classify_analysis_type(q)

        # 2. Extract Entities, Metrics, Dimensions from Schema Metadata
        entities: List[str] = []
        metrics: List[str] = []
        dimensions: List[str] = []

        if schema:
            words = set(re.findall(r'[\w\u0600-\u06FF]+', q_lower))
            if len(schema) > 30:
                # Fast path for large schemas: token-indexed filtering
                candidate_tables = [
                    t for t in schema.keys()
                    if t.lower() in words or t.lower().rstrip("s") in words or t.lower() in q_lower
                ]
                for t in candidate_tables:
                    entities.append(t)
                    table_info = schema.get(t, {})
                    for col in table_info.get("columns", []):
                        col_name = col["name"]
                        c_lower = col_name.lower()
                        if (c_lower in words or c_lower in q_lower) and c_lower not in ("id", "created_at"):
                            col_type = col.get("type", "").upper()
                            is_numeric = any(num_t in col_type for num_t in ("INT", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL", "REAL"))
                            full_ref = f"{t}.{col_name}"
                            if is_numeric:
                                if full_ref not in metrics:
                                    metrics.append(full_ref)
                            else:
                                if full_ref not in dimensions:
                                    dimensions.append(full_ref)
            else:
                for table_name, table_info in schema.items():
                    # Match table name or singular form
                    t_lower = table_name.lower()
                    t_singular = t_lower.rstrip("s")
                    if t_lower in q_lower or (len(t_singular) > 3 and t_singular in q_lower):
                        entities.append(table_name)

                    for col in table_info.get("columns", []):
                        col_name = col["name"]
                        c_lower = col_name.lower()
                        if c_lower in q_lower and c_lower not in ("id", "created_at"):
                            col_type = col.get("type", "").upper()
                            is_numeric = any(num_t in col_type for num_t in ("INT", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL", "REAL"))
                            full_ref = f"{table_name}.{col_name}"
                            if is_numeric:
                                if full_ref not in metrics:
                                    metrics.append(full_ref)
                            else:
                                if full_ref not in dimensions:
                                    dimensions.append(full_ref)

        # 3. Extract Aggregations
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

        # 4. Extract Limit & Sorting
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

        # 5. Extract Time Expressions
        time_expressions: List[str] = []
        year_matches = re.findall(r"\b(19\d\d|20\d\d)\b", q)
        time_expressions.extend(year_matches)

        trend_phrases = ["over time", "year over year", "month over month", "by year", "by month", "بمرور الوقت", "عبر الزمن", "حسب السنة", "حسب الشهر"]
        for phrase in trend_phrases:
            if phrase in q_lower:
                time_expressions.append(phrase)

        # 6. Extract Simple Filters
        filters: List[FilterCondition] = []
        for year in year_matches:
            filters.append(FilterCondition(operator="=", value=year, raw_expression=f"year = {year}"))

        # 7. Determine Expected Output Format
        expected_output = OutputFormat.TABLE
        if analysis_type == AnalysisType.COUNT or (aggregations == ["COUNT"] and not dimensions):
            expected_output = OutputFormat.SCALAR
        elif limit is not None or analysis_type == AnalysisType.RANKING:
            expected_output = OutputFormat.RANKING
        elif analysis_type == AnalysisType.TREND:
            expected_output = OutputFormat.TIME_SERIES
        elif analysis_type == AnalysisType.LOOKUP and len(entities) == 1 and not metrics:
            expected_output = OutputFormat.LIST

        # 8. Compute Confidence Score
        confidence = 0.2
        if entities and (metrics or aggregations or dimensions):
            confidence = 0.95
        elif entities:
            confidence = 0.8
        elif analysis_type != AnalysisType.UNKNOWN or aggregations:
            confidence = 0.6

        return QueryUnderstanding(
            raw_question=q,
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
            confidence=confidence,
            source="regex",
        )
