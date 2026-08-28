"""Evidence Manager and Investigation Progress Evaluation.

Responsible for:
1. Deterministic evidence extraction from QueryExecutionRecords and query results
   (aggregates, rankings, comparisons, trends, observations, empty datasets).
2. Grounded evidence provenance tracking (every evidence item strictly linked to source_query_id).
3. Safe handling of nulls, missing columns, empty datasets, and dirty/numeric strings.
4. InvestigationProgressEvaluator for task breakdowns, evidence coverage, unresolved questions, and state progress.
"""
from dataclasses import dataclass
from decimal import Decimal
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.analysis.investigation_models import (
    EvidenceItem,
    EvidenceType,
    InvestigationPlan,
    InvestigationState,
    InvestigationStatus,
    QueryExecutionRecord,
    QueryExecutionStatus,
    QueryTask,
    QueryTaskStatus,
)

logger = logging.getLogger(__name__)


# ─── Data Classes ───

@dataclass
class InvestigationProgress:
    """Snapshot evaluation of investigation progress and evidence coverage."""
    completed_tasks: List[str]
    pending_tasks: List[str]
    blocked_tasks: List[str]
    failed_tasks: List[str]
    task_completion: float
    evidence_coverage: float
    confidence_score: float
    completion_status: InvestigationStatus
    evidence_count: int
    known_facts_count: int
    unresolved_questions: List[str]


# ─── Utility Helpers ───

def _safe_numeric(val: Any) -> Optional[float]:
    """Safely parse a value into float, returning None on failure or non-numeric types."""
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, str):
        cleaned = val.strip().replace(",", "")
        # Remove trailing percentage sign if present
        if cleaned.endswith("%"):
            try:
                return float(cleaned[:-1])
            except ValueError:
                return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _parse_temporal_key(val: Any) -> Optional[Tuple[int, ...]]:
    """Parse string/numeric value into a comparable temporal tuple (year, month, day)."""
    if val is None:
        return None
    s = str(val).strip().lower()

    # 1. Check direct 4-digit year (e.g. 2024, 2025)
    if re.fullmatch(r"\d{4}", s):
        return (int(s), 0, 0)

    # 2. Check YYYY-MM-DD or YYYY/MM/DD
    m_date = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m_date:
        return (int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3)))

    # 3. Check YYYY-MM or YYYY/MM
    m_ym = re.match(r"^(\d{4})[-/](\d{1,2})$", s)
    if m_ym:
        return (int(m_ym.group(1)), int(m_ym.group(2)), 0)

    # 4. Check Year + Quarter (e.g. 2024-Q3, 2024 Q3, Q3 2024, Q3-2024)
    m_q1 = re.match(r"^(\d{4})[-_\s]*q([1-4])$", s)
    if m_q1:
        return (int(m_q1.group(1)), int(m_q1.group(2)) * 3, 0)
    m_q2 = re.match(r"^q([1-4])[-_\s]*(\d{4})$", s)
    if m_q2:
        return (int(m_q2.group(2)), int(m_q2.group(1)) * 3, 0)

    # 5. Check Quarter alone (e.g. Q1, Q2, Q3, Q4)
    m_q_alone = re.match(r"^q([1-4])$", s)
    if m_q_alone:
        return (0, int(m_q_alone.group(1)) * 3, 0)

    # 6. Check Month Name + Year (e.g. Jan 2024, January 2024, 2024 Jan)
    tokens = re.findall(r"\w+", s)
    year = 0
    month = 0
    for tok in tokens:
        if tok.isdigit() and len(tok) == 4:
            year = int(tok)
        elif tok in MONTH_NAMES:
            month = MONTH_NAMES[tok]
    if year > 0 or month > 0:
        return (year, month, 0)

    return None


def _format_number(val: float) -> str:
    """Format numeric values cleanly with comma grouping and up to 2 decimal places."""
    if val is None:
        return "N/A"
    if abs(val - round(val)) < 1e-9:
        return f"{int(round(val)):,}"
    return f"{val:,.2f}"


def _clean_metric_name(name: str) -> str:
    """Normalize and format a column/metric name for natural language statements."""
    cleaned = name.replace("_", " ").strip()
    return cleaned


# ─── Evidence Manager ───

