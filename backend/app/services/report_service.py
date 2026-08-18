"""Report generation service — turns raw SQL results into analyst reports."""
import json
import logging
from typing import Any, Optional

from app.config.settings import settings
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

    def _format_deterministic_report(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        analytics_result: Optional[AnalyticsResult] = None,
        insight_result: Optional[InsightResult] = None,
    ) -> str:
        """Format a rich, executive markdown report directly from query results and analytics without calling LLM."""
        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
        lines = []

        # 1. Summary Title
        if is_arabic:
            lines.append(f"### ملخص نتائج الاستعلام: **{question}**\n")
            lines.append(f"تم تنفيذ الاستعلام بنجاح واسترجاع **{len(results)}** سجل:")
        else:
            lines.append(f"### Query Results Summary: **{question}**\n")
            lines.append(f"The query executed successfully and returned **{len(results)}** records:")

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

        # 3. Analytics Insights highlights (if available)
        if insight_result and getattr(insight_result, "insights", None):
            if is_arabic:
                lines.append("#### أبرز المؤشرات والنتائج:")
            else:
                lines.append("#### Key Insights & Highlights:")
            for item in insight_result.insights[:4]:
                lines.append(f"- **{item.title}**: {item.message}")
            lines.append("")
        elif analytics_result and getattr(analytics_result, "numeric_summaries", None):
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

    async def generate_conversational_data_response(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        conversation_history: str = "",
        analytics_result: Optional[AnalyticsResult] = None,
        insight_result: Optional[InsightResult] = None,
    ) -> str:
        """Turn database results into a natural conversational answer, not a fixed report."""
        if not results:
            return await self.generate_no_answer_response(
                question=question,
                situation="The database query executed successfully but returned no matching rows.",
                reason="No records matched the request.",
            )

        import json
        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
        recent = conversation_history[-3000:] if conversation_history else "No previous conversation."
        result_text = json.dumps(results[:40], ensure_ascii=False, separators=(",", ":"), default=str)
        insights_text = ""
        if insight_result and getattr(insight_result, "insights", None):
            insights_text = "\n".join(f"- {i.title}: {i.message}" for i in insight_result.insights[:4])

        prompt = f"""
You are the final response layer of a conversational database assistant.
Answer the user's question using the database results below.

User question:
{question}

Recent conversation:
{recent}

Database results (ground truth):
{result_text}

Useful deterministic insights (optional):
{insights_text or 'None'}

Rules:
- Speak naturally like a human teammate, not like a generated report.
- Directly answer what the user asked.
- Do not mention SQL, tools, routing, schema grounding, prompts, or internal steps.
- Do not invent facts that are not supported by the results.
- Do not force a title, markdown table, bullet list, or fixed template unless it genuinely helps.
- Preserve the user's language and tone.
- Use the conversation context when a follow-up depends on earlier turns.
- For a simple numeric question, answer simply and naturally.
- For a richer analytical question, briefly explain the important takeaway and offer the most relevant context, without turning it into a formal report.
- When the result is ambiguous, say what is ambiguous instead of pretending certainty.

{"Respond entirely in natural Egyptian Arabic." if is_arabic else "Respond entirely in natural English."}
Return only the user-facing answer.
"""
        try:
            llm = get_langchain_llm(tier="fast", temperature=0.35)
            from langchain_core.messages import HumanMessage
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return str(response.content).strip()
        except Exception as exc:
            logger.warning("Conversational data response generation failed: %s", exc)
            if len(results) == 1 and len(results[0]) == 1:
                value = next(iter(results[0].values()))
                return f"النتيجة هي {value}." if is_arabic else f"The result is {value}."
            return (
                f"لقيت {len(results)} نتيجة مطابقة لطلبك." if is_arabic
                else f"I found {len(results)} matching results."
            )

    async def generate_report_and_chart(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        analytics_result: Optional[AnalyticsResult] = None,
        insight_result: Optional[InsightResult] = None,
        require_verification: bool = True,
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

        # Safe fast-path for standard analytical queries (1 LLM call total per question)
        if not require_verification:
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
                            fast_report = f"Based on the database analysis, the total result for **{question}** is **{val_formatted}** (Column: `{col_name}`)."
                        set_cached_report(question, sql, results_fingerprint, fast_report)
                        return fast_report
                elif 1 < len(row_item) <= 5:
                    is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
                    items_formatted = "\n".join(f"- **{k}**: {v}" for k, v in row_item.items())
                    if is_arabic:
                        fast_report = f"بناءً على نتائج التحليل، تفاصيل السجل المطلوب كالتالي:\n{items_formatted}"
                    else:
                        fast_report = f"Based on the database analysis, the details for the requested record are as follows:\n{items_formatted}"
                    set_cached_report(question, sql, results_fingerprint, fast_report)
                    return fast_report
            # For all simple queries with tabular results, generate rich deterministic report (0 LLM calls)
            fast_report = self._format_deterministic_report(
                question=question,
                sql=sql,
                results=results,
                analytics_result=analytics_result,
                insight_result=insight_result,
            )
            set_cached_report(question, sql, results_fingerprint, fast_report)
            return fast_report

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

    async def generate_conversational_response(
        self,
        question: str,
        conversation_history: str = "",
        database_context: Optional[str] = None,
    ) -> str:
        """
        Answer a normal conversational/general question without SQL, schema grounding,
        analytics, or chart generation.
        """
        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
        context = conversation_history[-4000:] if conversation_history else "No prior conversation."
        db_note = database_context or "A database is connected, but the user did not ask for database data."

        prompt = f"""You are a friendly conversational assistant that also happens to be connected to a database.
The user message does NOT require SQL or database data retrieval.

User message:
{question}

Recent conversation:
{context}

Database context:
{db_note}

Rules:
- Answer the user's actual question naturally and directly.
- Do not generate SQL.
- Do not discuss internal tools, routing, planning, schema grounding, or agent steps.
- Do not invent database facts.
- If the question is general knowledge, answer it normally.
- If the question is ambiguous, state what is unclear and ask one concise clarification.
- If the user is simply chatting, respond naturally and warmly.
- Never force the conversation back to database analytics unless the user clearly asks for that.
- Match the user's language and dialect.
{"Respond entirely in Arabic and use natural Egyptian Arabic." if is_arabic else "Respond entirely in English."}
Return only the final user-facing response."""
        try:
            llm = get_langchain_llm(tier="fast", temperature=0.3)
            from langchain_core.messages import HumanMessage
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            return str(response.content).strip()
        except Exception as exc:
            logger.warning("Conversational response generation failed: %s", exc)
            if is_arabic:
                return "أكيد، أقدر أساعدك. وضّح لي السؤال أو النقطة اللي حابب تعرف عنها أكثر."
            return "Sure. I can help with that. Tell me a little more about what you’d like to know."

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
            return f"جربت أجيب لك على سؤالك، لكن ما لقيتش بيانات مطابقة{tables_str}. {sit_clean}. {reas_clean}."
        else:
            return f"I checked the available data, but I couldn’t find a matching answer{tables_str}. {sit_clean}. {reas_clean}."



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
