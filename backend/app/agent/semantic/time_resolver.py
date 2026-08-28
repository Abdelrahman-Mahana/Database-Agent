"""Time Semantics Resolver.

Resolves relative and absolute temporal natural language expressions (English and Arabic)
into a strictly normalized TimeSpec with ISO date boundaries, temporal grain,
and candidate schema time columns.
"""
from __future__ import annotations

import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from app.agent.semantic.contract import TimeSpec


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
