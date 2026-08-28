"""Filter Normalization & Grounding Resolver.

Transforms ungrounded filter conditions into strictly typed, schema-grounded FilterSpec objects.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.agent.semantic.contract import FilterSpec, FilterOperator


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
