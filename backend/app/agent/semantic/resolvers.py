from __future__ import annotations
from app.agent.semantic.models import FilterOperator, SemanticGrain, DimensionSpec, FilterSpec, TimeSpec, SemanticContract
from app.models.schema_catalog.models import SchemaCatalog
from dataclasses import dataclass, field
from datetime import datetime, date
from loguru import logger
from typing import Any, Dict, List, Optional, Tuple
from typing import Any, List, Dict, Optional
from typing import Optional
import re

# --- From ambiguity_resolver.py ---
@dataclass
class AmbiguityCandidate:
    name: str
    entity_type: str  # "table" or "column"
    score: float
    reason: str
    description: Optional[str] = None


@dataclass
class AmbiguityResolution:
    is_ambiguous: bool = False
    chosen_candidate: Optional[str] = None
    candidates: List[AmbiguityCandidate] = field(default_factory=list)
    clarification_prompt: Optional[str] = None
    evidence: str = ""


class AmbiguityResolver:
    """Evaluates candidate matches to detect and resolve semantic ambiguity."""

    def resolve_table_ambiguity(
        self,
        question: str,
        candidates: List[Dict[str, Any]],
        threshold_margin: float = 0.15,
    ) -> AmbiguityResolution:
        """
        If top candidates have similarity scores within `threshold_margin`,
        flags ambiguity and builds a clarification prompt.
        """
        if not candidates:
            return AmbiguityResolution(is_ambiguous=False)

        sorted_cands = sorted(candidates, key=lambda c: c.get("score", 0.0), reverse=True)
        amb_candidates = [
            AmbiguityCandidate(
                name=c["name"],
                entity_type="table",
                score=c.get("score", 0.0),
                reason=c.get("reason", "Lexical/Semantic match"),
                description=c.get("description"),
            )
            for c in sorted_cands
        ]

        if len(sorted_cands) < 2:
            return AmbiguityResolution(
                is_ambiguous=False,
                chosen_candidate=sorted_cands[0]["name"],
                candidates=amb_candidates,
                evidence=f"Single dominant candidate '{sorted_cands[0]['name']}'.",
            )

        top_score = sorted_cands[0].get("score", 0.0)
        second_score = sorted_cands[1].get("score", 0.0)

        # Ambiguous if top two candidates have very close relevance scores
        if (top_score - second_score) < threshold_margin and top_score > 0.3:
            cand_names = [c["name"] for c in sorted_cands[:3]]
            options_str = " or ".join(f"'{c}'" for c in cand_names)
            clarification = f"Your question could refer to multiple related tables ({options_str}). Which one would you like to inspect?"

            return AmbiguityResolution(
                is_ambiguous=True,
                chosen_candidate=sorted_cands[0]["name"],  # Default fallback
                candidates=amb_candidates[:3],
                clarification_prompt=clarification,
                evidence=f"Ambiguity detected between '{sorted_cands[0]['name']}' (score {top_score:.2f}) and '{sorted_cands[1]['name']}' (score {second_score:.2f}).",
            )

        return AmbiguityResolution(
            is_ambiguous=False,
            chosen_candidate=sorted_cands[0]["name"],
            candidates=amb_candidates,
            evidence=f"Dominant candidate '{sorted_cands[0]['name']}' selected (score {top_score:.2f} vs {second_score:.2f}).",
        )


# Global singleton instance
ambiguity_resolver = AmbiguityResolver()


