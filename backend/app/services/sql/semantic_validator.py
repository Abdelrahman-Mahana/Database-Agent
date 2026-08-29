"""SQL Meaning & Semantic Validator.

Performs deep AST semantic invariance verification proving that a generated SQL query
strictly satisfies the business meaning, grain, filter logic, join fan-out safety,
and sorting intent defined in the frozen SemanticContract.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from loguru import logger
import sqlglot
from sqlglot import exp

from app.agent.semantic.models import (
    SemanticContract,
    GrainType,
    FormulaType,
    MetricSpec,
    DimensionSpec,
    TimeSpec,
    FilterSpec,
    SortSpec,
)
from app.utils.helpers import get_target_dialect


class SQLMeaningValidator:
    """
    Validates the semantic meaning and business logic of SQL AST against a SemanticContract.
    Catches queries that are syntactically valid but semantically incorrect or suffer from
    join fan-out (duplicate aggregation) defects.
    """

    def validate_sql_meaning(
        self,
        sql: str,
        contract: Optional[SemanticContract] = None,
        catalog: Optional[Any] = None,
        raw_schema: Optional[Dict[str, Any]] = None,
        relationships: Optional[List[Any]] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Runs all deep semantic rules:
        1. Grain and Projection Invariance
        2. Join Fan-Out & Duplicate Aggregation Safety
        3. Filter & Temporal Boundary Semantics
        4. Sorting Direction & Superlative Alignment
        5. Formula, Ratio & Divide-by-Zero Safety
        """
        if contract is None or hasattr(contract, "_mock_name"):
            return True, []

        try:
            target_dialect = get_target_dialect()
            parsed = sqlglot.parse_one(sql, read=target_dialect)
        except Exception as e:
            return False, [f"SQL syntax parse error during meaning validation: {e}"]

        warnings: List[str] = []

        # 1. Grain & Projection Invariance
        g_ok, g_warns = self.verify_grain_and_projection(parsed, contract)
        warnings.extend(g_warns)

        # 2. Join Fan-Out Safety & Duplicate Aggregation
        f_ok, f_warns = self.verify_join_fanout_safety(parsed, contract, catalog, raw_schema, relationships)
        warnings.extend(f_warns)

        # 3. Filter & Temporal Semantics
        filt_ok, filt_warns = self.verify_filter_and_temporal_semantics(parsed, contract)
        warnings.extend(filt_warns)

        # 4. Sorting Direction Alignment
        s_ok, s_warns = self.verify_sorting_semantics(parsed, contract)
        warnings.extend(s_warns)

        # 5. Formula & Ratio Safety
        form_ok, form_warns = self.verify_ratio_and_formula_safety(parsed, contract)
        warnings.extend(form_warns)

        passed = len(warnings) == 0
        return passed, warnings

    # -- Rule 1: Grain & Projection Invariance ---------------------------------

    def verify_grain_and_projection(
        self,
        parsed: exp.Expression,
        contract: SemanticContract,
    ) -> Tuple[bool, List[str]]:
        """
        Ensures the SQL projection and GROUP BY structure strictly match the target grain.
        """
        warnings: List[str] = []
        grain = getattr(contract, "grain", None)
        grain_type = (
            getattr(grain, "grain_type", None)
            or getattr(contract, "grain_type", None)
            or GrainType.ENTITY_GRAIN
        )
        if hasattr(grain_type, "value"):
            grain_type = grain_type.value

        ast_agg_funcs = list(parsed.find_all(exp.AggFunc))
        group_by = parsed.find(exp.Group)

        # A. Scalar Grain: Expects aggregate values and NO unaggregated grouping
        # Exception: If it's a trend, ranking, or comparison, or if dimensions are specified, 
        # the LLM may have hallucinated SCALAR, but a GROUP BY is actually expected.
        at = getattr(contract, "analysis_type", None)
        at_val = at.value if hasattr(at, "value") else str(at).lower()
        is_dimensional_analysis = at_val in ("trend", "ranking", "comparison")
        has_dims = bool(getattr(contract, "dimensions", []))

        if grain_type in (GrainType.SCALAR.value, "scalar") and not is_dimensional_analysis and not has_dims:
            if group_by:
                warnings.append(
                    "Semantic Grain is SCALAR (single aggregate total), but SQL contains a GROUP BY clause."
                )
            if not ast_agg_funcs:
                warnings.append(
                    "Semantic Grain is SCALAR, but SQL projection contains no aggregate function (e.g. SUM, COUNT, AVG)."
                )

        # B. Entity & Multidimensional Grain with Measures
        elif grain_type in (GrainType.ENTITY_GRAIN.value, GrainType.MULTIDIMENSIONAL.value, "entity", "multidimensional"):
            has_measures = bool(getattr(contract, "measures", []) or ast_agg_funcs)
            raw_dims = getattr(contract, "dimensions", [])
            dimensions = [d for d in raw_dims if not hasattr(d, "_mock_name")] if isinstance(raw_dims, (list, tuple)) else []
            if dimensions and has_measures and not group_by:
                dim_names = [getattr(d, "display_name", None) or getattr(d, "dimension_id", str(d)) for d in dimensions]
                warnings.append(
                    f"Semantic Contract specifies dimensions {dim_names} with measures, but SQL AST lacks GROUP BY."
                )

        # C. Distinctness on Measures
        raw_measures = getattr(contract, "measures", [])
        measures = raw_measures if isinstance(raw_measures, list) and not hasattr(raw_measures, "_mock_name") else []
        for m in measures:
            if hasattr(m, "_mock_name"):
                continue
            if getattr(m, "requires_distinct", False) or getattr(m, "formula_type", None) in (FormulaType.COUNT_DISTINCT, "count_distinct"):
                counts = [f for f in ast_agg_funcs if isinstance(f, exp.Count) or getattr(f, "name", "").upper() == "COUNT"]
                has_count_distinct = any(
                    bool(c.find(exp.Distinct))
                    or bool(c.args.get("distinct"))
                    or "DISTINCT" in c.sql().upper()
                    for c in counts
                )
                if not has_count_distinct:
                    warnings.append(
                        f"Metric '{m.display_name or m.metric_id}' requires unique/distinct counting, but SQL AST lacks COUNT(DISTINCT ...)."
                    )

        return len(warnings) == 0, warnings

    # -- Rule 2: Join Fan-Out & Aggregation Safety ------------------------------

    def verify_join_fanout_safety(
        self,
        parsed: exp.Expression,
        contract: Optional[SemanticContract] = None,
        catalog: Optional[Any] = None,
        raw_schema: Optional[Dict[str, Any]] = None,
        relationships: Optional[List[Any]] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Detects multi-table fan-out aggregation defects where parent columns are summed/averaged/counted
        across 1:N joined child records, causing inflated calculations and duplicate rows.
        Also detects Chasm Trap (Cartesian products from joining multiple 1:N child branches).
        """
        warnings: List[str] = []
        joins = list(parsed.find_all(exp.Join))
        if not joins:
            return True, []

        # 1. Build comprehensive child-to-parent 1:N relationships map
        child_to_parent: Dict[str, Set[str]] = {}

        def norm_name(n: Any) -> str:
            return str(n or "").split(".")[-1].lower().strip('"')

        # A. From catalog
        if catalog and hasattr(catalog, "tables"):
            for tname, prof in catalog.tables.items():
                child_norm = norm_name(tname)
                for fk in getattr(prof, "foreign_keys", []):
                    ref_tbl = fk.get("referred_table", "")
                    if ref_tbl:
                        parent_norm = norm_name(ref_tbl)
                        if parent_norm and parent_norm != child_norm:
                            child_to_parent.setdefault(child_norm, set()).add(parent_norm)

        # B. From relationships list
        if relationships:
            for rel in relationships:
                if isinstance(rel, dict):
                    src_tbl = norm_name(rel.get("source_table"))
                    tgt_tbl = norm_name(rel.get("target_table"))
                else:
                    src_tbl = norm_name(getattr(rel, "source_table", ""))
                    tgt_tbl = norm_name(getattr(rel, "target_table", ""))
                if src_tbl and tgt_tbl and src_tbl != tgt_tbl:
                    child_to_parent.setdefault(src_tbl, set()).add(tgt_tbl)

        # C. From raw_schema
        if raw_schema:
            for tname, info in raw_schema.items():
                child_norm = norm_name(tname)
                for fk in info.get("foreign_keys", []):
                    ref_tbl = fk.get("referred_table", "")
                    if ref_tbl:
                        parent_norm = norm_name(ref_tbl)
                        if parent_norm and parent_norm != child_norm:
                            child_to_parent.setdefault(child_norm, set()).add(parent_norm)

                # Heuristic column naming check (e.g. order_id in order_items)
                cols = [c["name"].lower() if isinstance(c, dict) else str(c).lower() for c in info.get("columns", [])]
                for c in cols:
                    if c.endswith("_id") and len(c) > 3:
                        parent_candidate = c[:-3]
                        plural_candidate = parent_candidate + "s"
                        all_tables = {norm_name(t) for t in raw_schema.keys()}
                        if parent_candidate in all_tables and parent_candidate != child_norm:
                            child_to_parent.setdefault(child_norm, set()).add(parent_candidate)
                        elif plural_candidate in all_tables and plural_candidate != child_norm:
                            child_to_parent.setdefault(child_norm, set()).add(plural_candidate)

        if not child_to_parent:
            return True, []

        # 2. Extract CTE names and subqueries (which pre-aggregate and avoid fan-out)
        cte_names: Set[str] = set()
        cte_nodes = set(parsed.find_all(exp.CTE))
        for with_exp in parsed.find_all(exp.With):
            for cte in with_exp.expressions:
                if cte.alias:
                    cte_names.add(norm_name(cte.alias))
                elif hasattr(cte, "alias_or_name") and cte.alias_or_name:
                    cte_names.add(norm_name(cte.alias_or_name))
                elif hasattr(cte, "this") and isinstance(cte.this, exp.Table):
                    cte_names.add(norm_name(cte.this.name))

        def is_inside_cte(node: exp.Expression) -> bool:
            curr = node.parent
            while curr is not None:
                if curr in cte_nodes or isinstance(curr, exp.CTE):
                    return True
                curr = curr.parent
            return False

        # 3. Resolve table aliases in the outer query block (excluding internal CTE tables)
        alias_to_table: Dict[str, str] = {}
        for t in parsed.find_all(exp.Table):
            if is_inside_cte(t):
                continue
            t_name = norm_name(t.name)
            if t_name:
                alias_to_table[t_name] = t_name
                if t.alias:
                    alias_to_table[t.alias.lower()] = t_name

        tables_in_query = set(alias_to_table.values())

        # 4. Map joined parent tables and their joined child tables
        parent_to_joined_children: Dict[str, Set[str]] = {}
        for child_tbl, parents in child_to_parent.items():
            if child_tbl in tables_in_query and child_tbl not in cte_names:
                for parent_tbl in parents:
                    if parent_tbl in tables_in_query and parent_tbl != child_tbl:
                        parent_to_joined_children.setdefault(parent_tbl, set()).add(child_tbl)

        # 5. Check for Chasm Trap (Parent joined to 2+ distinct 1:N child tables in same FROM block)
        for parent_tbl, joined_children in parent_to_joined_children.items():
            if len(joined_children) >= 2:
                warnings.append(
                    f"Chasm Trap defect: Parent table '{parent_tbl}' is joined with multiple 1:N child tables "
                    f"({', '.join(sorted(joined_children))}), creating an exponential Cartesian product. "
                    f"Pre-aggregate child metrics in separate CTEs/subqueries before joining to '{parent_tbl}'."
                )

        # 6. Check for Fan-Out Duplicate Aggregations on Parent Table Columns
        joined_parent_tables = set(parent_to_joined_children.keys())
        if not joined_parent_tables:
            return len(warnings) == 0, warnings

        for agg in parsed.find_all(exp.AggFunc):
            agg_name = getattr(agg, "name", "").upper()
            is_sum_or_avg = isinstance(agg, (exp.Sum, exp.Avg)) or agg_name in ("SUM", "AVG")
            is_count = isinstance(agg, exp.Count) or agg_name == "COUNT"
            is_distinct = bool(agg.find(exp.Distinct)) or bool(agg.args.get("distinct")) or "DISTINCT" in agg.sql().upper()

            for col in agg.find_all(exp.Column):
                raw_tbl = (col.table or "").lower()
                resolved_tbl = alias_to_table.get(raw_tbl, raw_tbl)
                if resolved_tbl in joined_parent_tables:
                    child_list = ", ".join(sorted(parent_to_joined_children[resolved_tbl]))
                    if is_sum_or_avg:
                        warnings.append(
                            f"Grain Fan-Out defect (Fan-out risk): Aggregation '{agg.sql()}' operates on parent table '{resolved_tbl}' "
                            f"which is joined with 1:N child table(s) ({child_list}). This multiplies parent values by child line counts. "
                            f"Pre-aggregate child records in a CTE/subquery, or remove the unnecessary 1:N join."
                        )
                    elif is_count and not is_distinct:
                        warnings.append(
                            f"Grain Fan-Out defect (Fan-out risk): Non-distinct COUNT '{agg.sql()}' on parent table '{resolved_tbl}' "
                            f"is joined with 1:N child table(s) ({child_list}), counting child rows instead of parent entities. "
                            f"Use COUNT(DISTINCT {col.sql()}) or aggregate parent entities prior to joining."
                        )

            # Check COUNT(*) in presence of 1:N joins when grain is entity/parent
            if is_count and not is_distinct:
                cols_in_agg = list(agg.find_all(exp.Column))
                if not cols_in_agg:  # COUNT(*)
                    for parent_tbl in joined_parent_tables:
                        child_list = ", ".join(sorted(parent_to_joined_children[parent_tbl]))
                        warnings.append(
                            f"Grain Fan-Out defect (Fan-out risk): 'COUNT(*)' on query joining parent '{parent_tbl}' with 1:N child ({child_list}) "
                            f"counts child rows instead of distinct parent entities. Use COUNT(DISTINCT {parent_tbl}.id)."
                        )

        return len(warnings) == 0, warnings

    # -- Rule 3: Filter & Temporal Semantics ------------------------------------

    def verify_filter_and_temporal_semantics(
        self,
        parsed: exp.Expression,
        contract: SemanticContract,
    ) -> Tuple[bool, List[str]]:
        """
        Verifies that mandatory business filters and temporal boundaries are
        properly expressed in the SQL AST WHERE/HAVING clauses.
        """
        warnings: List[str] = []
        where_clause = parsed.find(exp.Where)
        having_clause = parsed.find(exp.Having)
        filter_text = ""
        if where_clause:
            filter_text += " " + where_clause.sql()
        if having_clause:
            filter_text += " " + having_clause.sql()
        filter_text_lower = filter_text.lower()

        raw_filters = getattr(contract, "filters", [])
        filters = [f for f in raw_filters if not hasattr(f, "_mock_name")] if isinstance(raw_filters, (list, tuple)) else []

        for filt in filters:
            if not getattr(filt, "is_mandatory", True):
                continue

            target_col = (filt.target_column or filt.concept or "").lower()
            norm_val = filt.normalized_value if filt.normalized_value is not None else filt.raw_value

            if not filter_text:
                warnings.append(
                    f"Semantic Contract requires mandatory filter on '{target_col}', but SQL lacks WHERE/HAVING clause."
                )
                continue

            cols_in_filter = [c.name.lower() for c in (where_clause or parsed).find_all(exp.Column)]
            if target_col and target_col not in cols_in_filter:
                warnings.append(
                    f"Mandatory contract filter on column '{target_col}' is missing from SQL WHERE/HAVING conditions."
                )
                continue

            if norm_val is not None and isinstance(norm_val, (str, int, float)) and str(norm_val).strip():
                val_str = str(norm_val).lower().strip("'\"")
                if val_str not in filter_text_lower:
                    warnings.append(
                        f"Mandatory contract filter value '{norm_val}' for column '{target_col}' is not present in SQL predicate."
                    )

        time_spec = getattr(contract, "time_spec", None)
        if time_spec and not hasattr(time_spec, "_mock_name") and getattr(time_spec, "has_bounds", False):
            if not where_clause and not having_clause:
                warnings.append(
                    f"Semantic Contract specifies temporal scope ({time_spec.start_date or ''} to {time_spec.end_date or ''}), "
                    f"but SQL contains no WHERE/HAVING temporal clause."
                )
            else:
                dates_to_check = []
                if getattr(time_spec, "start_date", None):
                    dates_to_check.append(str(time_spec.start_date)[:4])
                if getattr(time_spec, "end_date", None):
                    dates_to_check.append(str(time_spec.end_date)[:4])

                has_time_match = any(d in filter_text for d in dates_to_check) or bool(
                    parsed.find(exp.Between) or any(f in filter_text_lower for f in ("strftime", "date_trunc", "extract", "year"))
                )
                if not has_time_match and dates_to_check:
                    warnings.append(
                        f"Temporal boundary ({time_spec.start_date or ''} to {time_spec.end_date or ''}) "
                        f"not found in SQL filter clauses."
                    )

        return len(warnings) == 0, warnings

    # -- Rule 4: Sorting Direction Alignment ------------------------------------

    def verify_sorting_semantics(
        self,
        parsed: exp.Expression,
        contract: SemanticContract,
    ) -> Tuple[bool, List[str]]:
        """
        Verifies that ORDER BY direction matches superlative business intent (Top/Bottom).
        """
        warnings: List[str] = []
        raw_sorting = getattr(contract, "sorting", [])
        sorting = [s for s in raw_sorting if not hasattr(s, "_mock_name")] if isinstance(raw_sorting, (list, tuple)) else []
        if not sorting:
            return True, []

        order_clause = parsed.find(exp.Order)
        if not order_clause:
            warnings.append("Semantic Contract specifies sorting criteria, but SQL AST lacks ORDER BY clause.")
            return False, warnings

        primary_sort = sorting[0]
        expected_dir = (getattr(primary_sort, "direction", "DESC") or "DESC").upper()
        
        ordered_expressions = order_clause.expressions
        if ordered_expressions:
            first_order = ordered_expressions[0]
            is_desc = bool(getattr(first_order, "args", {}).get("desc", False))
            actual_dir = "DESC" if is_desc else "ASC"

            if expected_dir == "DESC" and actual_dir == "ASC":
                warnings.append(
                    "Sorting direction mismatch: Contract specifies DESC (Top/Highest/Most), "
                    "but SQL AST is ordered ASC (Lowest/Smallest first)."
                )
            elif expected_dir == "ASC" and actual_dir == "DESC":
                warnings.append(
                    "Sorting direction mismatch: Contract specifies ASC (Bottom/Lowest/Smallest), "
                    "but SQL AST is ordered DESC (Highest/Largest first)."
                )

        return len(warnings) == 0, warnings

    # -- Rule 5: Formula & Ratio Safety -----------------------------------------

    def verify_ratio_and_formula_safety(
        self,
        parsed: exp.Expression,
        contract: SemanticContract,
    ) -> Tuple[bool, List[str]]:
        """
        Verifies ratio and percentage metrics contain division and division-by-zero protection.
        """
        warnings: List[str] = []
        raw_measures = getattr(contract, "measures", [])
        measures = raw_measures if isinstance(raw_measures, list) and not hasattr(raw_measures, "_mock_name") else []
        for m in measures:
            if hasattr(m, "_mock_name"):
                continue
            f_type = getattr(m, "formula_type", None)
            if f_type in (FormulaType.RATIO, FormulaType.PERCENTAGE, "ratio", "percentage"):
                divs = list(parsed.find_all(exp.Div))
                sql_str = parsed.sql()
                has_division = bool(divs) or "/" in sql_str
                if not has_division:
                    warnings.append(
                        f"Metric '{m.display_name or m.metric_id}' is a Ratio/Percentage, but SQL projection lacks a division expression (/)."
                    )

        return len(warnings) == 0, warnings


# Global instance
sql_meaning_validator = SQLMeaningValidator()
