"""Report generation service — turns raw SQL results into analyst reports."""
import json
import logging
from enum import Enum
from typing import Any, Optional

from app.config.settings import settings
from app.llm.model import get_langchain_llm
from app.llm.prompts import REPORT_TEMPLATE, CHART_SUGGESTION_TEMPLATE, REPORT_VERIFICATION_TEMPLATE, NO_ANSWER_RESPONSE_TEMPLATE
from app.services.sql_service import SchemaService
from app.utils.text_processor import extract_json_text
from app.analytics.models import AnalyticsResult, InsightResult

logger = logging.getLogger(__name__)


class ReportMode(str, Enum):
    """Whether the response is rendered from verified evidence or synthesized."""
    DETERMINISTIC = "deterministic"
    SYNTHESIS = "synthesis"


class ReportService:
    """Generates analyst reports and chart suggestions from query results."""

    def __init__(self):
        self.schema_service = SchemaService()


    def _format_results_compact(self, results: list[dict[str, Any]], max_rows: int = 15) -> str:
        """Format results as minified JSON to drastically reduce prompt tokens."""
        if not results:
            return "[]"
        return json.dumps(results[:max_rows], separators=(',', ':'), default=str)

    def _script_language_mismatch(self, original: str, revised: str) -> bool:
        """
        Cheap, deterministic check for whether `revised` switched script
        (e.g. Arabic -> Latin) compared to `original`. This is a safety net
        behind the prompt instruction to preserve language during the
        verification/rewrite pass - instruction-following alone isn't
        reliable enough for something as visible as answering in the wrong
        language entirely.
        """
        import re
        arabic_re = re.compile(r"[\u0600-\u06FF]")
        orig_has_arabic = bool(arabic_re.search(original))
        revised_has_arabic = bool(arabic_re.search(revised))
        # Only flag a real mismatch: original was clearly Arabic (enough
        # Arabic characters to not be a false positive from e.g. a proper
        # noun) and the revision dropped Arabic entirely.
        orig_arabic_chars = len(arabic_re.findall(original))
        return orig_has_arabic and orig_arabic_chars > 10 and not revised_has_arabic

    @staticmethod
    def _humanize_identifier(name: str) -> str:
        name = (name or "value").split(".")[-1]
        return name.replace("_", " ").strip() or "value"

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return f"{value:,}"
        if isinstance(value, float):
            return f"{value:,.2f}".rstrip("0").rstrip(".")
        return str(value)

    def _format_conversational_report(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        verified_facts: Optional[list[Any]] = None,
        total_result_rows: Optional[int] = None,
    ) -> str:
        """Return a natural chat-style answer; raw SQL/results stay in metadata."""
        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
        row_count = total_result_rows if total_result_rows is not None else len(results)

        if not results:
            return (
                "\u0645\u0634 \u0644\u0627\u0642\u064a \u0646\u062a\u0627\u064a\u062c \u0645\u0637\u0627\u0628\u0642\u0629 \u0644\u0644\u0633\u0624\u0627\u0644. \u0645\u0645\u0643\u0646 \u0646\u062c\u0631\u0628 \u0633\u0624\u0627\u0644 \u0623\u0648\u0633\u0639 \u0623\u0648 \u0646\u062d\u062f\u062f \u062c\u062f\u0648\u0644 \u0645\u0639\u064a\u0646."
                if is_arabic else
                "I couldn't find matching rows for that question. We can try a broader question or target a specific table."
            )

        if len(results) == 1 and len(results[0]) == 1:
            col_name, col_val = next(iter(results[0].items()))
            label = self._humanize_identifier(col_name)
            value = self._format_value(col_val)
            return (
                f"`{label}` \u0647\u0648 **{value}**.\n\n"
                f"\u062f\u0647 \u0627\u0644\u0631\u0642\u0645 \u0627\u0644\u0644\u064a \u0627\u062a\u062d\u0633\u0628 \u0645\u0628\u0627\u0634\u0631\u0629 \u0645\u0646 \u0642\u0627\u0639\u062f\u0629 \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0644\u0640 `{label}`. "
                f"\u0644\u0648 \u062d\u0628\u064a\u062a \u062a\u062a\u0623\u0643\u062f\u060c \u0627\u0641\u062a\u062d \u0627\u0644\u062a\u0641\u0627\u0635\u064a\u0644 \u062a\u062d\u062a \u0648\u0647\u062a\u0644\u0627\u0642\u064a SQL \u0648\u0627\u0644\u0646\u062a\u064a\u062c\u0629 \u0627\u0644\u062e\u0627\u0645."
                if is_arabic else
                f"The `{label}` is **{value}**.\n\n"
                f"I calculated that directly from the database for `{label}`. If you want to verify it, open the details below to see the SQL and raw result."
            )

        columns = list(results[0].keys())
        ranked_facts = [
            fact for fact in (verified_facts or [])
            if (fact.get("fact_type") if isinstance(fact, dict) else getattr(fact, "fact_type", None)) == "ranked_entity"
        ]

        sample_lines = []
        if ranked_facts:
            for index, fact in enumerate(ranked_facts[:5], start=1):
                value = fact.get("source_value") if isinstance(fact, dict) else getattr(fact, "source_value", None)
                if isinstance(value, dict):
                    entity = value.get("entity", "record")
                    metric = self._humanize_identifier(str(value.get("metric", "value")))
                    metric_value = self._format_value(value.get("metric"))
                    sample_lines.append(f"{index}. {entity} — {metric}: {metric_value}")
                else:
                    statement = fact.get("statement") if isinstance(fact, dict) else getattr(fact, "statement", "")
                    sample_lines.append(f"{index}. {statement}")
        else:
            for row in results[:5]:
                shown = [f"{self._humanize_identifier(key)}: {self._format_value(row.get(key))}" for key in columns[:3]]
                sample_lines.append("- " + "; ".join(shown))
        samples = "\n".join(sample_lines)
        supporting_facts = [
            line[2:] if line.startswith("- ") else line
            for line in self._format_verified_facts(verified_facts or [], limit=3)
            if "Rank " not in line
        ]
        if is_arabic:
            fact_sentence = (
                "\n\n\u0627\u0644\u062d\u0633\u0627\u0628 \u0627\u0644\u0623\u0647\u0645 \u0645\u0646 \u0643\u0644 \u0627\u0644\u0635\u0641\u0648\u0641: "
                + "؛ ".join(supporting_facts)
                if supporting_facts else ""
            )
        else:
            fact_sentence = (
                "\n\nThe key calculation from all rows is: "
                + "; ".join(supporting_facts)
                if supporting_facts else ""
            )

        if is_arabic:
            return (
                f"\u0647\u0646\u0627\u0643 **{row_count}** \u0646\u062a\u064a\u062c\u0629 \u0645\u0637\u0627\u0628\u0642\u0629.\n\n"
                f"\u0623\u0647\u0645 \u0627\u0644\u0646\u062a\u0627\u064a\u062c:\n{samples}{fact_sentence}\n\n"
                f"\u0644\u0648 \u0639\u0627\u0648\u0632 \u062a\u0631\u0627\u062c\u0639 \u0637\u0631\u064a\u0642\u0629 \u0627\u0644\u062d\u0633\u0627\u0628\u060c \u0627\u0641\u062a\u062d \u062a\u0641\u0627\u0635\u064a\u0644 SQL \u0648\u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u062e\u0627\u0645 \u062a\u062d\u062a."
            )

        return (
            f"There are **{row_count}** matching result{'s' if row_count != 1 else ''}.\n\n"
            f"The most useful results are:\n{samples}{fact_sentence}\n\n"
            f"If you want to audit the calculation, open the SQL and raw data details below."
        )

    def _format_conversational_report(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        verified_facts: Optional[list[Any]] = None,
        total_result_rows: Optional[int] = None,
    ) -> str:
        """Polished final answer style: answer first, explain simply, keep audit details optional."""
        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
        row_count = total_result_rows if total_result_rows is not None else len(results)

        if not results:
            if is_arabic:
                return (
                    "\u0627\u0644\u062e\u0644\u0627\u0635\u0629: \u0645\u0634 \u0644\u0627\u0642\u064a \u0646\u062a\u0627\u064a\u062c \u0645\u0637\u0627\u0628\u0642\u0629 \u0644\u0644\u0633\u0624\u0627\u0644.\n\n"
                    "\u0627\u0644\u0645\u0639\u0646\u0649 \u0628\u0628\u0633\u0627\u0637\u0629: \u0625\u0645\u0627 \u0627\u0644\u0641\u0644\u062a\u0631 \u0636\u064a\u0642 \u0634\u0648\u064a\u0629\u060c \u0623\u0648 \u0627\u0644\u062c\u062f\u0648\u0644 \u0627\u0644\u0645\u0646\u0627\u0633\u0628 \u0644\u0645 \u064a\u062a\u062d\u062f\u062f \u0628\u062f\u0642\u0629. \u062c\u0631\u0628 \u062a\u0633\u0623\u0644 \u0628\u0635\u064a\u063a\u0629 \u0623\u0648\u0633\u0639 \u0623\u0648 \u0627\u0630\u0643\u0631 \u0627\u0633\u0645 \u0627\u0644\u062c\u062f\u0648\u0644."
                )
            return (
                "Short answer: I couldn't find matching results for that question.\n\n"
                "What this means: the filter may be too narrow, or the right table was not specific enough. Try a broader question or mention the table you want to inspect."
            )

        if len(results) == 1 and len(results[0]) == 1:
            col_name, col_val = next(iter(results[0].items()))
            label = self._humanize_identifier(col_name)
            value = self._format_value(col_val)
            if is_arabic:
                return (
                    f"\u0627\u0644\u062e\u0644\u0627\u0635\u0629: `{label}` \u0647\u0648 **{value}**.\n\n"
                    "\u0627\u0644\u0645\u0639\u0646\u0649 \u0628\u0628\u0633\u0627\u0637\u0629: \u062f\u0647 \u0631\u0642\u0645 \u0627\u062a\u062d\u0633\u0628 \u0645\u0628\u0627\u0634\u0631\u0629 \u0645\u0646 \u0642\u0627\u0639\u062f\u0629 \u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a\u060c \u0641\u0645\u0641\u064a\u0634 \u062a\u062d\u0644\u064a\u0644 \u0625\u0636\u0627\u0641\u064a \u0645\u062d\u062a\u0627\u062c\u0647 \u0627\u0644\u0625\u062c\u0627\u0628\u0629.\n\n"
                    "\u0644\u0644\u0645\u0631\u0627\u062c\u0639\u0629: \u0627\u0641\u062a\u062d \u201c\u0637\u0631\u064a\u0642\u0629 \u0627\u0644\u0648\u0635\u0648\u0644 \u0644\u0644\u0625\u062c\u0627\u0628\u0629\u201d \u0648\u201c\u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u062e\u0627\u0645\u201d \u062a\u062d\u062a."
                )
            return (
                f"Short answer: `{label}` is **{value}**.\n\n"
                "What this means: this value was calculated directly from the database, so no extra interpretation is needed.\n\n"
                "To verify it, open \"How I got it (SQL)\" and \"Raw data\" below."
            )

        ranked_facts = [
            fact for fact in (verified_facts or [])
            if (fact.get("fact_type") if isinstance(fact, dict) else getattr(fact, "fact_type", None)) == "ranked_entity"
        ]
        lines: list[str] = []
        if ranked_facts:
            for index, fact in enumerate(ranked_facts[:5], start=1):
                value = fact.get("source_value") if isinstance(fact, dict) else getattr(fact, "source_value", None)
                if isinstance(value, dict):
                    entity = value.get("entity", "record")
                    metric = self._humanize_identifier(str(value.get("metric", "value")))
                    metric_value = self._format_value(value.get("metric"))
                    lines.append(f"{index}. **{entity}** - {metric}: **{metric_value}**")
                else:
                    statement = fact.get("statement") if isinstance(fact, dict) else getattr(fact, "statement", "")
                    lines.append(f"{index}. {statement}")
        else:
            columns = list(results[0].keys())
            for row in results[:5]:
                shown = [
                    f"{self._humanize_identifier(key)}: {self._format_value(row.get(key))}"
                    for key in columns[:3]
                ]
                lines.append("- " + "; ".join(shown))

        supporting_facts = [
            line[2:] if line.startswith("- ") else line
            for line in self._format_verified_facts(verified_facts or [], limit=3)
            if "Rank " not in line
        ]
        facts_text = ""
        if supporting_facts:
            facts_text = (
                "\n\n\u0623\u0647\u0645 \u062d\u0633\u0627\u0628 \u0645\u0646 \u0643\u0644 \u0627\u0644\u0646\u062a\u0627\u064a\u062c: " + "\u061b ".join(supporting_facts)
                if is_arabic else
                "\n\nThe key calculation across all results is: " + "; ".join(supporting_facts)
            )

        results_text = "\n".join(lines)
        if is_arabic:
            return (
                f"\u0627\u0644\u062e\u0644\u0627\u0635\u0629: \u0644\u0642\u064a\u062a **{row_count}** \u0646\u062a\u064a\u062c\u0629 \u0645\u0637\u0627\u0628\u0642\u0629.\n\n"
                f"\u0623\u0647\u0645 \u0645\u0627 \u0648\u062c\u062f\u062a\u0647:\n{results_text}{facts_text}\n\n"
                "\u0627\u0644\u0645\u0639\u0646\u0649 \u0628\u0628\u0633\u0627\u0637\u0629: \u062f\u064a \u0623\u0647\u0645 \u0627\u0644\u0646\u062a\u0627\u064a\u062c \u0627\u0644\u0645\u0637\u0627\u0628\u0642\u0629 \u0644\u0633\u0624\u0627\u0644\u0643\u060c \u0648\u062a\u0642\u062f\u0631 \u062a\u0637\u0644\u0628 \u062a\u0636\u064a\u064a\u0642 \u0627\u0644\u0646\u062a\u0627\u064a\u062c \u0623\u0648 \u062a\u0631\u062a\u064a\u0628\u0647\u0627 \u0628\u0637\u0631\u064a\u0642\u0629 \u0645\u062e\u062a\u0644\u0641\u0629.\n\n"
                "\u0644\u0644\u0645\u0631\u0627\u062c\u0639\u0629: \u0627\u0641\u062a\u062d \u201c\u0637\u0631\u064a\u0642\u0629 \u0627\u0644\u0648\u0635\u0648\u0644 \u0644\u0644\u0625\u062c\u0627\u0628\u0629\u201d \u0648\u201c\u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u062e\u0627\u0645\u201d \u062a\u062d\u062a."
            )

        return (
            f"Short answer: I found **{row_count}** matching result{'s' if row_count != 1 else ''}.\n\n"
            f"Here is what matters most:\n{results_text}{facts_text}\n\n"
            "What this means: these are the strongest matches for your question. You can ask me to narrow them down, sort them differently, or explain any row.\n\n"
            "To verify it, open \"How I got it (SQL)\" and \"Raw data\" below."
        )

    def _format_deterministic_report(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        analytics_result: Optional[AnalyticsResult] = None,
        insight_result: Optional[InsightResult] = None,
        verified_facts: Optional[list[Any]] = None,
        total_result_rows: Optional[int] = None,
    ) -> str:
        """Compatibility wrapper: deterministic answers should read like chat, not reports."""
        return self._format_conversational_report(
            question=question,
            sql=sql,
            results=results,
            verified_facts=verified_facts,
            total_result_rows=total_result_rows,
        )

        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
        lines = []

        # 1. Summary Title
        if is_arabic:
            lines.append(f"### ملخص نتائج الاستعلام: **{question}**\n")
            lines.append(f"تم تنفيذ الاستعلام بنجاح واسترجاع **{len(results)}** سجل:")
        else:
            lines.append(f"### Query Results Summary: **{question}**\n")
            lines.append(f"The query executed successfully and returned **{total_result_rows if total_result_rows is not None else len(results)}** records:")

        lines.append("")

        # 2. Markdown Table for tabular results
        if results and len(results) <= 15:
            headers = list(results[0].keys())
            header_line = "| " + " | ".join(headers) + " |"
            sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
            lines.append(header_line)
            lines.append(sep_line)
            for row in results:
                row_vals = [str(row.get(h, "")) for h in headers]
                lines.append("| " + " | ".join(row_vals) + " |")
            lines.append("")

        # Only facts scoped to the question belong in a deterministic answer.
        # Broad numeric profiling is useful for exploratory synthesis, but can
        # add unrelated totals/averages to a scalar, lookup, or ranking answer.
        if verified_facts:
            lines.append("#### Verified full-result facts:")
            lines.extend(self._format_verified_facts(verified_facts))
            lines.append("")

        # Insights are an optional fallback only when the query did not yield
        # explicit verified answer facts.
        if not verified_facts and insight_result and getattr(insight_result, "insights", None):
            if is_arabic:
                lines.append("#### أبرز المؤشرات والنتائج:")
            else:
                lines.append("#### Key Insights & Highlights:")
            for item in insight_result.insights[:4]:
                lines.append(f"- **{item.title}**: {item.message}")
            lines.append("")
        elif not verified_facts and analytics_result and getattr(analytics_result, "numeric_summaries", None):
            if is_arabic:
                lines.append("#### الملخص الإحصائي:")
            else:
                lines.append("#### Statistical Highlights:")
            for col, summary in list(analytics_result.numeric_summaries.items())[:3]:
                if summary.count > 0:
                    avg_fmt = f"{summary.mean:,.2f}" if summary.mean is not None else "N/A"
                    sum_fmt = f"{summary.sum:,.2f}" if summary.sum is not None else "N/A"
                    if is_arabic:
                        lines.append(f"- **{col}**: الإجمالي = `{sum_fmt}` | المتوسط = `{avg_fmt}`")
                    else:
                        lines.append(f"- **{col}**: Total = `{sum_fmt}` | Average = `{avg_fmt}`")
            lines.append("")

        return "\n".join(lines).strip()

    @staticmethod
    def resolve_report_mode(query_spec: Any = None, require_verification: bool = True) -> ReportMode:
        """Keep LLM synthesis for reasoning tasks, never as the data authority."""
        if query_spec is None:
            # Compatibility callers preserve the existing explicit behavior.
            return ReportMode.SYNTHESIS if require_verification else ReportMode.DETERMINISTIC
        analysis_type = getattr(query_spec, "analysis_type", "")
        analysis_name = analysis_type.value if hasattr(analysis_type, "value") else str(analysis_type).lower()
        complex_types = {"comparison", "trend", "root_cause", "correlation", "multi_step"}
        if getattr(query_spec, "requires_multi_step", False) or analysis_name in complex_types:
            return ReportMode.SYNTHESIS
        return ReportMode.DETERMINISTIC

    @staticmethod
    def _apply_deterministic_claim_gate(
        report: str,
        rows: list[dict[str, Any]],
        facts: Optional[list[Any]],
        sql: str,
    ) -> str:
        """Constrain every report mode to claims grounded in execution evidence."""
        from app.sql.result_verifier import result_verifier
        constrained, _, _ = result_verifier.verify_and_constrain_prose(
            report, rows=rows, facts=facts, sql=sql,
        )
        return constrained

    @staticmethod
    def _format_verified_facts(facts: list[Any], limit: int = 30) -> list[str]:
        """Render compact facts calculated before any LLM-row truncation."""
        lines = []
        for fact in facts[:limit]:
            statement = fact.get("statement") if isinstance(fact, dict) else getattr(fact, "statement", None)
            if statement:
                lines.append(f"- {statement}")
        return lines

    async def generate_report_and_chart(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        analytics_result: Optional[AnalyticsResult] = None,
        insight_result: Optional[InsightResult] = None,
        require_verification: bool = True,
        verified_facts: Optional[list[Any]] = None,
        total_result_rows: Optional[int] = None,
        query_spec: Any = None,
        verification_rows: Optional[list[dict[str, Any]]] = None,
    ) -> tuple[str, dict[str, Any]]:
        """
        Generate both the analyst report and chart suggestion in a unified step,
        leveraging instant heuristic chart resolution to eliminate redundant LLM calls.
        """
        # 1. Resolve chart heuristically / cached first (0 tokens, 0ms latency)
        chart = await self.suggest_chart(
            question=question,
            sql=sql,
            results=results,
            analytics_result=analytics_result,
            insight_result=insight_result,
        )

        # 2. Generate report (checks local SQLite cache & fast path first)
        report = await self.generate_report(
            question=question,
            sql=sql,
            results=results,
            analytics_result=analytics_result,
            insight_result=insight_result,
            require_verification=require_verification,
            verified_facts=verified_facts,
            total_result_rows=total_result_rows,
            query_spec=query_spec,
            verification_rows=verification_rows,
        )

        return report, chart

    async def generate_report(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        analytics_result: Optional[AnalyticsResult] = None,
        insight_result: Optional[InsightResult] = None,
        require_verification: bool = True,
        verified_facts: Optional[list[Any]] = None,
        total_result_rows: Optional[int] = None,
        query_spec: Any = None,
        verification_rows: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        """
        Generate a written analyst report from query results with token-optimized data payload.

        With a QuerySpec, report mode is selected centrally: scalar, count,
        lookup, aggregation, and ranking render deterministically; comparison,
        trend, root-cause, and multi-step questions use LLM synthesis. The
        ``require_verification`` argument remains for compatibility callers
        that do not yet pass a QuerySpec.
        """
        if total_result_rows is not None and total_result_rows > len(results) and verified_facts is None:
            raise ValueError(
                "Truncated report rows require verified_facts calculated from the full result set."
            )
        results_str = self._format_results_compact(results)

        # Resolve all presentation inputs before cache lookup. A report cache
        # entry is only valid for the exact prompt/model/preferences that
        # produced it, not merely for the same SQL result rows.
        try:
            from app.services.long_term_memory import long_term_memory
            prefs = long_term_memory.get_preferences("default_user") or {}
        except Exception as e:
            logger.debug("Failed to load report preferences for cache identity: %s", e)
            prefs = {}
        tone = prefs.get("reportTone", "executive")
        lang = prefs.get("language", "auto")
        dialect = prefs.get("arabicDialect", "egyptian")
        is_arabic_question = any("\u0600" <= c <= "\u06FF" for c in question)
        locale = f"ar-{dialect}" if lang == "ar" or (lang == "auto" and is_arabic_question) else lang
        report_mode = self.resolve_report_mode(query_spec, require_verification)
        provider = settings.llm_provider.lower()
        fast_models = {
            "openrouter": settings.openrouter_fast_model,
            "openai": settings.openai_fast_model,
            "groq": settings.groq_fast_model,
            "ollama": settings.ollama_fast_model,
        }
        model_id = "deterministic" if report_mode is ReportMode.DETERMINISTIC else f"{provider}:{fast_models.get(provider, 'unknown')}"
        import hashlib
        prompt_template_hash = hashlib.sha256(
            f"{REPORT_TEMPLATE}\n{REPORT_VERIFICATION_TEMPLATE}".encode("utf-8")
        ).hexdigest()[:12]
        report_cache_context = {
            "report_prompt_version": f"{settings.report_prompt_version}:conversation_v9:{prompt_template_hash}",
            "model_id": model_id,
            "locale": locale,
            "tone": tone,
            "user_context": "default_user",
        }

        # Phase 6: a fingerprint of the actual returned data (not just the
        # SQL text) — if the same question/SQL runs again and the underlying
        # rows haven't changed, skip straight to the cached report instead
        # of paying for the draft (+ verification) LLM call(s) again.
        from app.utils.cache import get_cached_report, set_cached_report
        fact_fingerprint = "\n".join(self._format_verified_facts(verified_facts or []))
        results_fingerprint = hashlib.sha256(
            f"{total_result_rows if total_result_rows is not None else len(results)}|{results_str}|{fact_fingerprint}".encode("utf-8")
        ).hexdigest()
        cached = get_cached_report(question, sql, results_fingerprint, **report_cache_context)
        if cached is not None:
            if report_mode is ReportMode.DETERMINISTIC:
                return cached
            # Caches may contain reports produced before a stricter verifier
            # rollout, so cached text never bypasses the deterministic gate.
            gate_facts = list(verified_facts or [])
            if total_result_rows is not None and total_result_rows != len(results):
                gate_facts.append({"statement": f"Total records returned: {total_result_rows}."})
            return self._apply_deterministic_claim_gate(
                cached,
                verification_rows if verification_rows is not None else results,
                gate_facts,
                sql,
            )

        # Scalar, count, lookup, aggregation, and ranking answers render from
        # rows + verified facts. The LLM is reserved for real synthesis.
        if report_mode is ReportMode.DETERMINISTIC:
            gate_facts = list(verified_facts or [])
            if total_result_rows is not None and total_result_rows != len(results):
                gate_facts.append({"statement": f"Total records returned: {total_result_rows}."})
            fast_report = self._format_conversational_report(
                question=question,
                sql=sql,
                results=results,
                verified_facts=verified_facts,
                total_result_rows=total_result_rows,
            )
            set_cached_report(question, sql, results_fingerprint, fast_report, **report_cache_context)
            return fast_report

            if len(results) == 1:
                row_item = results[0]
                if len(row_item) == 1:
                    col_name, col_val = list(row_item.items())[0]
                    if isinstance(col_val, (int, float)) or (isinstance(col_val, str) and col_val.isdigit()):
                        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
                        val_formatted = f"{col_val:,}" if isinstance(col_val, (int, float)) else str(col_val)
                        if is_arabic:
                            fast_report = f"بناءً على نتائج التحليل، إجمالي العدد الخاص بـ **{question}** هو **{val_formatted}** (العمود: `{col_name}`)."
                        else:
                            fast_report = f"The verified value for **{question}** is **{val_formatted}** (column: `{col_name}`)."
                        fast_report = self._apply_deterministic_claim_gate(
                            fast_report, verification_rows if verification_rows is not None else results,
                            verified_facts, sql,
                        )
                        set_cached_report(question, sql, results_fingerprint, fast_report, **report_cache_context)
                        return fast_report
                elif 1 < len(row_item) <= 5:
                    is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
                    items_formatted = "\n".join(f"- **{k}**: {v}" for k, v in row_item.items())
                    if is_arabic:
                        fast_report = f"بناءً على نتائج التحليل، تفاصيل السجل المطلوب كالتالي:\n{items_formatted}"
                    else:
                        fast_report = f"Based on the database analysis, the details for the requested record are as follows:\n{items_formatted}"
                    fast_report = self._apply_deterministic_claim_gate(
                        fast_report, verification_rows if verification_rows is not None else results,
                        verified_facts, sql,
                    )
                    set_cached_report(question, sql, results_fingerprint, fast_report, **report_cache_context)
                    return fast_report
            # For all simple queries with tabular results, generate rich deterministic report (0 LLM calls)
            fast_report = self._format_deterministic_report(
                question=question,
                sql=sql,
                results=results,
                analytics_result=analytics_result,
                insight_result=insight_result,
                verified_facts=verified_facts,
                total_result_rows=total_result_rows,
            )
            fast_report = self._apply_deterministic_claim_gate(
                fast_report, verification_rows if verification_rows is not None else results,
                verified_facts, sql,
            )
            set_cached_report(question, sql, results_fingerprint, fast_report, **report_cache_context)
            return fast_report

        sample_context = f"[Sample rows only — do not calculate totals from this sample]\n{results_str}"
        if insight_result and insight_result.prompt_context:
            results_json = f"{sample_context}\n\n[Insights Summary]\n{insight_result.prompt_context}"
        else:
            results_json = sample_context

        # Inject verified deterministic facts to strictly constrain narrative prose
        from app.sql.result_verifier import result_verifier
        facts = verified_facts if verified_facts is not None else result_verifier.generate_deterministic_facts(
            results, sql=sql, question=question
        )
        if facts:
            facts_summary = "\n".join(self._format_verified_facts(facts))
            results_json = f"{results_json}\n\n[Verified facts calculated from ALL {total_result_rows if total_result_rows is not None else len(results)} result rows — rely exclusively on these for totals, averages, ranges, and rankings]\n{facts_summary}"

        # Stage 1: Generate draft report
        prompt = REPORT_TEMPLATE.format(
            question=question,
            sql=sql,
            results=results_json,
        )

        try:
            if tone == "technical":
                prompt += "\n\n[USER PREFERENCE - TONE]: Adopt a Detailed Technical style with precise statistical breakdown and quantitative rigor."
            elif tone == "concise":
                prompt += "\n\n[USER PREFERENCE - TONE]: Keep the briefing extremely concise, formatting findings as brief bullet points."

            if lang == "ar" or (lang == "auto" and any("\u0600" <= c <= "\u06FF" for c in question)):
                prompt += f"\n\n[USER PREFERENCE - LANGUAGE & DIALECT]: Respond in Arabic (العربية), subtly tailoring idiomatic vocabulary toward the {dialect.upper()} Arabic dialect style while maintaining professional clarity."
            elif lang == "en":
                prompt += "\n\n[USER PREFERENCE - LANGUAGE]: Respond exclusively in English."
        except Exception as e:
            logger.debug("Failed to inject user preferences: %s", e)

        llm = get_langchain_llm(tier="fast", temperature=0.3)
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        draft_report = response.content

        # Deterministic verification always runs. It is the final authority on
        # which numeric claims can be returned, including when the optional LLM
        # verifier is disabled in production.
        verification_source_rows = verification_rows if verification_rows is not None else results
        _, pre_llm_evaluations, _ = result_verifier.verify_and_constrain_prose(
            draft_report, rows=verification_source_rows, facts=facts, sql=sql,
        )
        pre_llm_has_unverified = any(not evaluation.is_verified for evaluation in pre_llm_evaluations)

        # The LLM verifier is a high-risk synthesis refinement only; it is not
        # required for deterministic answer modes and never replaces the final
        # deterministic claim gate below.
        final_report = draft_report
        if settings.enable_report_verification and report_mode is ReportMode.SYNTHESIS:
            logger.info("Running report grounding verification LLM call.")
            verification_prompt = REPORT_VERIFICATION_TEMPLATE.format(
                results=results_json,
                draft_report=draft_report,
            )
            verified_response = await llm.ainvoke([HumanMessage(content=verification_prompt)])
            verified_text = verified_response.content

            if self._script_language_mismatch(draft_report, verified_text):
                logger.warning(
                    "Report verification stage switched language (Arabic draft -> non-Arabic "
                    "revision); discarding the verification pass and returning the draft report."
                )
            else:
                final_report = verified_text
        elif pre_llm_has_unverified:
            logger.warning("Deterministic report verification found ungrounded draft claims; constraining output.")

        constrained_report, _, _ = result_verifier.verify_and_constrain_prose(
            final_report, rows=verification_source_rows, facts=facts, sql=sql,
        )
        set_cached_report(question, sql, results_fingerprint, constrained_report, **report_cache_context)
        return constrained_report

    async def generate_conversational_response(
        self,
        question: str,
        conversation_history: str = "",
        database_context: Optional[str] = None,
    ) -> str:
        """Render a deterministic reply for the conversation/off-topic route.

        Routing already owns greetings and off-topic requests.  This method
        retains its asynchronous compatibility contract, but deliberately
        never invokes an LLM or uses conversational context to manufacture a
        general answer.
        """
        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
        if is_arabic:
            return "أنا مساعد متخصص في استعلام وتحليل قواعد البيانات. أقدر أساعدك في الجداول، المؤشرات، التقارير، وSQL."
        return "I am a database analysis assistant. I can help with tables, metrics, reports, and SQL queries."

    async def generate_no_answer_response(
        self,
        question: str,
        situation: str,
        reason: str,
        table_names: Optional[list[str]] = None,
    ) -> str:
        """
        Generate a clear, deterministic human explanation for why the question
        couldn't be answered (unanswerable from schema, no matching rows, or execution failed).
        Eliminates unnecessary LLM calls for unanswerable queries.
        """
        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
        sit_clean = situation.rstrip(".")
        reas_clean = reason.rstrip(".")

        if table_names:
            if len(table_names) > 5:
                tables_str = f" ({len(table_names)} tables in schema)"
            else:
                tables_str = f" ({', '.join(table_names)})"
        else:
            tables_str = ""

        if is_arabic:
            return f"لم يتم العثور على نتائج مطابقة لطلبك{tables_str}.\n**التفاصيل**: {sit_clean}. {reas_clean}."
        else:
            return f"Could not process or answer the requested question using the available database schema{tables_str}.\n**Details**: {sit_clean}. {reas_clean}."



    async def suggest_chart(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        analytics_result: Optional[AnalyticsResult] = None,
        insight_result: Optional[InsightResult] = None,
    ) -> dict[str, Any]:
        """Suggest whether and what type of chart to display, using rules first and optional LLM fallback."""
        if not results:
            return {"should_chart": False, "chart_type": "none", "x_column": "", "y_column": "", "reason": "No data"}

        # Check cache first
        from app.utils.cache import get_cached_chart, set_cached_chart
        cached_chart = get_cached_chart(sql)
        if cached_chart is not None:
            return cached_chart

        # 1. Try rule-based heuristic first (free/instant)
        heuristic_suggestion = self._suggest_chart_heuristically(question, sql, results, analytics_result)
        if heuristic_suggestion is not None:
            logger.info(f"Chart suggestion resolved via heuristic: {heuristic_suggestion['chart_type']} ({heuristic_suggestion['reason']})")
            set_cached_chart(sql, heuristic_suggestion)
            return heuristic_suggestion

        # 2. Check if LLM chart suggestion is enabled
        if not settings.enable_chart_suggestion:
            suggestion = {"should_chart": False, "chart_type": "none", "x_column": "", "y_column": "", "reason": "Chart suggestion disabled"}
            set_cached_chart(sql, suggestion)
            return suggestion

        # 3. Fallback to LLM suggestion
        columns = list(results[0].keys())
        prompt = CHART_SUGGESTION_TEMPLATE.format(
            question=question,
            sql=sql,
            columns=", ".join(columns),
            row_count=len(results),
        )

        try:
            logger.info("Running chart suggestion LLM call.")
            llm = get_langchain_llm(tier="fast", temperature=0.1)
            from langchain_core.messages import SystemMessage, HumanMessage
            messages = [
                SystemMessage(content="You are a data visualization expert."),
                HumanMessage(content=prompt)
            ]
            response = await llm.ainvoke(messages)

            json_str = extract_json_text(response.content)
            chart_suggestion = json.loads(json_str)
            set_cached_chart(sql, chart_suggestion)
            return chart_suggestion
        except Exception as e:
            logger.warning("Chart suggestion LLM call failed: %s", e)
            fallback = {"should_chart": False, "chart_type": "none", "x_column": "", "y_column": "", "reason": "Could not parse response"}
            set_cached_chart(sql, fallback)
            return fallback

    def _suggest_chart_heuristically(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        analytics_result: Optional[AnalyticsResult] = None,
    ) -> dict[str, Any] | None:
        """Heuristic check to determine a suitable chart without LLM latency/cost."""
        if not results or len(results) <= 1:
            return {"should_chart": False, "chart_type": "none", "x_column": "", "y_column": "", "reason": "Not enough rows to plot"}

        columns = list(results[0].keys())
        if len(columns) < 2:
            return {"should_chart": False, "chart_type": "none", "x_column": "", "y_column": "", "reason": "Need at least two columns"}

        numeric_cols = []
        date_cols = []
        text_cols = []

        if analytics_result and analytics_result.dataset:
            ds = analytics_result.dataset
            numeric_cols = ds.numeric_columns
            date_cols = ds.date_columns
            text_cols = ds.categorical_columns
        else:
            # Sample values from the first few rows
            sample_rows = results[:5]
            for col in columns:
                is_num = True
                is_date = False
                col_lower = col.lower()

                if any(x in col_lower for x in ("date", "year", "month", "day", "time", "created_at", "updated_at")):
                    is_date = True
                    is_num = False
                else:
                    for row in sample_rows:
                        val = row.get(col)
                        if val is None:
                            continue
                        if not isinstance(val, (int, float)):
                            try:
                                float(str(val))
                            except ValueError:
                                is_num = False
                                break

                if is_num:
                    numeric_cols.append(col)
                elif is_date:
                    date_cols.append(col)
                else:
                    text_cols.append(col)

        # If no numeric column, we can't chart
        if not numeric_cols:
            return {"should_chart": False, "chart_type": "none", "x_column": "", "y_column": "", "reason": "No numeric metric to plot"}

        # Rule 1: Time series (Date + Numeric) -> Line Chart
        if date_cols:
            return {
                "should_chart": True,
                "chart_type": "line",
                "x_column": date_cols[0],
                "y_column": numeric_cols[0],
                "reason": "Rule-based: Detected time-series trend column"
            }

        # Rule 2: Category + Numeric -> Bar Chart
        if text_cols:
            return {
                "should_chart": True,
                "chart_type": "bar",
                "x_column": text_cols[0],
                "y_column": numeric_cols[0],
                "reason": "Rule-based: Categorical comparison"
            }

        # Rule 3: Multiple Numeric columns -> Scatter Plot
        if len(numeric_cols) >= 2:
            s_res = {
                "should_chart": True,
                "chart_type": "scatter",
                "x_column": numeric_cols[1],
                "y_column": numeric_cols[0],
                "reason": "Rule-based: Numeric relationship comparison"
            }
        else:
            s_res = {
                "should_chart": True,
                "chart_type": "bar",
                "x_column": columns[0],
                "y_column": numeric_cols[0],
                "reason": "Rule-based fallback: Bar chart for query results"
            }

        try:
            from app.services.long_term_memory import long_term_memory
            prefs = long_term_memory.get_preferences("default_user") or {}
            pref_chart = prefs.get("preferredChart")
            if pref_chart and pref_chart in ("bar", "line", "pie", "scatter") and pref_chart != "auto":
                s_res["chart_type"] = pref_chart
                s_res["reason"] += f" (Overridden by User Settings: {pref_chart})"
        except Exception:
            pass

        return s_res