# --- From filter_resolver.py ---
class FilterResolver:
    """Resolves and normalizes filter predicates against active database schema."""

    OPERATOR_MAP = {
        "=": FilterOperator.EQ,
        "==": FilterOperator.EQ,
        "equals": FilterOperator.EQ,
        "equal to": FilterOperator.EQ,
        "is": FilterOperator.EQ,
        "يساوي": FilterOperator.EQ,
        "هو": FilterOperator.EQ,
        "!=": FilterOperator.NEQ,
        "<>": FilterOperator.NEQ,
        "not equal": FilterOperator.NEQ,
        "لا يساوي": FilterOperator.NEQ,
        ">": FilterOperator.GT,
        "greater than": FilterOperator.GT,
        "more than": FilterOperator.GT,
        "above": FilterOperator.GT,
        "أكبر من": FilterOperator.GT,
        "اعلى من": FilterOperator.GT,
        ">=": FilterOperator.GTE,
        "greater than or equal": FilterOperator.GTE,
        "at least": FilterOperator.GTE,
        "على الأقل": FilterOperator.GTE,
        "<": FilterOperator.LT,
        "less than": FilterOperator.LT,
        "under": FilterOperator.LT,
        "below": FilterOperator.LT,
        "أقل من": FilterOperator.LT,
        "اصغر من": FilterOperator.LT,
        "<=": FilterOperator.LTE,
        "less than or equal": FilterOperator.LTE,
        "at most": FilterOperator.LTE,
        "على الأكثر": FilterOperator.LTE,
        "in": FilterOperator.IN,
        "من ضمن": FilterOperator.IN,
        "like": FilterOperator.LIKE,
        "contains": FilterOperator.LIKE,
        "يحتوي": FilterOperator.LIKE,
        "between": FilterOperator.BETWEEN,
        "بين": FilterOperator.BETWEEN,
        "is null": FilterOperator.IS_NULL,
        "is not null": FilterOperator.IS_NOT_NULL,
    }

    # Standard geographical & categorical synonym mappings
    VALUE_SYNONYMS = {
        "usa": "USA",
        "united states": "USA",
        "america": "USA",
        "أمريكا": "USA",
        "الولايات المتحدة": "USA",
        "uk": "United Kingdom",
        "united kingdom": "United Kingdom",
        "بريطانيا": "United Kingdom",
        "المملكة المتحدة": "United Kingdom",
        "canada": "Canada",
        "كندا": "Canada",
        "germany": "Germany",
        "ألمانيا": "Germany",
        "المانيا": "Germany",
        "france": "France",
        "فرنسا": "France",
        "brazil": "Brazil",
        "البرازيل": "Brazil",
    }

    def resolve_filters(
        self,
        raw_filters: List[Any],
        schema: Optional[Dict[str, Any]] = None,
        candidate_tables: Optional[List[str]] = None,
    ) -> List[FilterSpec]:
        """
        Normalize a list of raw filter conditions (e.g. from QuerySpec or parser)
        into fully typed, grounded FilterSpec instances.
        """
        results: List[FilterSpec] = []
        for rf in raw_filters:
            if isinstance(rf, dict):
                col_name = rf.get("column")
                op_raw = rf.get("operator", "=")
                val_raw = rf.get("value")
                expr = rf.get("raw_expression", "")
            else:
                col_name = getattr(rf, "column", None)
                op_raw = getattr(rf, "operator", "=")
                val_raw = getattr(rf, "value", None)
                expr = getattr(rf, "raw_expression", "")


            # Normalize operator
            op = self.OPERATOR_MAP.get(str(op_raw).lower().strip(), FilterOperator.EQ)

            # Normalize value
            norm_val, data_type = self._normalize_value(val_raw)

            # Ground target column and table
            target_table, target_column = self._ground_column(col_name, schema, candidate_tables)

            results.append(FilterSpec(
                concept=col_name or target_column or "filter",
                target_table=target_table,
                target_column=target_column or col_name,
                operator=op,
                raw_value=val_raw,
                normalized_value=norm_val,
                data_type=data_type,
                raw_expression=expr or f"{col_name} {op.value} {val_raw}",
            ))

        return results

    def _normalize_value(self, val: Any) -> Tuple[Any, str]:
        """Normalize value types and handle synonym dictionary."""
        if val is None:
            return None, "null"

        if isinstance(val, (int, float)):
            return val, "numeric"

        if isinstance(val, (list, tuple)):
            norm_list = [self._normalize_single_string(str(v)) for v in val]
            return norm_list, "list"

        val_str = str(val).strip().strip("'\"")
        
        # Check numeric conversion
        if re.match(r"^-?\d+$", val_str):
            return int(val_str), "integer"
        if re.match(r"^-?\d+\.\d+$", val_str):
            return float(val_str), "float"

        norm_str = self._normalize_single_string(val_str)
        return norm_str, "text"

    def _normalize_single_string(self, s: str) -> str:
        s_clean = s.strip().lower()
        if s_clean in self.VALUE_SYNONYMS:
            return self.VALUE_SYNONYMS[s_clean]
        return s.strip()

    def _ground_column(
        self,
        col_name: Optional[str],
        schema: Optional[Dict[str, Any]],
        candidate_tables: Optional[List[str]],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Match column name to a schema table and column."""
        if not col_name or not schema:
            return None, col_name

        c_lower = col_name.lower().strip()
        schema_tables = {t.lower(): t for t in schema.keys()}

        # 1. Search candidate tables first
        search_tables = []
        if candidate_tables:
            for ct in candidate_tables:
                if ct.lower() in schema_tables:
                    search_tables.append(schema_tables[ct.lower()])

        if not search_tables:
            search_tables = list(schema.keys())

        for table_name in search_tables:
            table_info = schema.get(table_name) or {}
            columns = []
            if isinstance(table_info, dict):
                columns = [col.get("name") if isinstance(col, dict) else str(col) for col in table_info.get("columns", [])]
            elif isinstance(table_info, list):
                columns = [c.get("name") if isinstance(c, dict) else str(c) for c in table_info]

            for c in columns:
                if c.lower() == c_lower or c_lower in c.lower():
                    return table_name, c

        return None, col_name


# Global singleton
filter_resolver = FilterResolver()


# --- From time_resolver.py ---
class TimeResolver:
    """Deterministic, rule-based resolver for temporal expressions."""

    # Arabic month names mapping
    AR_MONTHS = {
        "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "مايو": 5, "يونيو": 6,
        "يوليو": 7, "أغسطس": 8, "اغسطس": 8, "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10,
        "نوفمبر": 11, "ديسمبر": 12,
    }

    EN_MONTHS = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
        "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    CANDIDATE_DATE_COLUMNS = [
        "invoicedate", "invoice_date", "orderdate", "order_date",
        "created_at", "create_date", "date", "timestamp", "hiredate", "hire_date",
        "birthdate", "birth_date", "payment_date", "transaction_date",
    ]

    def __init__(self, reference_date: Optional[date] = None):
        # Default reference date for relative resolution (fallback to fixed demo/recent or today)
        self.reference_date = reference_date or date.today()

    def resolve_time(
        self,
        text: str,
        schema: Optional[Dict[str, Any]] = None,
        candidate_tables: Optional[List[str]] = None,
    ) -> Optional[TimeSpec]:
        """
        Extract and normalize temporal bounds and grains from user question.
        """
        if not text:
            return None

        text_clean = text.strip()
        text_lower = text_clean.lower()

        # 1. Detect Quarters e.g. "Q1 2023", "الربع الأول من 2022"
        quarter_match = re.search(
            r"(?:q([1-4])|الربع\s+(الأول|الثاني|الثالث|الرابع))\s*(?:من|of|in)?\s*(19\d\d|20\d\d)?",
            text_clean, re.IGNORECASE
        )
        if quarter_match:
            q_num = None
            if quarter_match.group(1):
                q_num = int(quarter_match.group(1))
            elif quarter_match.group(2):
                ar_q = quarter_match.group(2)
                q_map = {"الأول": 1, "الثاني": 2, "الثالث": 3, "الرابع": 4}
                q_num = q_map.get(ar_q, 1)

            year_val = int(quarter_match.group(3)) if quarter_match.group(3) else self.reference_date.year
            start_month = (q_num - 1) * 3 + 1
            end_month = start_month + 2
            end_days = {3: 31, 6: 30, 9: 30, 12: 31}
            time_col, source_table = self._find_time_column(schema, candidate_tables)
            return TimeSpec(
                time_column=time_col,
                source_table=source_table,
                start_date=f"{year_val}-{start_month:02d}-01",
                end_date=f"{year_val}-{end_month:02d}-{end_days[end_month]:02d}",
                granularity="QUARTER",
                raw_expression=quarter_match.group(0),
                is_relative=False,
            )

        # 2. Detect Year Range e.g. "between 2009 and 2011" or "بين 2009 و 2011" or "من 2010 إلى 2013"
        range_match = re.search(
            r"(?:between|from|بين|من)\s+(?:عام|سنة)?\s*(19\d\d|20\d\d)\s*(?:and|to|و|إلى|الي)\s*(?:عام|سنة)?\s*(19\d\d|20\d\d)",
            text_clean, re.IGNORECASE
        )
        if range_match:
            y1, y2 = int(range_match.group(1)), int(range_match.group(2))
            start_year, end_year = min(y1, y2), max(y1, y2)
            time_col, source_table = self._find_time_column(schema, candidate_tables)
            return TimeSpec(
                time_column=time_col,
                source_table=source_table,
                start_date=f"{start_year}-01-01",
                end_date=f"{end_year}-12-31",
                granularity=self._detect_granularity(text_lower),
                raw_expression=range_match.group(0),
                is_relative=False,
            )

        # 3. Detect Specific Single Year e.g. "in 2012", "خلال عام 2010", "سنة 2023", "عام 2020", "2013"
        year_match = re.search(
            r"(?:in|during|for|for the year|عام|سنة|خلال عام|خلال سنة|في عام|في سنة)\s+(19\d\d|20\d\d)\b",
            text_clean, re.IGNORECASE
        )
        if not year_match:
            # Standalone year with word boundary
            standalone = re.findall(r"\b(19\d\d|20\d\d)\b", text_clean)
            if standalone:
                year_val = int(standalone[0])
                time_col, source_table = self._find_time_column(schema, candidate_tables)
                return TimeSpec(
                    time_column=time_col,
                    source_table=source_table,
                    start_date=f"{year_val}-01-01",
                    end_date=f"{year_val}-12-31",
                    granularity=self._detect_granularity(text_lower),
                    raw_expression=f"year {year_val}",
                    is_relative=False,
                )
        else:
            year_val = int(year_match.group(1))
            time_col, source_table = self._find_time_column(schema, candidate_tables)
            return TimeSpec(
                time_column=time_col,
                source_table=source_table,
                start_date=f"{year_val}-01-01",
                end_date=f"{year_val}-12-31",
                granularity=self._detect_granularity(text_lower),
                raw_expression=year_match.group(0),
                is_relative=False,
            )

        # 4. Detect Relative Periods (last year, last month, الشهر الماضي, السنة الماضية)

        if any(term in text_lower for term in ("last year", "previous year", "السنة الماضية", "العام الماضي")):
            target_year = self.reference_date.year - 1
            time_col, source_table = self._find_time_column(schema, candidate_tables)
            return TimeSpec(
                time_column=time_col,
                source_table=source_table,
                start_date=f"{target_year}-01-01",
                end_date=f"{target_year}-12-31",
                granularity=self._detect_granularity(text_lower),
                raw_expression="last year",
                is_relative=True,
            )

        if any(term in text_lower for term in ("this year", "current year", "هذه السنة", "هذا العام")):
            target_year = self.reference_date.year
            time_col, source_table = self._find_time_column(schema, candidate_tables)
            return TimeSpec(
                time_column=time_col,
                source_table=source_table,
                start_date=f"{target_year}-01-01",
                end_date=f"{target_year}-12-31",
                granularity=self._detect_granularity(text_lower),
                raw_expression="this year",
                is_relative=True,
            )

        # 5. Detect Temporal Grain only (e.g. "monthly trend", "شهريا", "over time", "سنويا")
        grain = self._detect_granularity(text_lower)
        if grain:
            time_col, source_table = self._find_time_column(schema, candidate_tables)
            return TimeSpec(
                time_column=time_col,
                source_table=source_table,
                granularity=grain,
                raw_expression=f"grain: {grain}",
                is_relative=False,
            )

        return None

    def _detect_granularity(self, text_lower: str) -> Optional[str]:
        """Extract explicit grouping temporal grain if mentioned."""
        if re.search(r"\b(monthly|per month|by month|شهرياً|شهريا|حسب الشهر|لكل شهر|عبر الشهور)\b", text_lower):
            return "MONTH"
        if re.search(r"\b(yearly|per year|by year|annually|سنوياً|سنويا|حسب السنة|لكل سنة|عبر السنوات)\b", text_lower):
            return "YEAR"
        if re.search(r"\b(quarterly|per quarter|by quarter|ربع سنوي|حسب الربع)\b", text_lower):
            return "QUARTER"
        if re.search(r"\b(daily|per day|by day|يومياً|يوميا|حسب اليوم|يومي)\b", text_lower):
            return "DAY"
        if re.search(r"\b(over time|trend|evolution|across time|بمرور الوقت|عبر الزمن|تطور)\b", text_lower):
            return "MONTH"
        return None

    def _find_time_column(
        self,
        schema: Optional[Dict[str, Any]],
        candidate_tables: Optional[List[str]],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Identify candidate time column in the active schema."""
        if not schema:
            return "InvoiceDate", "Invoice"

        schema_tables = {t.lower(): t for t in schema.keys()}

        # 1. Check candidate tables first
        search_tables = []
        if candidate_tables:
            for ct in candidate_tables:
                if ct.lower() in schema_tables:
                    search_tables.append(schema_tables[ct.lower()])

        if not search_tables:
            search_tables = list(schema.keys())

        for table_name in search_tables:
            table_info = schema.get(table_name) or {}
            columns = []
            if isinstance(table_info, dict):
                columns = [col.get("name") if isinstance(col, dict) else str(col) for col in table_info.get("columns", [])]
            elif isinstance(table_info, list):
                columns = [c.get("name") if isinstance(c, dict) else str(c) for c in table_info]

            col_map = {c.lower(): c for c in columns}
            for candidate_col in self.CANDIDATE_DATE_COLUMNS:
                if candidate_col in col_map:
                    return col_map[candidate_col], table_name

        return None, None


# Global singleton
time_resolver = TimeResolver()


# --- From synonyms.py ---
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
