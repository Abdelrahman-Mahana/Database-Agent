"""One pre-execution control gate for every SQL provenance path."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.config.settings import settings
from app.core.security.cost_guard import check_query_cost, cost_guard_failure_result
from app.utils.helpers import validate_sql


@dataclass
class SQLControlGateResult:
    allowed: bool
    error_type: str | None = None
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    validation_status: dict[str, bool] = field(default_factory=dict)


class SQLControlGate:
    """Apply the canonical pre-execution controls irrespective of SQL source."""

    def evaluate(
        self,
        sql: str,
        *,
        query_spec: Any = None,
        catalog: Any = None,
        raw_schema: dict[str, Any] | None = None,
        db: Any = None,
    ) -> SQLControlGateResult:
        safety = validate_sql(sql)
        if not safety["valid"]:
            return SQLControlGateResult(False, safety.get("query_type", "safety"), safety["reason"])

        # Import lazily to keep the gate usable in lightweight validation paths.
        from app.services.sql.validator import sql_validator
        identifiers_ok, identifier_warnings = sql_validator.verify_sql_identifiers(
            sql, catalog=catalog, raw_schema=raw_schema or {}
        )
        joins_ok, join_warnings = sql_validator.verify_sql_joins(sql, catalog=catalog)
        alignment_ok, alignment_warnings = sql_validator.verify_query_spec_alignment(
            sql, query_spec=query_spec, catalog=catalog
        )
        warnings = identifier_warnings + join_warnings + alignment_warnings
        status = {
            "safety_valid": True,
            "identifiers_valid": identifiers_ok,
            "joins_valid": joins_ok,
            "alignment_valid": alignment_ok,
            "meaning_valid": alignment_ok,
        }
        if not identifiers_ok or not joins_ok or not alignment_ok:
            error_type = (
                "identifier_grounding" if not identifiers_ok else
                "join_validation" if not joins_ok else
                "semantic_alignment"
            )
            return SQLControlGateResult(False, error_type, "; ".join(warnings) or "SQL failed semantic validation.", warnings, status)


        if settings.enable_cost_guard:
            try:
                cost = check_query_cost(
                    sql=sql, catalog=catalog, db=db,
                    max_unfiltered_rows=settings.cost_guard_max_unfiltered_rows,
                    max_estimated_rows=settings.cost_guard_max_estimated_rows,
                )
            except Exception as cost_err:
                cost = cost_guard_failure_result(
                    sql,
                    catalog=catalog,
                    max_unfiltered_rows=settings.cost_guard_max_unfiltered_rows,
                    error=cost_err,
                )
            if cost is not None and not cost.allowed:
                return SQLControlGateResult(False, "cost_guard", cost.reason, warnings, status)

        return SQLControlGateResult(True, warnings=warnings, validation_status=status)
