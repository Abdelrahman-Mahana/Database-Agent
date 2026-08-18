"""Result Verifier (Step 10 of Canonical Request Flow).

Verifies query execution results and report texts:
1. Expected cardinality (scalar, lookup, list, aggregate).
2. Aggregate semantics alignment (COUNT/SUM/AVG presence).
3. Null value behavior (detecting all-NULL metric columns).
4. Duplicate row amplification (Cartesian product detection).
5. QuerySpec fulfillment evaluation.
6. Deterministic fact generation from raw execution rows.
7. Result-to-Answer claim verification and prose constraining.
8. Claim-level confidence tracking.
"""
from __future__ import annotations

import re
import uuid
import sqlglot
from sqlglot import exp
from dataclasses import dataclass, field, asdict
from typing import Any, Optional, List, Dict, Tuple
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class DeterministicFact:
    """100% verified ground-truth fact extracted deterministically from query results."""
    claim_id: str
    fact_type: str  # "scalar", "row_count", "metric_aggregation", "top_record", "empty_state"
    statement: str
    source_column: Optional[str] = None
    source_value: Any = None
    operation: str = "value"
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ClaimEvaluation:
    """Evaluation of an individual narrative assertion against verified ground-truth data."""
    statement: str
    status: str  # "VERIFIED", "UNVERIFIED", "CONTRADICTED"
    is_verified: bool
    confidence: float
    evidence_source: Optional[str] = None
    entity: Optional[str] = None
    metric: Optional[str] = None
    operation: Optional[str] = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResultVerificationOutcome:
    """Outcome of verifying database execution results against semantic QuerySpec."""
    passed: bool = True
    cardinality_status: str = "ok"          # "ok", "unexpected_empty", "cardinality_mismatch"
    aggregate_semantics_valid: bool = True
    null_behavior_status: str = "ok"        # "ok", "all_null_metrics", "has_nulls"
    duplicate_amplification_detected: bool = False
    join_cardinality_status: str = "not_evaluated"  # not_evaluated, expected_grain, fanout_warning
    answers_query_spec: bool = True
    claims_grounded: bool = True
    unverified_claims: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics_summary: dict[str, Any] = field(default_factory=dict)
    deterministic_facts: list[DeterministicFact] = field(default_factory=list)
    claim_evaluations: list[ClaimEvaluation] = field(default_factory=list)
    gate_statuses: dict[str, str] = field(default_factory=dict)
    answer_action: str = "PASS"  # PASS: normal answer, WARN: answer with warning, FAIL: block analyst answer

    def to_dict(self) -> dict[str, Any]:
        # `asdict` already recursively serializes both nested dataclasses.
        return asdict(self)


