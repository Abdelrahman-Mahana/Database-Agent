"""Query cost guard — multi-layered static and dynamic safety defense.

Combines:
1. AST structure analysis (sqlglot) to extract tables, WHERE filters, LIMITs, Cartesian products, and aggregates.
2. Catalog table cardinality profiling to calculate baseline scan volume.
3. Database-side EXPLAIN cost estimation (PostgreSQL, MySQL, SQLite) to detect unindexed full table scans and low-selectivity queries.
4. Fail-closed policies for high-risk Cartesian products and massive unindexed scans to protect production databases.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import sqlglot
from sqlglot import exp
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.models.schema_catalog.models import SchemaCatalog
from app.utils.validator import get_target_dialect
from app.core.config.settings import settings

logger = logging.getLogger(__name__)

# Fallback regex in case sqlglot fails on non-standard dialect extensions
_FROM_JOIN_RE = re.compile(
    r"\b(?:FROM|JOIN)\s+[\"\[`]?([A-Za-z_][A-Za-z0-9_ ]*?)[\"\]`]?(?:\s|,|$|;)",
    re.IGNORECASE,
)


@dataclass
class CostCheckResult:
    allowed: bool
    reason: Optional[str] = None
    estimated_rows_scanned: Optional[int] = None
    referenced_tables: Optional[list[str]] = None
    query_cost: Optional[float] = None
    is_unindexed_scan: bool = False


class CostEstimationError(RuntimeError):
    """Raised when a database query-plan estimate cannot be obtained."""


def _extract_referenced_tables(sql: str, known_tables: Set[str]) -> list[str]:
    """Extract table names referenced in SQL using AST analysis with regex fallback."""
    found: list[str] = []
    known_lower_map = {t.lower(): t for t in known_tables}

    try:
        parsed = sqlglot.parse_one(sql)
        ctes = {cte.alias_or_name.lower() for cte in parsed.find_all(exp.CTE)}
        for tbl in parsed.find_all(exp.Table):
            t_name = tbl.name
            if t_name and t_name.lower() not in ctes:
                matched = known_lower_map.get(t_name.lower())
                if matched and matched not in found:
                    found.append(matched)
    except Exception:
        # Fallback to regex pattern matching
        for m in _FROM_JOIN_RE.finditer(sql):
            candidate = m.group(1).strip()
            matched = known_lower_map.get(candidate.lower())
            if matched and matched not in found:
                found.append(matched)

    return list(dict.fromkeys(found))


def _detect_cartesian_product(sql: str) -> bool:
    """Detect unconstrained Cartesian products (CROSS JOIN or multiple unjoined FROM tables)."""
    try:
        parsed = sqlglot.parse_one(sql)
        where_clause = parsed.find(exp.Where)

        for join in parsed.find_all(exp.Join):
            # Explicit CROSS JOIN is always a Cartesian product
            if getattr(join, "kind", "").upper() == "CROSS":
                return True
            # Comma joins or joins without ON / USING: check if WHERE clause exists
            if not join.args.get("on") and not join.args.get("using"):
                if not where_clause:
                    return True

        # Check multiple tables in FROM
        from_clause = parsed.find(exp.From)
        if from_clause and len(from_clause.expressions) > 1 and not where_clause:
            return True
    except Exception:
        if re.search(r"\bCROSS\s+JOIN\b", sql, re.IGNORECASE):
            return True
    return False


def _analyze_query_ast(sql: str) -> Dict[str, Any]:
    """Analyze query AST for presence of LIMIT, WHERE, and Aggregations."""
    has_limit = False
    limit_value: Optional[int] = None
    has_where = False
    is_aggregate = False

    try:
        parsed = sqlglot.parse_one(sql)
        # Check LIMIT
        limit_node = parsed.args.get("limit") or parsed.find(exp.Limit)
        if limit_node:
            has_limit = True
            try:
                expr = limit_node.expression if hasattr(limit_node, "expression") else limit_node
                limit_value = int(str(expr).strip())
            except (ValueError, TypeError):
                limit_value = None

        # Check WHERE
        where_node = parsed.args.get("where") or parsed.find(exp.Where)
        if where_node:
            has_where = True

        # Check Aggregates
        has_agg_funcs = bool(list(parsed.find_all(exp.Anonymous, exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)))
        has_group_by = parsed.args.get("group") is not None or parsed.find(exp.Group) is not None
        is_aggregate = has_agg_funcs or has_group_by

    except Exception:
        # Regex fallback if AST parsing fails
        has_limit = bool(re.search(r"\b(LIMIT\s+\d+|TOP\s+\d+|FETCH\s+FIRST)\b", sql, re.IGNORECASE))
        has_where = bool(re.search(r"\bWHERE\b", sql, re.IGNORECASE))
        is_aggregate = bool(re.search(r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(|\bGROUP\s+BY\b", sql, re.IGNORECASE))

    return {
        "has_limit": has_limit,
        "limit_value": limit_value,
        "has_where": has_where,
        "is_aggregate": is_aggregate,
    }


def estimate_db_cost(
    sql: str,
    db: Session,
    *,
    raise_on_error: bool = False,
) -> Tuple[Optional[int], Optional[float], bool]:
    """
    Run database-side EXPLAIN to get query plan cost and estimated rows.
    Returns (estimated_rows, total_cost, is_unindexed_scan).
    """
    clean_sql = sql.strip().rstrip(";")
    if not clean_sql:
        return None, None, False

    dialect_name = "sqlite"
    try:
        if db and db.bind and db.bind.dialect:
            dialect_name = db.bind.dialect.name.lower()
        else:
            dialect_name = get_target_dialect()
    except Exception:
        dialect_name = get_target_dialect()

    estimated_rows: Optional[int] = None
    total_cost: Optional[float] = None
    is_unindexed_scan = False

    try:
        if dialect_name in ("postgresql", "postgres"):
            explain_query = f"EXPLAIN (FORMAT JSON) {clean_sql}"
            result = db.execute(text(explain_query)).fetchone()
            if result and result[0]:
                data = result[0]
                if isinstance(data, list) and len(data) > 0:
                    plan = data[0].get("Plan", {})
                    estimated_rows = plan.get("Plan Rows")
                    total_cost = plan.get("Total Cost")
                    # Check for sequential scans
                    plan_str = json.dumps(plan).lower()
                    if "seq scan" in plan_str:
                        is_unindexed_scan = True

        elif dialect_name in ("mysql", "mariadb"):
            explain_query = f"EXPLAIN FORMAT=JSON {clean_sql}"
            result = db.execute(text(explain_query)).fetchone()
            if result and result[0]:
                data = json.loads(result[0]) if isinstance(result[0], str) else result[0]
                query_block = data.get("query_block", {})
                cost_str = query_block.get("cost_info", {}).get("query_cost")
                if cost_str:
                    total_cost = float(cost_str)
                # Check for table scans
                block_str = json.dumps(query_block).lower()
                if '"access_type": "all"' in block_str:
                    is_unindexed_scan = True

        elif dialect_name == "sqlite":
            explain_query = f"EXPLAIN QUERY PLAN {clean_sql}"
            rows = db.execute(text(explain_query)).fetchall()
            for r in rows:
                detail = str(r[3] if len(r) > 3 else r[-1]).upper()
                if "SCAN" in detail and "USING INDEX" not in detail and "SEARCH" not in detail:
                    is_unindexed_scan = True

    except (SQLAlchemyError, Exception) as e:
        try:
            db.rollback()
        except Exception:
            pass
        logger.debug("Database EXPLAIN cost estimate skipped/failed: %s", e)
        if raise_on_error:
            raise CostEstimationError("Database EXPLAIN cost estimation failed") from e

    return estimated_rows, total_cost, is_unindexed_scan


def is_high_risk_query(
    sql: str,
    catalog: Optional[SchemaCatalog] = None,
    max_unfiltered_rows: int = 500_000,
) -> bool:
    """Return whether a query is unsafe to run when cost estimation is unavailable.

    This deliberately mirrors the guard's static high-risk policies: an
    unbounded Cartesian product, or an unfiltered/unbounded scan of a known
    large table.  A filtered query is not promoted to high risk merely because
    the table is large.
    """
    ast_info = _analyze_query_ast(sql)
    if ast_info["has_limit"]:
        return False
    if _detect_cartesian_product(sql):
        return True

    if ast_info["has_where"] or catalog is None or not catalog.tables:
        return False
    referenced = _extract_referenced_tables(sql, set(catalog.tables.keys()))
    return any(
        (catalog.tables[table].row_count or 0) > max_unfiltered_rows
        for table in referenced
    )


def cost_guard_failure_result(
    sql: str,
    *,
    catalog: Optional[SchemaCatalog] = None,
    max_unfiltered_rows: int = 500_000,
    error: Optional[Exception] = None,
) -> CostCheckResult:
    """Convert a guard failure to a consistent fail-closed/continue decision."""
    high_risk = is_high_risk_query(sql, catalog, max_unfiltered_rows)
    fail_closed = getattr(settings, "cost_guard_fail_closed_on_high_risk", True)
    detail = f": {error}" if error else ""
    if high_risk and fail_closed:
        logger.warning("Cost guard failed for high-risk query; blocking execution%s", detail)
        return CostCheckResult(
            allowed=False,
            reason=(
                "High-Risk Query Blocked: cost estimation failed, so the query cannot be "
                "safely approved. Add a restrictive WHERE clause or LIMIT and retry."
            ),
        )

    logger.warning("Cost guard estimation failed; allowing non-high-risk query%s", detail)
    return CostCheckResult(
        allowed=True,
        reason="Cost estimation was unavailable; query allowed because it is not high risk.",
    )


def check_query_cost(
    sql: str,
    catalog: Optional[SchemaCatalog] = None,
    max_unfiltered_rows: int = 500_000,
    db: Optional[Session] = None,
    max_estimated_rows: Optional[int] = None,
) -> CostCheckResult:
    """
    Multi-layered pre-flight cost check:
    1. AST inspection: check for LIMIT, WHERE, Cartesian products, and referenced tables.
    2. Catalog baseline: sum row counts of referenced tables.
    3. EXPLAIN estimation: run database query plan analysis when session is available.
    4. Guard evaluation: fail-closed on unconstrained Cartesian products and runaway table scans.
    """
    if not sql or not sql.strip():
        return CostCheckResult(allowed=True, reason="empty query")

    # 1. AST Analysis
    ast_info = _analyze_query_ast(sql)
    has_limit = ast_info["has_limit"]
    limit_value = ast_info["limit_value"]
    has_where = ast_info["has_where"]

    # 2. Extract referenced tables and catalog row counts
    referenced: list[str] = []
    total_table_rows = 0
    has_large_table = False

    if catalog is not None and catalog.tables:
        referenced = _extract_referenced_tables(sql, set(catalog.tables.keys()))
        for t in referenced:
            rc = catalog.tables[t].row_count
            if rc is not None:
                total_table_rows += rc
                if rc > max_unfiltered_rows:
                    has_large_table = True

    # 3. Fast-path: bounded queries with small LIMIT (e.g. LIMIT 100) are always allowed
    if has_limit and limit_value is not None and limit_value <= 10_000:
        return CostCheckResult(
            allowed=True,
            reason=f"query bounded by LIMIT {limit_value}",
            estimated_rows_scanned=total_table_rows or limit_value,
            referenced_tables=referenced,
        )

    # 4. Fail Closed on High-Risk Cartesian Products (CROSS JOIN)
    fail_closed = getattr(settings, "cost_guard_fail_closed_on_high_risk", True)
    if _detect_cartesian_product(sql) and not has_limit:
        if total_table_rows > 1_000 or has_large_table or fail_closed:
            return CostCheckResult(
                allowed=False,
                reason=(
                    "High-Risk Query Blocked: Unconstrained Cartesian product (CROSS JOIN) without join conditions or LIMIT. "
                    "Please specify explicit JOIN ON conditions or add a LIMIT."
                ),
                referenced_tables=referenced,
            )

    # 5. Strict Block: Unfiltered scan (No WHERE and No LIMIT) on large tables
    if has_large_table and not has_where and not has_limit:
        return CostCheckResult(
            allowed=False,
            reason=(
                f"Query has no WHERE/LIMIT and would scan an estimated {total_table_rows:,} rows "
                f"across {', '.join(referenced)} (threshold: {max_unfiltered_rows:,}). "
                f"Add a filter or a LIMIT."
            ),
            estimated_rows_scanned=total_table_rows,
            referenced_tables=referenced,
        )

    # 6. Database-Side EXPLAIN Check (when DB session is available)
    if db is not None:
        try:
            db_rows, db_cost, is_unindexed = estimate_db_cost(sql, db, raise_on_error=True)
        except CostEstimationError as cost_err:
            return cost_guard_failure_result(
                sql,
                catalog=catalog,
                max_unfiltered_rows=max_unfiltered_rows,
                error=cost_err,
            )
        effective_max_rows = max_estimated_rows or (max_unfiltered_rows * 2)

        # 6a. Block if database engine's optimizer estimates runaway row scans
        if db_rows is not None and db_rows > effective_max_rows:
            return CostCheckResult(
                allowed=False,
                reason=(
                    f"Query plan estimates {db_rows:,} rows scanned (threshold: {effective_max_rows:,}). "
                    f"The WHERE condition has low selectivity on table(s) {', '.join(referenced)}. "
                    f"Please add a more selective filter or a LIMIT."
                ),
                estimated_rows_scanned=db_rows,
                query_cost=db_cost,
                referenced_tables=referenced,
                is_unindexed_scan=is_unindexed,
            )

        # 6b. Block if unindexed scan on massive table without LIMIT
        if is_unindexed and total_table_rows > (max_unfiltered_rows * 2) and not has_limit:
            return CostCheckResult(
                allowed=False,
                reason=(
                    f"Query requires an unindexed full table scan across {total_table_rows:,} rows "
                    f"in {', '.join(referenced)}. Please filter on an indexed column or add a LIMIT."
                ),
                estimated_rows_scanned=total_table_rows,
                query_cost=db_cost,
                referenced_tables=referenced,
                is_unindexed_scan=True,
            )

        return CostCheckResult(
            allowed=True,
            estimated_rows_scanned=db_rows or total_table_rows or None,
            query_cost=db_cost,
            referenced_tables=referenced,
            is_unindexed_scan=is_unindexed,
        )

    # 7. Default allow with estimated table rows
    return CostCheckResult(
        allowed=True,
        estimated_rows_scanned=total_table_rows if total_table_rows > 0 else None,
        referenced_tables=referenced,
    )
