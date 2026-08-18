"""Query Explanation Service (P1 Feature).

Provides dry-run query inspection, schema grounding preview, join paths,
assumptions, and estimated execution cost without executing live data queries.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.sql.validator import sql_validator
from app.security.cost_guard import check_query_cost
from app.schema_catalog.models import SchemaCatalog


class QueryExplainService:
    """Explains tables used, filters, joins, and assumptions before running risky/complex queries."""

    def explain_sql(
        self,
        sql: str,
        catalog: Optional[SchemaCatalog] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Produce a comprehensive dry-run breakdown of a SQL statement."""
        explanation: Dict[str, Any] = {
            "sql": sql,
            "safety_valid": True,
            "safety_reason": "Query is safe",
            "tables_used": [],
            "join_paths": [],
            "filters": [],
            "aggregations": [],
            "estimated_cost": None,
            "assumptions": [],
        }

        # 1. Safety validation
        safety = sql_validator.validate_safety(sql)
        explanation["safety_valid"] = safety.get("valid", False)
        explanation["safety_reason"] = safety.get("reason", "Query is safe")

        if not explanation["safety_valid"]:
            return explanation

        # 2. AST Decomposition
        try:
            parsed = sqlglot.parse_one(sql)

            # Tables
            tables = [t.name for t in parsed.find_all(exp.Table) if t.name]
            explanation["tables_used"] = list(dict.fromkeys(tables))

            # Joins
            for join in parsed.find_all(exp.Join):
                join_tbl = join.this.name if isinstance(join.this, exp.Table) else str(join.this)
                on_clause = join.args.get("on")
                explanation["join_paths"].append({
                    "table": join_tbl,
                    "kind": join.kind or "INNER",
                    "condition": on_clause.sql() if on_clause else "NATURAL",
                })

            # Filters (WHERE / HAVING)
            where = parsed.args.get("where")
            if where:
                explanation["filters"].append(where.sql())

            # Aggregations
            for func in parsed.find_all(exp.Func):
                fname = getattr(func, "name", "") or func.sql_name()
                if fname.upper() in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
                    explanation["aggregations"].append(func.sql())

        except Exception as parse_err:
            explanation["assumptions"].append(f"AST partial parse notice: {parse_err}")

        # 3. Cost & Resource Estimation
        try:
            cost_res = check_query_cost(sql=sql, catalog=catalog, db=db)
            explanation["estimated_cost"] = {
                "allowed": cost_res.allowed,
                "reason": cost_res.reason,
                "estimated_rows": cost_res.estimated_rows,
                "estimated_cost_units": cost_res.estimated_cost,
                "is_unfiltered_scan": cost_res.is_unfiltered_scan,
            }
        except Exception:
            pass

        return explanation


# Global singleton instance
query_explain_service = QueryExplainService()