class EvidenceManager:
    """Extracts grounded, deterministic evidence items from query execution results."""

    @classmethod
    def extract_evidence(
        cls,
        record: QueryExecutionRecord,
        task: Optional[QueryTask] = None,
        expected_evidence: Optional[str] = None,
    ) -> List[EvidenceItem]:
        """Deterministically extract structured evidence items from a QueryExecutionRecord.

        Handles:
        1. Empty results (row_count == 0).
        2. Failed query executions.
        3. Aggregates (single-row metrics).
        4. Rankings / Top-K entities (deterministically sorted by metric descending).
        5. Two-period or two-entity Comparisons (chronologically or metadata-ordered).
        6. Sequential / Chronological Trends (chronologically sorted).
        """
        evidence_items: List[EvidenceItem] = []
        query_id = record.query_id
        purpose = task.purpose if (task and task.purpose) else record.purpose
        sub_q = task.sub_question if (task and task.sub_question) else record.sub_question

        # 1. Handle Failed Query Execution
        if record.status == QueryExecutionStatus.FAILED or record.error:
            evidence_items.append(
                EvidenceItem(
                    evidence_id=f"ev_{query_id}_failed",
                    source_query_id=query_id,
                    statement=f"Query '{query_id}' failed: {record.error or 'Execution error'}",
                    metric=None,
                    value=None,
                    dimensions={},
                    confidence=1.0,
                    verified=True,
                    evidence_type=EvidenceType.OBSERVATION,
                    derivation_method="raw_observed",
                )
            )
            return evidence_items

        # 2. Handle Empty Result (0 rows)
        if record.status == QueryExecutionStatus.EMPTY or (not record.rows or len(record.rows) == 0):
            evidence_items.append(
                EvidenceItem(
                    evidence_id=f"ev_{query_id}_empty",
                    source_query_id=query_id,
                    statement=f"No matching records were found for query '{query_id}'.",
                    metric="row_count",
                    value=0,
                    dimensions={},
                    confidence=1.0,
                    verified=True,
                    evidence_type=EvidenceType.OBSERVATION,
                    derivation_method="raw_observed",
                )
            )
            return evidence_items

        rows = record.rows
        first_row = rows[0]
        if not isinstance(first_row, dict):
            return evidence_items

        # Classify columns into numeric metrics and categorical/temporal dimensions
        DIMENSION_PATTERNS = (
            "year", "month", "day", "date", "quarter", "period", "time", "week",
            "id", "code", "name", "category", "region", "country", "city", "state",
            "segment", "type", "status", "channel", "brand", "product", "customer",
            "user", "group", "tier", "department", "genre", "cohort"
        )

        metric_cols: List[str] = []
        dimension_cols: List[str] = []

        for col, val in first_row.items():
            col_lower = col.lower()
            # Explicit dimension column name check
            is_dim_by_name = any(
                col_lower == p or col_lower.endswith(f"_{p}") or col_lower.startswith(f"{p}_")
                for p in DIMENSION_PATTERNS
            )
            num_val = _safe_numeric(val)

            if is_dim_by_name and not any(k in col_lower for k in ("count", "amount", "total", "sum", "revenue", "price", "margin", "profit")):
                dimension_cols.append(col)
            elif num_val is not None:
                metric_cols.append(col)
            else:
                dimension_cols.append(col)

        # 3. Strategy: Single Row Aggregates (Pure Metrics or 1 Row Summary)
        if len(rows) == 1:
            for col in metric_cols:
                num_val = _safe_numeric(first_row.get(col))
                if num_val is None:
                    continue
                dims = {d: first_row.get(d) for d in dimension_cols if first_row.get(d) is not None}
                dim_prefix = f"for {', '.join(f'{k}={v}' for k, v in dims.items())} " if dims else ""
                clean_name = _clean_metric_name(col)

                statement = f"{clean_name.capitalize()} {dim_prefix}= {_format_number(num_val)}"
                if purpose and len(metric_cols) == 1:
                    statement = f"{purpose}: {clean_name} = {_format_number(num_val)}"

                evidence_items.append(
                    EvidenceItem(
                        evidence_id=f"ev_{query_id}_{col}",
                        source_query_id=query_id,
                        statement=statement.strip(),
                        metric=col,
                        value=num_val,
                        dimensions=dims,
                        confidence=1.0,
                        verified=True,
                        evidence_type=EvidenceType.NUMERIC,
                        derivation_method="raw_observed",
                    )
                )
            # If no numeric metrics in single row, record categorical fact
            if not metric_cols and dimension_cols:
                dims = {d: first_row.get(d) for d in dimension_cols}
                evidence_items.append(
                    EvidenceItem(
                        evidence_id=f"ev_{query_id}_cat",
                        source_query_id=query_id,
                        statement=f"Retrieved record: {', '.join(f'{k}={v}' for k, v in dims.items())}",
                        value=dims,
                        dimensions=dims,
                        confidence=1.0,
                        verified=True,
                        evidence_type=EvidenceType.CATEGORICAL,
                        derivation_method="raw_observed",
                    )
                )
            return evidence_items

        # 4. Strategy: Two-Row Comparison (Deterministic baseline vs current)
        if len(rows) == 2 and metric_cols and dimension_cols:
            primary_dim = dimension_cols[0]
            r0 = rows[0]
            r1 = rows[1]
            d0_str = str(r0.get(primary_dim, "Period 1"))
            d1_str = str(r1.get(primary_dim, "Period 2"))

            t0 = _parse_temporal_key(d0_str)
            t1 = _parse_temporal_key(d1_str)

            # Determine chronological baseline vs current
            has_reliable_order = False
            base_row, curr_row = r0, r1
            base_label, curr_label = d0_str, d1_str

            if t0 is not None and t1 is not None and t0 != t1:
                has_reliable_order = True
                if t0 < t1:
                    base_row, curr_row = r0, r1
                    base_label, curr_label = d0_str, d1_str
                else:
                    base_row, curr_row = r1, r0
                    base_label, curr_label = d1_str, d0_str
            elif task and (task.purpose or task.sub_question):
                # Check for explicit baseline/target markers
                text_meta = f"{task.purpose} {task.sub_question}".lower()
                if d0_str.lower() in ("base", "baseline", "prev", "previous", "2024") and d1_str.lower() in ("curr", "current", "target", "2025"):
                    has_reliable_order = True
                    base_row, curr_row = r0, r1
                    base_label, curr_label = d0_str, d1_str
                elif d1_str.lower() in ("base", "baseline", "prev", "previous", "2024") and d0_str.lower() in ("curr", "current", "target", "2025"):
                    has_reliable_order = True
                    base_row, curr_row = r1, r0
                    base_label, curr_label = d1_str, d0_str

            for col in metric_cols[:2]:  # Focus on primary numeric metrics
                v_base = _safe_numeric(base_row.get(col))
                v_curr = _safe_numeric(curr_row.get(col))

                if v_base is not None and v_curr is not None:
                    clean_name = _clean_metric_name(col)

                    if has_reliable_order:
                        delta = v_curr - v_base
                        pct_change = ((delta) / v_base * 100) if v_base != 0 else 0.0

                        if delta < 0:
                            rel_phrase = f"{abs(pct_change):.1f}% lower than"
                        elif delta > 0:
                            rel_phrase = f"{abs(pct_change):.1f}% higher than"
                        else:
                            rel_phrase = "equal to"

                        statement = (
                            f"{curr_label} {clean_name} ({_format_number(v_curr)}) is {rel_phrase} {base_label} ({_format_number(v_base)})"
                        )

                        evidence_items.append(
                            EvidenceItem(
                                evidence_id=f"ev_{query_id}_comp_{col}",
                                source_query_id=query_id,
                                statement=statement,
                                metric=col,
                                value={"base": v_base, "target": v_curr, "delta": delta, "pct_change": round(pct_change, 2)},
                                dimensions={primary_dim: [base_label, curr_label]},
                                confidence=0.95,
                                verified=True,
                                evidence_type=EvidenceType.COMPARISON,
                                derivation_method="comparison_delta",
                            )
                        )
                    else:
                        # Ambiguous ordering: produce neutral comparison observation without directional claims
                        v0 = _safe_numeric(r0.get(col))
                        v1 = _safe_numeric(r1.get(col))
                        obs_statement = (
                            f"Two comparison records retrieved for {clean_name} across {primary_dim} "
                            f"({d0_str}: {_format_number(v0)}, {d1_str}: {_format_number(v1)}), "
                            f"without an explicit baseline/current chronology."
                        )
                        evidence_items.append(
                            EvidenceItem(
                                evidence_id=f"ev_{query_id}_comp_obs_{col}",
                                source_query_id=query_id,
                                statement=obs_statement,
                                metric=col,
                                value={d0_str: v0, d1_str: v1},
                                dimensions={primary_dim: [d0_str, d1_str]},
                                confidence=0.90,
                                verified=True,
                                evidence_type=EvidenceType.OBSERVATION,
                                derivation_method="unresolved_comparison_observation",
                            )
                        )

        # 5. Strategy: Ranking / Top-K Entity (Intent-Aware & Deterministic sorting)
        if len(rows) >= 2 and metric_cols and dimension_cols:
            primary_dim = dimension_cols[0]
            primary_metric = metric_cols[0]

            # Intent check: only produce ranking evidence if task/question explicitly indicates ranking intent
            RANKING_KEYWORDS = {
                "top", "highest", "lowest", "rank", "ranking", "best", "worst",
                "most", "least", "bottom", "first", "leading", "max", "min",
                "أعلى", "أفضل", "أكثر", "أقل", "ترتيب", "أكبر", "أصغر"
            }
            text_context = f"{purpose} {sub_q} {expected_evidence or ''}".lower()
            has_ranking_intent = any(k in re.findall(r"\w+", text_context) for k in RANKING_KEYWORDS)

            valid_metric_rows = [
                r for r in rows
                if _safe_numeric(r.get(primary_metric)) is not None and r.get(primary_dim) is not None
            ]

            if valid_metric_rows:
                # Sort deterministically by metric
                sorted_by_metric = sorted(
                    valid_metric_rows,
                    key=lambda r: _safe_numeric(r.get(primary_metric)),
                    reverse=True,
                )
                top_row = sorted_by_metric[0]
                top_dim_val = str(top_row.get(primary_dim, ""))
                top_metric_val = _safe_numeric(top_row.get(primary_metric))

                clean_metric = _clean_metric_name(primary_metric)
                clean_dim = _clean_metric_name(primary_dim)

                if has_ranking_intent and top_dim_val and top_metric_val is not None:
                    ranking_statement = (
                        f"{top_dim_val} is the top {clean_dim} by {clean_metric} with {_format_number(top_metric_val)}"
                    )

                    evidence_items.append(
                        EvidenceItem(
                            evidence_id=f"ev_{query_id}_top_{primary_dim}",
                            source_query_id=query_id,
                            statement=ranking_statement,
                            metric=primary_metric,
                            value=top_metric_val,
                            dimensions={primary_dim: top_dim_val},
                            confidence=0.95,
                            verified=True,
                            evidence_type=EvidenceType.RANKING,
                            derivation_method="deterministic_ranking",
                        )
                    )
                elif not has_ranking_intent and not evidence_items:
                    # Non-ranking multi-row query: produce categorical breakdown observation
                    min_val = min(_safe_numeric(r.get(primary_metric)) for r in valid_metric_rows)
                    max_val = max(_safe_numeric(r.get(primary_metric)) for r in valid_metric_rows)
                    breakdown_stmt = (
                        f"{clean_metric.capitalize()} breakdown across {len(valid_metric_rows)} {clean_dim} categories "
                        f"(range: {_format_number(min_val)} to {_format_number(max_val)})"
                    )
                    evidence_items.append(
                        EvidenceItem(
                            evidence_id=f"ev_{query_id}_breakdown_{primary_dim}",
                            source_query_id=query_id,
                            statement=breakdown_stmt,
                            metric=primary_metric,
                            value={"min": min_val, "max": max_val, "count": len(valid_metric_rows)},
                            dimensions={primary_dim: len(valid_metric_rows)},
                            confidence=0.90,
                            verified=True,
                            evidence_type=EvidenceType.OBSERVATION,
                            derivation_method="categorical_observation",
                        )
                    )

        # 6. Strategy: Sequential / Chronological Trend (>= 3 points)
        if len(rows) >= 3 and metric_cols and dimension_cols:
            primary_dim = dimension_cols[0]
            primary_metric = metric_cols[0]

            # Attempt chronological parsing
            parsed_keys = [_parse_temporal_key(r.get(primary_dim)) for r in rows]
            is_chronological = all(k is not None for k in parsed_keys)

            if is_chronological:
                # Sort rows deterministically by parsed temporal chronology
                sorted_temporal_rows = sorted(
                    rows,
                    key=lambda r: _parse_temporal_key(r.get(primary_dim)) or (0, 0, 0),
                )
                series_values = [_safe_numeric(r.get(primary_metric)) for r in sorted_temporal_rows]

                if all(v is not None for v in series_values):
                    start_label = str(sorted_temporal_rows[0].get(primary_dim, "Start"))
                    end_label = str(sorted_temporal_rows[-1].get(primary_dim, "End"))
                    clean_metric = _clean_metric_name(primary_metric)

                    # Monotonically increasing
                    if all(series_values[i] <= series_values[i + 1] for i in range(len(series_values) - 1)) and series_values[0] < series_values[-1]:
                        trend_stmt = f"{clean_metric.capitalize()} increased from {start_label} to {end_label}"
                        trend_dir = "increasing"
                    # Monotonically decreasing
                    elif all(series_values[i] >= series_values[i + 1] for i in range(len(series_values) - 1)) and series_values[0] > series_values[-1]:
                        trend_stmt = f"{clean_metric.capitalize()} decreased from {start_label} to {end_label}"
                        trend_dir = "decreasing"
                    else:
                        min_val = min(series_values)
                        max_val = max(series_values)
                        trend_stmt = (
                            f"{clean_metric.capitalize()} fluctuated across {len(rows)} periods "
                            f"between {_format_number(min_val)} and {_format_number(max_val)}"
                        )
                        trend_dir = "fluctuating"

                    evidence_items.append(
                        EvidenceItem(
                            evidence_id=f"ev_{query_id}_trend_{primary_metric}",
                            source_query_id=query_id,
                            statement=trend_stmt,
                            metric=primary_metric,
                            value={
                                "start": series_values[0],
                                "end": series_values[-1],
                                "min": min(series_values),
                                "max": max(series_values),
                                "direction": trend_dir,
                            },
                            dimensions={primary_dim: [start_label, end_label]},
                            confidence=0.95,
                            verified=True,
                            evidence_type=EvidenceType.TREND,
                            derivation_method="chronological_trend",
                        )
                    )
            else:
                # If dimension is not chronological, do not make directional claims; produce neutral categorical observation
                series_values = [_safe_numeric(r.get(primary_metric)) for r in rows if _safe_numeric(r.get(primary_metric)) is not None]
                if series_values and not evidence_items:
                    clean_metric = _clean_metric_name(primary_metric)
                    clean_dim = _clean_metric_name(primary_dim)
                    min_val = min(series_values)
                    max_val = max(series_values)
                    obs_stmt = f"{clean_metric.capitalize()} observed across {len(rows)} {clean_dim} categories (range: {_format_number(min_val)} to {_format_number(max_val)})"

                    evidence_items.append(
                        EvidenceItem(
                            evidence_id=f"ev_{query_id}_obs_{primary_metric}",
                            source_query_id=query_id,
                            statement=obs_stmt,
                            metric=primary_metric,
                            value={"min": min_val, "max": max_val, "count": len(series_values)},
                            dimensions={primary_dim: len(rows)},
                            confidence=0.90,
                            verified=True,
                            evidence_type=EvidenceType.OBSERVATION,
                            derivation_method="categorical_observation",
                        )
                    )

        # 7. Fallback: If no specialized evidence created, create high-level row summary
        if not evidence_items:
            evidence_items.append(
                EvidenceItem(
                    evidence_id=f"ev_{query_id}_summary",
                    source_query_id=query_id,
                    statement=f"Query '{query_id}' retrieved {len(rows)} rows with columns: {', '.join(list(first_row.keys())[:5])}.",
                    metric="row_count",
                    value=len(rows),
                    dimensions={},
                    confidence=1.0,
                    verified=True,
                    evidence_type=EvidenceType.OBSERVATION,
                    derivation_method="raw_observed",
                )
            )

        return evidence_items


