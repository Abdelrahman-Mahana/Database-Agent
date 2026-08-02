"""Phase 5 — query cost guard.

Runs BEFORE execution, not via a live EXPLAIN (which is dialect-fragile —
SQLite, Postgres, and MySQL all format EXPLAIN output differently, and
parsing "estimated rows" out of it reliably across all three is its own
maintenance burden). Instead this does static analysis of the generated SQL
text plus the row counts already captured once in the Schema Catalog
(Phase 1) — cheap, dialect-agnostic, and testable without a live DB
connection.

Policy (deliberately conservative — fails OPEN, never blocks blind):
  - No row-count data available (no catalog / table not profiled) -> ALLOW.
    We only block when we can actually reason about the cost; guessing wrong
    and blocking a legitimate query is worse than occasionally missing a
    genuinely expensive one.
  - Query has a WHERE clause, a LIMIT/TOP/FETCH clause, or is a pure
    aggregation (COUNT/SUM/AVG/... or GROUP BY, which return few rows
    regardless of table size) -> ALLOW.
  - Otherwise, sum the row counts of every table referenced. If that sum
    exceeds the configured threshold -> BLOCK with a clear reason (the
    caller — analyst_agent — can turn this into a repair-loop instruction
    or a user-facing message asking to narrow the question).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.schema_catalog.models import SchemaCatalog

_FROM_JOIN_RE = re.compile(r"\b(?:FROM|JOIN)\s+[\"\[`]?([A-Za-z_][A-Za-z0-9_ ]*?)[\"\]`]?(?:\s|,|$|;)", re.IGNORECASE)
_WHERE_RE = re.compile(r"\bWHERE\b", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\b(LIMIT|TOP\s+\d+|FETCH\s+FIRST)\b", re.IGNORECASE)
_AGG_RE = re.compile(r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(|\bGROUP\s+BY\b", re.IGNORECASE)


@dataclass
class CostCheckResult:
    allowed: bool
    reason: Optional[str] = None
    estimated_rows_scanned: Optional[int] = None
    referenced_tables: Optional[list[str]] = None


def _extract_referenced_tables(sql: str, known_tables: set[str]) -> list[str]:
    found = []
    for m in _FROM_JOIN_RE.finditer(sql):
        candidate = m.group(1).strip()
        # Case-insensitive match against known table names (schema is the
        # source of truth for actual casing/spacing, e.g. "Order Details").
        for t in known_tables:
            if t.lower() == candidate.lower():
                found.append(t)
                break
    return list(dict.fromkeys(found))  # de-dup, preserve order


def check_query_cost(
    sql: str,
    catalog: Optional[SchemaCatalog],
    max_unfiltered_rows: int = 500_000,
) -> CostCheckResult:
    """Pre-flight check: should this query be allowed to run as-is?

    Safe to call with `catalog=None` (e.g. before the first profiling pass
    has completed) — always returns allowed=True in that case.
    """
    if catalog is None or not catalog.tables:
        return CostCheckResult(allowed=True, reason="no schema catalog available — cannot estimate, allowing")

    if _WHERE_RE.search(sql) or _LIMIT_RE.search(sql) or _AGG_RE.search(sql):
        return CostCheckResult(allowed=True, reason="filtered, limited, or aggregate query")

    referenced = _extract_referenced_tables(sql, set(catalog.tables.keys()))
    if not referenced:
        return CostCheckResult(allowed=True, reason="could not identify referenced tables — allowing")

    total_rows = 0
    known_any_count = False
    for t in referenced:
        rc = catalog.tables[t].row_count
        if rc is not None:
            total_rows += rc
            known_any_count = True

    if not known_any_count:
        return CostCheckResult(allowed=True, reason="row counts not profiled yet — allowing", referenced_tables=referenced)

    if total_rows > max_unfiltered_rows:
        return CostCheckResult(
            allowed=False,
            reason=(
                f"Query has no WHERE/LIMIT and would scan an estimated {total_rows:,} rows "
                f"across {', '.join(referenced)} (threshold: {max_unfiltered_rows:,}). "
                f"Add a filter or a LIMIT."
            ),
            estimated_rows_scanned=total_rows,
            referenced_tables=referenced,
        )

    return CostCheckResult(allowed=True, estimated_rows_scanned=total_rows, referenced_tables=referenced)
