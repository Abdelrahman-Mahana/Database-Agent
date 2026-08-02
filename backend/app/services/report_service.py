"""Report generation service — turns raw SQL results into analyst reports."""
import json
import logging
from typing import Any, Optional

from app.core.config import settings
from app.llm.model import get_langchain_llm
from app.llm.prompts import REPORT_TEMPLATE, CHART_SUGGESTION_TEMPLATE, REPORT_VERIFICATION_TEMPLATE, NO_ANSWER_RESPONSE_TEMPLATE
from app.services.sql_service import SchemaService
from app.utils.text_processor import extract_json_text
from app.analytics.models import AnalyticsResult, InsightResult

logger = logging.getLogger(__name__)


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

    async def generate_report(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        analytics_result: Optional[AnalyticsResult] = None,
        insight_result: Optional[InsightResult] = None,
        require_verification: bool = True,
    ) -> str:
        """
        Generate a written analyst report from query results with token-optimized data payload.

        `require_verification` gates the (costly) Stage 2 fact-check/citation
        pass - a second full LLM call over the draft. Callers should set this
        to False for simple lookup/count/aggregation/ranking questions, where
        a single-query, single-fact answer has little room for the kind of
        drift (mislabeled figures, wrong entity names) that verification
        catches - and True for comparison/trend/root-cause/multi-step
        questions, where synthesizing across multiple figures is exactly
        where that drift tends to show up. This roughly halves LLM report
        cost on simple questions, which are the majority of traffic.
        """
        results_str = self._format_results_compact(results)

        # Phase 6: a fingerprint of the actual returned data (not just the
        # SQL text) — if the same question/SQL runs again and the underlying
        # rows haven't changed, skip straight to the cached report instead
        # of paying for the draft (+ verification) LLM call(s) again.
        import hashlib
        from app.utils.cache import get_cached_report, set_cached_report
        results_fingerprint = hashlib.sha256(results_str.encode("utf-8")).hexdigest()
        cached = get_cached_report(question, sql, results_fingerprint)
        if cached is not None:
            return cached

        if insight_result and insight_result.prompt_context:
            results_json = f"{results_str}\n\n[Insights Summary]\n{insight_result.prompt_context}"
        else:
            results_json = results_str

        # Stage 1: Generate draft report
        prompt = REPORT_TEMPLATE.format(
            question=question,
            sql=sql,
            results=results_json,
        )

        try:
            from app.services.long_term_memory import long_term_memory
            prefs = long_term_memory.get_preferences("default_user") or {}
            tone = prefs.get("reportTone", "executive")
            if tone == "technical":
                prompt += "\n\n[USER PREFERENCE - TONE]: Adopt a Detailed Technical style with precise statistical breakdown and quantitative rigor."
            elif tone == "concise":
                prompt += "\n\n[USER PREFERENCE - TONE]: Keep the briefing extremely concise, formatting findings as brief bullet points."
            
            lang = prefs.get("language", "auto")
            dialect = prefs.get("arabicDialect", "egyptian")
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

        # Stage 2: Verify facts and add citations (if enabled AND warranted)
        if settings.enable_report_verification and require_verification:
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
                set_cached_report(question, sql, results_fingerprint, draft_report)
                return draft_report
            set_cached_report(question, sql, results_fingerprint, verified_text)
            return verified_text

        set_cached_report(question, sql, results_fingerprint, draft_report)
        return draft_report

    async def generate_no_answer_response(
        self,
        question: str,
        situation: str,
        reason: str,
        table_names: Optional[list[str]] = None,
    ) -> str:
        """
        Generate a short, honest, human-voiced explanation for why the question
        couldn't be answered (unanswerable from schema, no matching rows, or
        execution failed after repair attempts) - instead of a flat hardcoded
        English string regardless of what language the user asked in.

        Falls back to a plain (still situation-specific) string if the LLM
        call itself fails, so this never blocks the response.
        """
        try:
            prompt = NO_ANSWER_RESPONSE_TEMPLATE.format(
                question=question,
                situation=situation,
                reason=reason,
                table_names=", ".join(table_names) if table_names else "N/A",
            )
            llm = get_langchain_llm(tier="fast", temperature=0.3)
            from langchain_core.messages import HumanMessage
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return response.content
        except Exception as e:
            logger.warning("No-answer humanization LLM call failed, falling back to plain text: %s", e)
            return f"{situation}: {reason}"

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