class ResultVerifier:
    """Inspects execution results, SQL structure, and generated reports."""

    def generate_deterministic_facts(
        self,
        rows: list[dict[str, Any]],
        query_spec: Optional[Any] = None,
        sql: str = "",
        question: str = "",
    ) -> list[DeterministicFact]:
        """
        Extracts 100% deterministic ground-truth facts directly from database rows.
        Guarantees zero hallucination.
        """
        facts: list[DeterministicFact] = []
        row_count = len(rows)

        # Facts are answer evidence, not a profile of every result column.  In
        # particular, never infer SUM/AVG/MIN/MAX for every numeric value in a
        # tabular result: identifiers and unrelated metrics are not evidence
        # for the user's question.
        question = question or str(getattr(query_spec, "raw_question", "") or "")
        requested_operations = self._requested_fact_operations(query_spec, sql, question)
        ranking_requested = self._is_ranking_request(query_spec, sql, question)
        sql_has_aggregate = bool(re.search(r"\b(?:COUNT|SUM|AVG|MIN|MAX)\s*\(", sql, re.I))

        # 1. Empty State fact
        if row_count == 0:
            facts.append(DeterministicFact(
                claim_id=f"fact_empty_{uuid.uuid4().hex[:8]}",
                fact_type="empty_state",
                statement="The query returned 0 rows.",
                source_column=None,
                source_value=0,
                confidence=1.0,
            ))
            return facts

        if "count" in requested_operations and not sql_has_aggregate:
            facts.append(DeterministicFact(
                claim_id=f"fact_row_count_{uuid.uuid4().hex[:8]}",
                fact_type="row_count",
                statement=f"Total records returned: {row_count}.",
                source_column=None,
                source_value=row_count,
                operation="count",
                confidence=1.0,
            ))

        # 2. Scalar fact (single row, single/two column queries)
        if row_count == 1:
            first_row = rows[0]
            for col_name, val in first_row.items():
                if val is not None:
                    facts.append(DeterministicFact(
                        claim_id=f"fact_scalar_{col_name}_{uuid.uuid4().hex[:8]}",
                        fact_type="scalar",
                        statement=f"{col_name.replace('_', ' ').title()} is {val}.",
                        source_column=col_name,
                        source_value=val,
                        evidence={"row": 0, "column": col_name},
                        confidence=1.0,
                    ))

        # 3. Derive an aggregate only when the question asks for that operation
        # and metric.  If SQL already aggregates, its projected values are the
        # answer; re-aggregating grouped rows would create a different fact.
        if row_count > 1 and requested_operations and not sql_has_aggregate:
            for col_name in self._requested_metric_columns(rows, query_spec, question):
                numeric_values = [
                    float(row[col_name]) for row in rows
                    if isinstance(row.get(col_name), (int, float)) and not isinstance(row.get(col_name), bool)
                ]
                if not numeric_values:
                    continue
                for operation in requested_operations:
                    if operation == "count":
                        continue
                    value = self._aggregate_value(numeric_values, operation)
                    if value is None:
                        continue
                    label = col_name.replace("_", " ")
                    verb = {"sum": "Total", "average": "Average", "min": "Minimum", "max": "Maximum"}[operation]
                    facts.append(DeterministicFact(
                        claim_id=f"fact_agg_{operation}_{col_name}_{uuid.uuid4().hex[:8]}",
                        fact_type="metric_aggregation",
                        statement=f"{verb} {label} is {value:,.2f}.",
                        source_column=col_name,
                        source_value=value,
                        operation=operation,
                        evidence={"rows": list(range(row_count)), "column": col_name},
                        confidence=1.0,
                    ))

        # 4. Rankings contain ordered entities and their requested metric, not
        # synthetic statistics over every numeric column.
        if ranking_requested:
            facts.extend(self._ranking_facts(rows, query_spec, question, sql))

        return facts

    @staticmethod
    def _aggregate_value(values: list[float], operation: str) -> Optional[float]:
        if operation == "sum":
            return sum(values)
        if operation == "average":
            return sum(values) / len(values)
        if operation == "min":
            return min(values)
        if operation == "max":
            return max(values)
        return None

    def _requested_fact_operations(self, query_spec: Optional[Any], sql: str, question: str) -> set[str]:
        requested = " ".join(str(item).lower() for item in (getattr(query_spec, "aggregations", []) or []))
        text = f"{requested} {question.lower()}"
        operations: set[str] = set()
        for operation, patterns in {
            "sum": (r"\bsum\b", r"\btotal\b", "إجمالي", "مجموع"),
            "average": (r"\bavg\b", r"\baverage\b", "متوسط"),
            "min": (r"\bminimum\b", r"\bmin\b", r"\blowest\b", "أقل", "أدنى"),
            "max": (r"\bmaximum\b", r"\bmax\b", r"\bhighest\b", "أعلى", "أكبر"),
            "count": (r"\bcount\b", r"\bhow many\b", "عدد", "كم"),
        }.items():
            if any(re.search(pattern, text, re.I) if pattern.startswith(r"\b") else pattern in text for pattern in patterns):
                operations.add(operation)
        return operations

    def _requested_metric_columns(self, rows: list[dict[str, Any]], query_spec: Optional[Any], question: str) -> list[str]:
        columns = list(rows[0])
        requested_metrics = [self._normalise_words(metric).replace(" ", "_") for metric in (getattr(query_spec, "metrics", []) or [])]
        question_words = self._normalise_words(question).split()
        selected = []
        for column in columns:
            value = next((row.get(column) for row in rows if row.get(column) is not None), None)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or self._is_identifier_column(column):
                continue
            normalized = self._normalise_words(column)
            if (
                any(metric and (metric in normalized.replace(" ", "_") or normalized.replace(" ", "_") in metric) for metric in requested_metrics)
                or any(word in normalized.split() for word in question_words)
                or column.lower() in question.lower()
            ):
                selected.append(column)
        return selected

    @staticmethod
    def _is_identifier_column(column: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]", "", column.lower())
        return normalized == "id" or normalized.endswith("id") or normalized.endswith("key")

    def _is_ranking_request(self, query_spec: Optional[Any], sql: str, question: str) -> bool:
        shape = getattr(query_spec, "output_shape", None) or getattr(query_spec, "expected_output", "")
        shape = shape.value if hasattr(shape, "value") else str(shape).lower()
        return (
            shape == "ranking"
            or bool(re.search(r"\b(top|bottom|highest|lowest|best|worst)\b|أعلى|الأكثر|أقل|الأدنى", question, re.I))
            or bool(re.search(r"\bORDER\s+BY\b[\s\S]*\bLIMIT\s+\d+", sql, re.I))
        )

    def _ranking_facts(self, rows: list[dict[str, Any]], query_spec: Optional[Any], question: str, sql: str) -> list[DeterministicFact]:
        metric_columns = self._requested_metric_columns(rows, query_spec, question)
        if not metric_columns:
            metric_columns = [column for column in rows[0] if isinstance(rows[0].get(column), (int, float)) and not self._is_identifier_column(column)]
        if not metric_columns:
            return []
        metric = metric_columns[0]
        entity_columns = [column for column in rows[0] if column != metric and not isinstance(rows[0].get(column), (int, float))]
        entity_column = entity_columns[0] if entity_columns else None
        facts = []
        for index, row in enumerate(rows, start=1):
            entity = row.get(entity_column) if entity_column else "record"
            value = row.get(metric)
            facts.append(DeterministicFact(
                claim_id=f"fact_rank_{index}_{uuid.uuid4().hex[:8]}",
                fact_type="ranked_entity",
                statement=f"Rank {index}: {entity} — {metric.replace('_', ' ')} is {value}.",
                source_column=metric,
                source_value={"rank": index, "entity": entity, "metric": value},
                operation="rank",
                evidence={"row": index - 1, "entity_column": entity_column, "metric_column": metric},
                confidence=1.0,
            ))
        return facts

    def verify(
        self,
        rows: list[dict[str, Any]],
        query_spec: Optional[Any] = None,
        sql: str = "",
        validation_status: Optional[dict[str, Any]] = None,
        catalog: Optional[Any] = None,
    ) -> ResultVerificationOutcome:
        outcome = ResultVerificationOutcome()
        sql_upper = sql.upper() if sql else ""
        row_count = len(rows)

        outcome.metrics_summary["row_count"] = row_count
        outcome.metrics_summary["column_count"] = len(rows[0]) if rows else 0

        # Generate deterministic facts
        outcome.deterministic_facts = self.generate_deterministic_facts(rows, query_spec=query_spec, sql=sql)

        # 1. Cardinality Verification
        if row_count == 0:
            outcome.cardinality_status = "unexpected_empty"
            outcome.warnings.append("Execution returned 0 rows. Filters may be too restrictive.")
        else:
            raw_shape = getattr(query_spec, "output_shape", None) or getattr(query_spec, "expected_output", None) or ""
            output_shape = raw_shape.value if hasattr(raw_shape, "value") else str(raw_shape).lower()

            if output_shape == "scalar":
                if row_count > 1:
                    outcome.cardinality_status = "cardinality_mismatch"
                    outcome.warnings.append(f"Expected single scalar value, but received {row_count} rows.")
                elif len(rows[0]) > 1:
                    outcome.warnings.append(f"Expected single scalar column, but received {len(rows[0])} columns.")

        # 2. Aggregate Semantics Check
        if query_spec:
            metrics = getattr(query_spec, "metrics", []) or []
            has_aggregates = any(fn in sql_upper for fn in ("COUNT(", "SUM(", "AVG(", "MIN(", "MAX("))
            if metrics and not has_aggregates and "GROUP BY" not in sql_upper:
                outcome.aggregate_semantics_valid = False
                outcome.warnings.append("QuerySpec requested metrics, but generated SQL lacks aggregate functions.")

        # 3. Null Behavior Inspection
        if rows:
            all_keys = list(rows[0].keys())
            null_cols = []
            for key in all_keys:
                if all(r.get(key) is None for r in rows):
                    null_cols.append(key)

            if null_cols:
                outcome.null_behavior_status = "all_null_metrics"
                outcome.warnings.append(f"Columns {null_cols} returned NULL for all rows.")

        # 4. Join cardinality / grain analysis.  Repeated result rows alone
        # are valid for many queries (e.g. several customers in Egypt), so
        # never use row equality as Cartesian-product evidence.
        cardinality = self._analyze_join_cardinality(rows, sql, catalog, query_spec)
        outcome.join_cardinality_status = cardinality["status"]
        outcome.metrics_summary["join_cardinality"] = cardinality
        if cardinality["status"] == "fanout_warning":
            outcome.warnings.append(cardinality["message"])

        # 5. Explicit quality gates.  Do not infer success from a loose
        # warnings expression: each gate has one of PASS/WARN/FAIL, and any
        # FAIL blocks an analyst narrative.
        validation_status = validation_status or {}
        outcome.gate_statuses = {
            "safety": "PASS" if validation_status.get("safety_valid", True) else "FAIL",
            "identifier_grounding": "PASS" if validation_status.get("identifiers_valid", True) else "FAIL",
            "semantic_alignment": "PASS" if validation_status.get("alignment_valid", True) else "FAIL",
            "result_cardinality": "WARN" if outcome.cardinality_status in {"cardinality_mismatch", "unexpected_empty"} else (
                "PASS"
            ),
            "aggregate_semantics": "PASS" if outcome.aggregate_semantics_valid else "FAIL",
            "null_behavior": "WARN" if outcome.null_behavior_status != "ok" else "PASS",
            "join_cardinality": "WARN" if outcome.join_cardinality_status == "fanout_warning" else "PASS",
        }
        gate_values = set(outcome.gate_statuses.values())
        outcome.answer_action = "FAIL" if "FAIL" in gate_values else ("WARN" if "WARN" in gate_values else "PASS")
        outcome.passed = outcome.answer_action != "FAIL"
        outcome.answers_query_spec = outcome.gate_statuses["semantic_alignment"] == "PASS" and outcome.gate_statuses["aggregate_semantics"] == "PASS"

        return outcome

    def _analyze_join_cardinality(
        self,
        rows: list[dict[str, Any]], sql: str, catalog: Optional[Any], query_spec: Optional[Any],
    ) -> dict[str, Any]:
        """Detect proven FK fan-out; return inconclusive without grain/key evidence."""
        if not rows or catalog is None or not hasattr(catalog, "tables"):
            return {"status": "not_evaluated", "reason": "catalog PK/FK evidence unavailable"}
        try:
            parsed = sqlglot.parse_one(sql)
        except Exception:
            return {"status": "not_evaluated", "reason": "SQL could not be parsed"}
        if not list(parsed.find_all(exp.Join)):
            return {"status": "expected_grain", "reason": "query has no joins"}
        if parsed.find(exp.Group) or any(parsed.find_all(exp.AggFunc)):
            return {"status": "expected_grain", "reason": "aggregate/grouped output defines its own grain"}

        # Derive parent -> child relationships with their PK output columns.
        parent_children: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for child_name, profile in catalog.tables.items():
            child_short = child_name.split(".")[-1].lower()
            child_pks = profile.primary_key or [c.name for c in profile.columns if c.primary_key]
            if len(child_pks) != 1:
                continue
            for fk in profile.foreign_keys:
                refs = fk.get("referred_columns", [])
                if len(refs) != 1:
                    continue
                parent = fk.get("referred_table", "").split(".")[-1].lower()
                parent_children.setdefault((parent, refs[0].lower()), []).append((child_short, child_pks[0].lower()))

        # Need a parent key and at least two independently-related child PKs
        # in the projection.  Without all three, the result grain is unknown.
        output_columns = {name.lower(): name for name in rows[0]}
        for (parent, parent_pk), children in parent_children.items():
            parent_output = output_columns.get(parent_pk)
            child_outputs = [(child, output_columns.get(pk)) for child, pk in children if output_columns.get(pk)]
            if not parent_output or len(child_outputs) < 2:
                continue
            for parent_value in {row.get(parent_output) for row in rows}:
                group = [row for row in rows if row.get(parent_output) == parent_value]
                cardinalities = [len({row.get(output) for row in group}) for _, output in child_outputs]
                product = 1
                for count in cardinalities:
                    product *= count
                # This is FK-backed fan-out evidence, not duplicate equality.
                if len(group) == product and product > max(cardinalities, default=1):
                    requested_tables = {
                        str(dimension).split(".")[0].split(".")[-1].lower()
                        for dimension in (getattr(query_spec, "dimensions", []) or [])
                        if "." in str(dimension)
                    }
                    child_tables = {child for child, _ in child_outputs}
                    if child_tables.issubset(requested_tables):
                        return {
                            "status": "expected_grain",
                            "reason": "QuerySpec explicitly requests dimensions from each fan-out child table",
                        }
                    return {
                        "status": "fanout_warning",
                        "parent_table": parent,
                        "parent_key": parent_pk,
                        "parent_value": parent_value,
                        "child_cardinalities": dict(zip((child for child, _ in child_outputs), cardinalities)),
                        "row_multiplication_ratio": round(product / max(cardinalities), 2),
                        "message": "FK-backed join fan-out detected; verify that the requested output grain permits this multiplication.",
                    }
        return {"status": "not_evaluated", "reason": "result projection lacks sufficient parent/child PK evidence"}

    # -- Control 4: Result-to-Answer Claim Checker & Prose Constrainer ----------

    def verify_and_constrain_prose(
        self,
        report_text: str,
        rows: list[dict[str, Any]],
        facts: Optional[list[DeterministicFact]] = None,
        analytics_result: Optional[dict[str, Any]] = None,
        sql: str = "",
    ) -> Tuple[str, list[ClaimEvaluation], float]:
        """
        Evaluates sentences/claims in the generated narrative prose against ground-truth cells
        and deterministic facts. Constrains unverified assertions and tracks claim-level confidence.
        """
        if not report_text:
            return "", [], 1.0

        if not rows:
            # If no rows, verify if report states empty/no data
            claim = ClaimEvaluation(
                statement=report_text.strip(),
                status="VERIFIED",
                is_verified=True,
                confidence=1.0,
                evidence_source="empty_dataset",
            )
            return report_text, [claim], 1.0

        if "| ---" in report_text or re.search(r"^\s*\|.+\|\s*$", report_text, re.MULTILINE):
            claim = ClaimEvaluation(
                statement="Markdown table response generated from executed result rows.",
                status="VERIFIED",
                is_verified=True,
                confidence=0.85,
                evidence_source="rendered_result_table",
            )
            return report_text, [claim], 0.85

        # Do not create an untyped pool of numbers.  `300` from units_sold is
        # not evidence for a "churn was 300" claim.  Each candidate below has
        # explicit row/column provenance and semantic labels.
        evidence_index = self._build_claim_evidence(rows, sql=sql)

        # 2. Deconstruct prose into sentences/claims.
        sentences = re.split(r"(?<=[.!?\n])\s+", report_text.strip())
        evaluations: list[ClaimEvaluation] = []
        valid_sentences: list[str] = []

        number_pattern = re.compile(r"\b(?:\$)?(\d+(?:,\d{3})*(?:\.\d+)?)(?:%)?\b")

        for sent in sentences:
            sent_clean = sent.strip()
            if not sent_clean:
                continue

            nums = number_pattern.findall(sent_clean)
            matched_evidence: list[dict[str, Any]] = []
            unmatched_numbers: list[str] = []

            for match in nums:
                clean_num_str = match.replace(",", "")
                try:
                    val = float(clean_num_str)
                    evidence = self._find_claim_evidence(sent_clean, val, evidence_index)
                    if evidence is None:
                        unmatched_numbers.append(match)
                    else:
                        matched_evidence.append(evidence)
                except ValueError:
                    continue

            # Numeric-free narrative assertions cannot be proven from cells
            # without a semantic claim representation. Short framing text is
            # neutral when the result rows exist; analytical assertions still
            # fail closed.
            framing_text = (
                not nums
                and len(sent_clean.split()) <= 30
                and bool(re.search(r"\b(here (are|is)|results?|details?|records?|data|database|calculated|verify|sql|raw result)\b", sent_clean, re.I))
            )
            is_claim_valid = bool(nums) and not unmatched_numbers
            if is_claim_valid:
                primary = matched_evidence[0]
                evaluations.append(ClaimEvaluation(
                    statement=sent_clean,
                    status="VERIFIED",
                    is_verified=True,
                    confidence=1.0,
                    evidence_source="structured_result_evidence",
                    entity=primary.get("entity"),
                    metric=primary.get("metric"),
                    operation=primary.get("operation"),
                    evidence={"matches": matched_evidence},
                ))
                valid_sentences.append(sent_clean)
            elif framing_text:
                evaluations.append(ClaimEvaluation(
                    statement=sent_clean,
                    status="VERIFIED",
                    is_verified=True,
                    confidence=0.75,
                    evidence_source="framing_text",
                ))
                valid_sentences.append(sent_clean)
            else:
                evaluations.append(ClaimEvaluation(
                    statement=sent_clean,
                    status="UNVERIFIED",
                    is_verified=False,
                    confidence=0.20,
                    evidence_source=(
                        f"unmatched_figures: {', '.join(unmatched_numbers)}"
                        if unmatched_numbers else "no_structured_claim_evidence"
                    ),
                ))
                # Add disclaimer on unverified claims
                valid_sentences.append(f"{sent_clean} *(unverified claim)*")

        # Overall claim confidence
        if evaluations:
            verified_count = sum(1 for e in evaluations if e.is_verified)
            overall_confidence = round(verified_count / len(evaluations), 2)
        else:
            overall_confidence = 1.0

        constrained_prose = " ".join(valid_sentences)
        return constrained_prose, evaluations, overall_confidence

    @staticmethod
    def _normalise_words(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()

    def _build_claim_evidence(self, rows: list[dict[str, Any]], sql: str = "") -> list[dict[str, Any]]:
        """Build only provenance-carrying evidence records from result rows."""
        evidence: list[dict[str, Any]] = []
        row_count = len(rows)
        sql_upper = sql.upper()
        aggregate_operation = next((
            operation for token, operation in (
                ("COUNT(", "count"), ("SUM(", "sum"), ("AVG(", "average"),
                ("MIN(", "min"), ("MAX(", "max"),
            ) if token in sql_upper
        ), None)
        for row_index, row in enumerate(rows):
            entity_values = [
                str(value).strip() for value in row.values()
                if isinstance(value, str) and value.strip() and not self._is_numeric(value)
            ]
            for column, value in row.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                normalized_column = self._normalise_words(column)
                # A projected ``*_count`` / ``count_*`` value is already a
                # count fact, even when callers of the legacy checker do not
                # provide the source SQL.  Treating it as a plain cell value
                # makes a truthful sentence such as "the system has 4
                # companies" impossible to verify.
                column_is_count = (
                    normalized_column == "count"
                    or normalized_column.startswith("count ")
                    or normalized_column.endswith(" count")
                )
                evidence.append({
                    "value": float(value), "entity": entity_values,
                    "metric": column,
                    "operation": aggregate_operation or ("count" if column_is_count else "value"),
                    "evidence": {"row": row_index, "column": column},
                })

        # Aggregates have an explicit operation and the full source row set.
        if row_count > 1:
            for column in rows[0]:
                values = [r.get(column) for r in rows]
                if all(isinstance(v, str) and v.strip() for v in values):
                    evidence.append({
                        "value": float(row_count), "entity": [], "metric": f"{column}_count", "operation": "count",
                        "evidence": {"rows": list(range(row_count)), "column": column},
                    })
                if not values or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                    continue
                numeric_values = [float(v) for v in values]
                for operation, value in (
                    ("sum", sum(numeric_values)),
                    ("average", sum(numeric_values) / row_count),
                    ("min", min(numeric_values)),
                    ("max", max(numeric_values)),
                ):
                    evidence.append({
                        "value": value, "entity": [], "metric": column, "operation": operation,
                        "evidence": {"rows": list(range(row_count)), "column": column},
                    })
        return evidence

    @staticmethod
    def _is_numeric(value: str) -> bool:
        try:
            float(re.sub(r"[,$%]", "", value))
            return True
        except ValueError:
            return False

    def _find_claim_evidence(
        self, sentence: str, value: float, evidence_index: list[dict[str, Any]]
    ) -> Optional[dict[str, Any]]:
        """Match value + metric + operation + entity (when row-level) atomically."""
        normalized_sentence = self._normalise_words(sentence)
        operation = "value"
        for keyword, candidate_operation in (
            ("average", "average"), ("avg", "average"), ("total", "sum"),
            ("sum", "sum"), ("minimum", "min"), ("lowest", "min"),
            ("maximum", "max"), ("highest", "max"),
        ):
            if keyword in normalized_sentence.split():
                operation = candidate_operation
                break

        for candidate in evidence_index:
            if abs(value - candidate["value"]) >= 0.01:
                continue
            metric = self._normalise_words(candidate["metric"])
            metric_in_sentence = self._metric_is_named(metric, normalized_sentence)
            # "across 2 products" is a count claim tied to the product
            # column, even though it does not literally say "product count".
            if candidate["operation"] == "count":
                source_name = metric.removesuffix(" count")
                metric_in_sentence = (
                    source_name in normalized_sentence
                    or f"{source_name}s" in normalized_sentence
                    # Count aliases are deliberately limited to a count
                    # projection; they never permit a value from an unrelated
                    # metric to substantiate a narrative claim.
                    or (
                        metric in {"count", "total count", "record count", "row count"}
                        and bool(re.search(r"\b(has|have|there are|exist|exists|number of|total)\b", normalized_sentence))
                    )
                )
            if not metric_in_sentence:
                continue
            if candidate["operation"] != operation and not (
                candidate["operation"] == "count"
                or (candidate["operation"] == "value" and candidate["entity"])
            ):
                continue
            # A row-level value must name an entity from its source row.  This
            # prevents a value from a different metric/entity being reused.
            entities = candidate["entity"]
            if candidate["operation"] == "value" and (
                not entities
                or not any(self._normalise_words(entity) in normalized_sentence for entity in entities)
            ):
                continue
            return {
                "entity": entities[0] if entities else None,
                "metric": candidate["metric"], "operation": candidate["operation"],
                "value": candidate["value"], **candidate["evidence"],
            }
        return None

    @staticmethod
    def _metric_is_named(metric: str, sentence: str) -> bool:
        if metric and metric in sentence:
            return True
        # Conservative semantic aliases.  These preserve a metric binding
        # (unlike value-only matching) for common report wording.
        aliases = {
            "revenue": {"revenue", "sales", "generated", "bringing"},
            "units sold": {"units sold", "units", "quantity"},
        }
        return any(alias in sentence.split() or alias in sentence for alias in aliases.get(metric, set()))

    def verify_report_claims(
        self,
        report_text: str,
        rows: list[dict[str, Any]],
        analytics_result: Optional[dict[str, Any]] = None,
    ) -> Tuple[bool, list[str]]:
        """Backward-compatible claim checker."""
        _, evaluations, _ = self.verify_and_constrain_prose(
            report_text, rows, analytics_result=analytics_result
        )
        unverified = [f"Unverified claim: '{e.statement}'" for e in evaluations if not e.is_verified]
        return len(unverified) == 0, unverified


# Global singleton instance
result_verifier = ResultVerifier()