# ─── Investigation Progress Evaluator ───

class InvestigationProgressEvaluator:
    """Evaluates task execution status, evidence coverage, unresolved questions, and overall progress."""

    @classmethod
    def evaluate_progress(cls, state: InvestigationState) -> InvestigationProgress:
        """Compute an accurate progress assessment separating task completion, evidence coverage, and confidence."""
        if not state.plan or not state.plan.query_tasks:
            # Empty plan progress
            return InvestigationProgress(
                completed_tasks=[],
                pending_tasks=[],
                blocked_tasks=[],
                failed_tasks=[],
                task_completion=1.0,
                evidence_coverage=1.0,
                confidence_score=1.0,
                completion_status=InvestigationStatus.COMPLETED,
                evidence_count=len(state.evidence),
                known_facts_count=len(state.known_facts),
                unresolved_questions=[],
            )

        query_tasks = state.plan.query_tasks
        total_count = len(query_tasks)

        completed_tasks: List[str] = [t.query_id for t in query_tasks if t.status == QueryTaskStatus.COMPLETED]
        pending_tasks: List[str] = [t.query_id for t in query_tasks if t.status in (QueryTaskStatus.PENDING, QueryTaskStatus.RUNNING)]
        blocked_tasks: List[str] = [t.query_id for t in query_tasks if t.status in (QueryTaskStatus.BLOCKED, QueryTaskStatus.SKIPPED)]
        failed_tasks: List[str] = [t.query_id for t in query_tasks if t.status == QueryTaskStatus.FAILED]

        # 1. Task Completion: fraction of query tasks completed
        task_completion = round(len(completed_tasks) / total_count, 2) if total_count > 0 else 1.0

        # 2. Evidence Coverage: fraction of expected evidence verified from completed tasks
        covered_tasks = [
            t.query_id for t in query_tasks
            if t.status == QueryTaskStatus.COMPLETED and any(
                ev.source_query_id == t.query_id and ev.verified and not (ev.evidence_type == EvidenceType.OBSERVATION and "failed" in ev.statement.lower())
                for ev in state.evidence
            )
        ]
        evidence_coverage = round(len(covered_tasks) / total_count, 2) if total_count > 0 else 1.0

        # 3. Confidence Score: separate from task completion and evidence coverage
        if state.evidence:
            confidence_score = round(sum(e.confidence for e in state.evidence) / len(state.evidence), 2)
        else:
            confidence_score = 0.0

        # Update unresolved questions deterministically
        unresolved: List[str] = []
        for t in query_tasks:
            if t.status != QueryTaskStatus.COMPLETED and t.sub_question:
                if t.sub_question not in unresolved:
                    unresolved.append(t.sub_question)
        state.unresolved_questions = unresolved

        # Update known facts canonical synchronization from evidence
        for ev in state.evidence:
            if ev.statement and ev.statement not in state.known_facts:
                state.known_facts.append(ev.statement)

        # Synchronize state metrics
        state.task_completion = task_completion
        state.evidence_coverage = evidence_coverage
        state.completeness_score = evidence_coverage
        state.confidence_score = confidence_score

        # Determine completion status
        if state.queries_executed >= state.max_queries:
            if len(completed_tasks) == total_count:
                completion_status = InvestigationStatus.COMPLETED
            elif len(completed_tasks) > 0:
                completion_status = InvestigationStatus.BUDGET_EXHAUSTED
            else:
                completion_status = InvestigationStatus.FAILED
        elif len(completed_tasks) == total_count:
            completion_status = InvestigationStatus.COMPLETED
        elif pending_tasks:
            # Check if any pending tasks are eligible to run
            completed_set = set(completed_tasks)
            has_runnable = any(
                not t.depends_on or all(dep in completed_set for dep in t.depends_on)
                for t in query_tasks
                if t.status == QueryTaskStatus.PENDING
            )
            completion_status = InvestigationStatus.RUNNING if has_runnable else InvestigationStatus.PARTIAL
        elif len(completed_tasks) > 0:
            completion_status = InvestigationStatus.PARTIAL
        else:
            completion_status = InvestigationStatus.FAILED

        return InvestigationProgress(
            completed_tasks=completed_tasks,
            pending_tasks=pending_tasks,
            blocked_tasks=blocked_tasks,
            failed_tasks=failed_tasks,
            task_completion=task_completion,
            evidence_coverage=evidence_coverage,
            confidence_score=confidence_score,
            completion_status=completion_status,
            evidence_count=len(state.evidence),
            known_facts_count=len(state.known_facts),
            unresolved_questions=unresolved,
        )
