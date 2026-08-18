"""SQL Validator for safety rules, dialect transpilation, dry-run execution checks,
identifier grounding, join-path verification, and QuerySpec semantic alignment.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp
from typing import Any, Dict, List, Optional, Tuple, Set
from sqlalchemy.orm import Session
from loguru import logger

from app.services.sql_service import SQLExecutor
from app.utils.validator import validate_sql, sanitize_query, transpile_sql_to_dialect, get_target_dialect
from app.utils.text_processor import extract_sql, normalize_sql


class SQLValidator:
    """Performs safety checks, syntax validation, dialect transpilation, execution checks,
    AST identifier grounding, join-path verification, and QuerySpec alignment.
    """

    def __init__(self):
        self.sql_executor = SQLExecutor()

    def sanitize_and_extract(self, raw_response: str) -> str:
        """Extract SQL from markdown fences and sanitize it."""
        return sanitize_query(extract_sql(raw_response))

    def transpile(self, sql: str, target_dialect: str | None = None) -> str:
        """Transpile SQL query to target database dialect."""
        dialect = target_dialect or get_target_dialect()
        return transpile_sql_to_dialect(sql, dialect)

    def validate_safety(self, sql: str) -> Dict[str, Any]:
        """Run safety validation rules on SQL statement."""
        return validate_sql(sql)

    def validate_execution(self, sql: str, db: Optional[Session] = None) -> Tuple[bool, Optional[str]]:
        """
        Perform candidate validation using SQL AST analysis and dialect-aware EXPLAIN.
        Validates syntax, safety, and schema binding without live query execution.
        """
        safety = self.validate_safety(sql)
        if not safety.get("valid", False):
            return False, safety.get("reason", "AST validation failed")

        if db is not None:
            return self.sql_executor.explain(sql, db)

        return True, None

    # -- Control 1: Identifier Grounding (with CTE & Table Alias Tracking) -----

    def verify_sql_identifiers(
        self,
        sql: str,
        catalog: Optional[Any] = None,
        raw_schema: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Ensures every table and column mentioned in the SQL AST resolves to known catalog objects,
        properly accounting for CTEs (WITH clauses), subquery aliases, and derived columns.
        Cuts hallucinated identifiers.
        """
        warnings: List[str] = []
        try:
            target_dialect = get_target_dialect()
            parsed = sqlglot.parse_one(sql, read=target_dialect)
        except Exception as e:
            return False, [f"SQL syntax parse error: {e}"]

        known_tables: Set[str] = set()
        known_columns_by_table: Dict[str, Set[str]] = {}

        if catalog is not None and hasattr(catalog, "tables"):
            for tname, prof in catalog.tables.items():
                short_name = tname.split(".")[-1].lower()
                known_tables.add(short_name)
                known_tables.add(tname.lower())
                cols = {c.name.lower() for c in prof.columns}
                known_columns_by_table[short_name] = cols
                known_columns_by_table[tname.lower()] = cols
        elif raw_schema:
            for tname, info in raw_schema.items():
                short_name = tname.split(".")[-1].lower()
                known_tables.add(short_name)
                known_tables.add(tname.lower())
                cols = {c["name"].lower() for c in info.get("columns", [])}
                known_columns_by_table[short_name] = cols
                known_columns_by_table[tname.lower()] = cols

        if not known_tables:
            return True, []

        all_known_cols = {col for cols in known_columns_by_table.values() for col in cols}

        # 1. Discover CTE definitions and derived table aliases
        cte_names: Set[str] = set()
        for cte in parsed.find_all(exp.CTE):
            cte_alias = cte.alias_or_name
            if cte_alias:
                cte_names.add(cte_alias.lower())

        table_alias_map: Dict[str, str] = {}
        for table_exp in parsed.find_all(exp.Table):
            t_name = table_exp.name.lower() if table_exp.name else ""
            t_alias = table_exp.alias.lower() if table_exp.alias else ""
            if t_alias and t_name:
                table_alias_map[t_alias] = t_name

        for subquery in parsed.find_all(exp.Subquery):
            sub_alias = subquery.alias.lower() if subquery.alias else ""
            if sub_alias:
                cte_names.add(sub_alias)

        # Collect derived column aliases (e.g., SELECT count(*) AS cnt)
        derived_column_aliases: Set[str] = set()
        for alias_exp in parsed.find_all(exp.Alias):
            if alias_exp.alias:
                derived_column_aliases.add(alias_exp.alias.lower())

        # 2. Check Tables
        for table_exp in parsed.find_all(exp.Table):
            t_name = table_exp.name.lower()
            if not t_name:
                continue
            if t_name in cte_names:
                continue

            short_name = t_name.split(".")[-1]
            if t_name not in known_tables and short_name not in known_tables:
                warnings.append(f"Unrecognized table '{table_exp.name}' referenced in query.")

        # 3. Check Columns
        for col_exp in parsed.find_all(exp.Column):
            c_name = col_exp.name.lower()
            if not c_name or c_name == "*":
                continue
            if c_name in derived_column_aliases:
                continue

            raw_t_name = col_exp.table.lower() if col_exp.table else None
            t_name = table_alias_map.get(raw_t_name, raw_t_name) if raw_t_name else None

            if t_name:
                if t_name in cte_names:
                    # Columns from CTEs/subqueries are derived
                    continue
                short_t = t_name.split(".")[-1]
                target_table = t_name if t_name in known_columns_by_table else short_t
                if target_table in known_columns_by_table:
                    if c_name not in known_columns_by_table[target_table]:
                        warnings.append(f"Column '{col_exp.name}' does not exist in table '{t_name}'.")
            else:
                if c_name not in all_known_cols and c_name not in derived_column_aliases:
                    warnings.append(f"Column '{col_exp.name}' not found in any database table.")

        passed = len(warnings) == 0
        return passed, warnings

    # -- Control 2: Join-Key Verification --------------------------------------

    def verify_sql_joins(
        self,
        sql: str,
        catalog: Optional[Any] = None,
        relationships: Optional[List[Any]] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Ensures every JOIN's ON key is an exact catalog relationship edge.

        Table-level connectivity is insufficient: if ``orders`` and
        ``customers`` are related, ``orders.order_id = customers.customer_id``
        is still invalid.  This verifier resolves table aliases and requires
        at least one ON equality for each JOIN to match an FK column pair
        (in either direction). Extra predicates such as tenant filters remain
        allowed alongside the FK predicate.
        """
        warnings: List[str] = []
        try:
            target_dialect = get_target_dialect()
            parsed = sqlglot.parse_one(sql, read=target_dialect)
        except Exception:
            return True, []

        joins = list(parsed.find_all(exp.Join))
        if not joins:
            return True, []

        # Directed, column-level edges, normalized as
        # (left_table, left_column, right_table, right_column).  Each FK is
        # stored in both directions so SQL may put either side on the left.
        known_edges: Set[Tuple[str, str, str, str]] = set()

        def norm_table(name: Any) -> str:
            return str(name or "").split(".")[-1].lower()

        def add_edge(source_table: Any, source_column: Any, target_table: Any, target_column: Any) -> None:
            source_table, target_table = norm_table(source_table), norm_table(target_table)
            source_column, target_column = str(source_column or "").lower(), str(target_column or "").lower()
            if source_table and target_table and source_column and target_column:
                known_edges.add((source_table, source_column, target_table, target_column))
                known_edges.add((target_table, target_column, source_table, source_column))

        if relationships:
            for rel in relationships:
                if isinstance(rel, dict):
                    add_edge(rel.get("source_table"), rel.get("source_column"), rel.get("target_table"), rel.get("target_column"))
                else:
                    add_edge(
                        getattr(rel, "source_table", ""), getattr(rel, "source_column", ""),
                        getattr(rel, "target_table", ""), getattr(rel, "target_column", ""),
                    )
        elif catalog and hasattr(catalog, "tables"):
            for tname, prof in catalog.tables.items():
                for fk in prof.foreign_keys:
                    constrained = fk.get("constrained_columns", [])
                    referred = fk.get("referred_columns", [])
                    for source_col, target_col in zip(constrained, referred):
                        add_edge(tname, source_col, fk.get("referred_table"), target_col)

        if not known_edges:
            return True, []

        # Alias resolution is mandatory for checking `o.customer_id = c.id`.
        alias_to_table: Dict[str, str] = {}
        for table in parsed.find_all(exp.Table):
            table_name = norm_table(table.name)
            if table_name:
                alias_to_table[table_name] = table_name
                if table.alias:
                    alias_to_table[table.alias.lower()] = table_name

        for join in joins:
            join_table_exp = join.this
            join_tbl = norm_table(join_table_exp.name) if isinstance(join_table_exp, exp.Table) else ""
            if not join_tbl:
                continue

            on_clause = join.args.get("on")
            if on_clause is None:
                warnings.append(f"JOIN on table '{join_tbl}' has no ON predicate matching a catalog foreign key.")
                continue

            fk_key_matched = False
            for equality in on_clause.find_all(exp.EQ):
                left, right = equality.left, equality.right
                if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
                    continue
                left_table = alias_to_table.get((left.table or "").lower(), norm_table(left.table))
                right_table = alias_to_table.get((right.table or "").lower(), norm_table(right.table))
                edge = (left_table, left.name.lower(), right_table, right.name.lower())
                # Only an equality involving the newly joined table can prove
                # that JOIN's relationship; unrelated predicates in ON cannot.
                if join_tbl in (left_table, right_table) and edge in known_edges:
                    fk_key_matched = True
                    break

            if not fk_key_matched:
                warnings.append(
                    f"JOIN on table '{join_tbl}' has no ON key that matches a catalog foreign key relationship."
                )

        passed = len(warnings) == 0
        return passed, warnings

    # -- Control 3: QuerySpec-to-AST Semantic Alignment -----------------------

    def verify_query_spec_alignment(
        self,
        sql: str,
        query_spec: Optional[Any] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Compares requested metrics, dimensions, aggregations, filters, sorting,
        and limits from QuerySpec against the SQL AST.
        """
        if query_spec is None:
            return True, []

        warnings: List[str] = []
        try:
            target_dialect = get_target_dialect()
            parsed = sqlglot.parse_one(sql, read=target_dialect)
        except Exception:
            return True, []

        # 1. Check Aggregations / Metrics
        aggregations = [a.upper() for a in getattr(query_spec, "aggregations", []) or []]
        metrics = getattr(query_spec, "metrics", []) or []

        ast_agg_funcs = list(parsed.find_all(exp.AggFunc))
        has_agg_req = len(metrics) > 0 or len(aggregations) > 0

        if has_agg_req and not ast_agg_funcs and not parsed.find(exp.Group):
            warnings.append("QuerySpec specifies metrics/aggregations, but SQL AST contains no aggregate function or GROUP BY.")

        # Check specific aggregations
        if "COUNT" in aggregations and not any(isinstance(f, exp.Count) for f in ast_agg_funcs):
            # Check anonymous func count
            if not any(getattr(f, "name", "").upper() == "COUNT" for f in ast_agg_funcs):
                warnings.append("QuerySpec requested COUNT aggregation, but SQL AST lacks COUNT().")

        # 2. Check Dimensions & GROUP BY
        dimensions = getattr(query_spec, "dimensions", []) or []
        group_by = parsed.find(exp.Group)
        if dimensions and ast_agg_funcs and not group_by:
            warnings.append(f"QuerySpec specifies dimensions {dimensions} with metrics, but SQL AST lacks GROUP BY.")

        # 3. Check Filters (WHERE / HAVING)
        filters = getattr(query_spec, "filters", []) or []
        where_clause = parsed.find(exp.Where)
        having_clause = parsed.find(exp.Having)
        if filters and not where_clause and not having_clause:
            warnings.append("QuerySpec specifies filter conditions, but SQL AST lacks WHERE or HAVING clause.")

        # 4. Check Ordering & Limits
        sorting = getattr(query_spec, "sorting", []) or []
        order_clause = parsed.find(exp.Order)
        if sorting and not order_clause:
            warnings.append("QuerySpec specifies sorting criteria, but SQL AST lacks ORDER BY clause.")

        limit_val = getattr(query_spec, "limit", None)
        limit_clause = parsed.find(exp.Limit) or parsed.args.get("limit")
        if limit_val is not None and not limit_clause:
            warnings.append(f"QuerySpec specifies limit={limit_val}, but SQL AST lacks LIMIT clause.")

        passed = len(warnings) == 0
        return passed, warnings

    def validate_sql_correctness(
        self,
        sql: str,
        catalog: Optional[Any] = None,
        raw_schema: Optional[Dict[str, Any]] = None,
        query_spec: Optional[Any] = None,
        relationships: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Runs full suite of AST safety, identifier grounding, join verification, and QuerySpec alignment."""
        safety = self.validate_safety(sql)
        id_valid, id_warn = self.verify_sql_identifiers(sql, catalog=catalog, raw_schema=raw_schema)
        join_valid, join_warn = self.verify_sql_joins(sql, catalog=catalog, relationships=relationships)
        align_valid, align_warn = self.verify_query_spec_alignment(sql, query_spec=query_spec)

        all_warnings = id_warn + join_warn + align_warn
        is_all_valid = safety.get("valid", False) and id_valid and join_valid and align_valid

        return {
            "valid": is_all_valid,
            "safety_valid": safety.get("valid", False),
            "identifiers_valid": id_valid,
            "joins_valid": join_valid,
            "alignment_valid": align_valid,
            "warnings": all_warnings,
            "safety_reason": safety.get("reason", "OK"),
        }


# Global instance
sql_validator = SQLValidator()
