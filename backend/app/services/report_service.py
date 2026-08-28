"""Report generation service — turns raw SQL results into analyst reports."""
import json
import logging
import re
from enum import Enum
from typing import Any, Optional

from app.core.config.settings import settings
from app.agent.llm.model import get_langchain_llm
from app.agent.llm.prompts import (
    REPORT_TEMPLATE,
    EVIDENCE_BASED_REPORT_TEMPLATE,
    CHART_SUGGESTION_TEMPLATE,
    REPORT_VERIFICATION_TEMPLATE,
    NO_ANSWER_RESPONSE_TEMPLATE,
)
from app.services.sql_service import SchemaService
from app.utils.text_processor import extract_json_text, COMPLEX_ANALYSIS_TYPES
from app.services.analytics.models import AnalyticsResult, InsightResult
from app.services.analysis.models import AnalysisResult

logger = logging.getLogger(__name__)


class ReportMode(str, Enum):
    """Whether the response is rendered from verified evidence or synthesized."""
    DETERMINISTIC = "deterministic"
    SYNTHESIS = "synthesis"


class ReportService:
    """Generates analyst reports and chart suggestions from query results."""

    def __init__(self):
        self.schema_service = SchemaService()


    def _format_results_compact(self, results: list[dict[str, Any]], max_rows: int = 8) -> str:
        """Format results as minified JSON with compacted field values to strictly bound prompt tokens."""
        if not results:
            return "[]"
        compacted = []
        for r in results[:max_rows]:
            row_dict = {}
            for k, v in r.items():
                if v is None:
                    continue
                v_str = str(v)
                if len(v_str) > 60:
                    v_str = v_str[:57] + "..."
                row_dict[k] = v_str
            compacted.append(row_dict)
        out = json.dumps(compacted, separators=(',', ':'), default=str)
        if len(out) > 2500:
            out = out[:2500] + "... [truncated]"
        return out

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
    def _humanize_identifier(name: str, is_arabic: bool = False) -> str:
        name_clean = (name or "value").split(".")[-1].strip().lower()
        arabic_mappings = {
            "sum": "إجمالي القيمة",
            "count": "العدد الإجمالي",
            "avg": "المتوسط",
            "min": "الحد الأدنى",
            "max": "الحد الأقصى",
            "total_revenue": "إجمالي الإيرادات",
            "total_amount": "إجمالي القيمة",
            "amount_total": "إجمالي الفاتورة",
            "amount_untaxed": "المبلغ قبل الضريبة",
            "amount_tax": "قيمة الضريبة",
            "amount_residual": "المبلغ المتبقي",
            "invoice_date": "تاريخ الفاتورة",
            "invoice_number": "رقم الفاتورة",
            "invoice_id": "رقم الفاتورة",
            "invoice_count": "عدد الفواتير",
            "total_invoices": "إجمالي الفواتير",
            "order_count": "عدد الطلبات",
            "partner_id": "العميل",
            "name": "الاسم",
            "customer_name": "اسم العميل",
            "client_name": "اسم العميل",
            "partner_name": "اسم العميل / الشريك",
            "patient_name": "اسم المريض",
            "doctor_name": "اسم الطبيب",
            "product_name": "اسم الصنف / المنتج",
            "service_name": "اسم الخدمة",
            "clinic_name": "اسم العيادة",
            "date": "التاريخ",
            "create_date": "تاريخ الإنشاء",
            "write_date": "تاريخ التعديل",
            "month": "الشهر",
            "year": "السنة",
            "state": "الحالة",
            "status": "الحالة",
            "invoice_status": "حالة الفاتورة",
            "payment_state": "حالة السداد",
            "move_type": "نوع الفاتورة",
            "price_unit": "سعر الوحدة",
            "quantity": "الكمية",
            "qty": "الكمية",
            "price_subtotal": "الإجمالي الفرعي",
            "price_total": "الإجمالي الكلي",
            "discount": "الخصم",
            "balance": "الرصيد",
            "cost": "التكلفة",
            "service_cost": "تكلفة الخدمة",
            "company_id": "الشركة",
            "company_name": "اسم الشركة",
        }
        if is_arabic and name_clean in arabic_mappings:
            return arabic_mappings[name_clean]
        return (name or "value").split(".")[-1].replace("_", " ").strip() or "value"

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return f"{value:,}"
        if isinstance(value, float):
            return f"{value:,.2f}".rstrip("0").rstrip(".")
        return str(value)

    def _format_smart_rows_summary(self, results: list[dict[str, Any]], is_arabic: bool, max_rows: int = 5) -> list[str]:
        if not results:
            return []

        row_sample = results[0]
        
        # 1. Identify primary name/title column
        name_priority = [
            "customer_name", "client_name", "partner_name", "patient_name", "doctor_name",
            "product_name", "service_name", "name", "full_name", "display_name",
            "title", "label", "subject", "description",
            "email", "username", "code", "reference", "ref"
        ]
        primary_col = None
        for cand in name_priority:
            for k in row_sample.keys():
                if k.lower() == cand or (cand in k.lower() and not k.lower().endswith("_id")):
                    if any(r.get(k) and str(r.get(k)).strip() for r in results[:max_rows]):
                        primary_col = k
                        break
            if primary_col:
                break

        # 2. Select secondary informative columns (dates, counts, amounts, ID)
        skip_terms = {"password", "token", "hash", "secret", "color", "active", "sequence", "write_uid", "create_uid", "message_main_attachment_id"}
        secondary_cols = []
        for k in row_sample.keys():
            if k == primary_col or k.lower() in skip_terms:
                continue
            vals = [r.get(k) for r in results[:max_rows] if r.get(k) is not None]
            if vals and any(str(v).strip() for v in vals):
                secondary_cols.append(k)

        def _col_importance(c: str) -> int:
            cl = c.lower()
            if any(x in cl for x in ("number", "code", "ref", "id")):
                return 100
            if "date" in cl or "time" in cl:
                return 90
            if any(x in cl for x in ("amount", "total", "price", "count", "sum", "quantity", "qty", "balance", "cost")):
                return 85
            if any(x in cl for x in ("status", "state", "type", "category", "stage")):
                return 80
            if any(x in cl for x in ("phone", "mobile", "email", "city", "country")):
                return 75
            return 10

        secondary_cols.sort(key=_col_importance, reverse=True)
        chosen_sec = secondary_cols[:4]

        lines = []
        for index, row in enumerate(results[:max_rows], start=1):
            if primary_col and row.get(primary_col) and str(row.get(primary_col)).strip():
                main_val = str(row.get(primary_col)).strip()
                details = []
                for sec in chosen_sec:
                    v = row.get(sec)
                    if v is not None and str(v).strip():
                        label = self._humanize_identifier(sec, is_arabic=is_arabic)
                        fmt_val = self._format_value(v)
                        details.append(f"{label}: **{fmt_val}**")
                det_str = f" — {', '.join(details)}" if details else ""
                lines.append(f"{index}. **{main_val}**{det_str}")
            else:
                useful = []
                for k in [c for c in (chosen_sec or list(row.keys())) if row.get(c) is not None][:4]:
                    label = self._humanize_identifier(k, is_arabic=is_arabic)
                    fmt_val = self._format_value(row.get(k))
                    useful.append(f"{label}: **{fmt_val}**")
                if useful:
                    lines.append(f"{index}. {', '.join(useful)}")
                else:
                    lines.append(f"{index}. {is_arabic and 'سجل رقم' or 'Record'} #{row.get('id', index)}")

        return lines

    def _format_lookup_report(self, question: str, results: list[dict[str, Any]], is_arabic: bool) -> str:
        """Archetype 1: Lookup (Direct Answer + Details)."""
        if not results:
            return "الخلاصة: لم يتم العثور على السجل المطلوب." if is_arabic else "Direct Answer: No matching record found."
        first_row = results[0]
        summary_items = [f"{self._humanize_identifier(k, is_arabic=is_arabic)}: **{self._format_value(v)}**" for k, v in list(first_row.items())[:4]]
        details_text = "، ".join(summary_items)
        if is_arabic:
            return (
                f"الخلاصة: {details_text}.\n\n"
                f"التفاصيل:\n" + "\n".join(f"- {self._humanize_identifier(k, is_arabic=is_arabic)}: {self._format_value(v)}" for k, v in first_row.items())
            )
        return (
            f"Direct Answer: {details_text}.\n\n"
            f"Details:\n" + "\n".join(f"- {self._humanize_identifier(k, is_arabic=is_arabic)}: {self._format_value(v)}" for k, v in first_row.items())
        )

    def _format_metric_report(
        self,
        question: str,
        results: list[dict[str, Any]],
        verified_facts: Optional[list[Any]] = None,
        analysis_result: Optional[AnalysisResult] = None,
        sql: str = "",
        is_arabic: bool = True,
    ) -> str:
        """Archetype 2: Metric (Number + Calculation Method)."""
        metric_val = "N/A"
        metric_label = "المؤشر" if is_arabic else "Metric"
        if results and len(results) >= 1:
            first_row = results[0]
            for k, v in first_row.items():
                if isinstance(v, (int, float)) or (isinstance(v, str) and not v.isalpha()):
                    metric_label = self._humanize_identifier(k, is_arabic=is_arabic)
                    metric_val = self._format_value(v)
                    break
            if metric_val == "N/A" and first_row:
                k, v = next(iter(first_row.items()))
                metric_label = self._humanize_identifier(k, is_arabic=is_arabic)
                metric_val = self._format_value(v)

        if is_arabic:
            if any(term in question for term in ("إيراد", "ايراد", "إيرادات", "مبيعات", "مبلغ", "فلوس")):
                if metric_label in ("إجمالي القيمة", "sum", "المؤشر", "value"):
                    metric_label = "إجمالي الإيرادات"

        calc_method = []
        sql_up = sql.upper()
        if "COUNT(" in sql_up:
            calc_method.append("حساب إجمالي العدد (COUNT)" if is_arabic else "Count aggregation (COUNT)")
        elif "SUM(" in sql_up:
            calc_method.append("حساب إجمالي المجموع (SUM)" if is_arabic else "Sum aggregation (SUM)")
        elif "AVG(" in sql_up:
            calc_method.append("حساب المتوسط الحسابي (AVG)" if is_arabic else "Average calculation (AVG)")

        row_count = len(results)
        calc_scope = f"تم الحساب عبر استعلام مباشر من قاعدة البيانات ({row_count} نتيجة)" if is_arabic else f"Calculated directly from database ({row_count} rows)"
        if calc_method:
            calc_scope = f"{calc_method[0]} عبر قاعدة البيانات" if is_arabic else f"{calc_method[0]} from database"

        if is_arabic:
            explanation_context = f"العدد الإجمالي المسجل في جدول البيانات هو **{metric_val}** سجل." if "COUNT" in sql_up else f"القيمة المحتسبة بناءً على البيانات هي **{metric_val}**."
            return (
                f"الخلاصة: {metric_label} هو **{metric_val}**.\n\n"
                f"طريقة الحساب:\n"
                f"- **المعنى وسياق النتيجة**: {explanation_context}\n"
                f"- **العملية وطريقة الحساب**: {calc_scope}.\n"
                f"- **دقة وموثوقية النتيجة**: استعلام قطعي مباشر ومطابق تماماً لسجلات قاعدة البيانات بدون أي تقريب أو تخمين.\n\n"
                f"💡 **اقتراحات للتحليل التالي**:\n"
                f"- يمكنك طلب توزيع هذه الأرقام حسب الفترة الزمنية (شهرياً/سنوياً) أو حسب الفئات والعملاء.\n"
                f"- أو استعراض عينة من السجلات بالتفصيل (مثلاً: «**اعرض أول 5 سجلات**»)."
            )
        
        explanation_en = f"The total count of active records recorded in the table is **{metric_val}**." if "COUNT" in sql_up else f"The calculated aggregate metric from the database is **{metric_val}**."
        return (
            f"Direct Metric: `{metric_label}` is **{metric_val}**.\n\n"
            f"Calculation Details:\n"
            f"- **Business Context**: {explanation_en}\n"
            f"- **Method**: {calc_scope}.\n"
            f"- **Data Grounding**: Deterministic aggregation directly executed against database records.\n\n"
            f"💡 **Suggested Next Steps**:\n"
            f"- Filter or break down by date range or status (e.g. «**Break down by month**» or «**Group by state**»).\n"
            f"- Inspect individual record attributes (e.g. «**Show top 5 sample rows**»)."
        )

    def _format_comparison_report(
        self,
        question: str,
        results: list[dict[str, Any]],
        analysis_result: Optional[AnalysisResult] = None,
        is_arabic: bool = True,
    ) -> str:
        """Archetype 3: Comparison (A, B, Difference, Winner)."""
        if len(results) >= 2:
            row_a = results[0]
            row_b = results[1]
            label_a = list(row_a.values())[0] if row_a else "A"
            val_a = list(row_a.values())[1] if len(row_a) > 1 else list(row_a.values())[0]
            label_b = list(row_b.values())[0] if row_b else "B"
            val_b = list(row_b.values())[1] if len(row_b) > 1 else list(row_b.values())[0]

            diff_str = "N/A"
            winner_str = str(label_a)
            if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
                diff = abs(val_a - val_b)
                pct = (diff / val_b * 100) if val_b else 0
                winner = label_a if val_a >= val_b else label_b
                diff_str = f"{diff:,.2f} ({pct:.1f}%)" if pct else f"{diff:,.2f}"
                winner_str = str(winner)

            if is_arabic:
                return (
                    f"الخلاصة: مقارنة بين **{label_a}** و **{label_b}** تظهر تفوق **{winner_str}**.\n\n"
                    f"مقارنة الأطراف:\n"
                    f"- الطرف الأول ({label_a}): **{self._format_value(val_a)}**\n"
                    f"- الطرف الثاني ({label_b}): **{self._format_value(val_b)}**\n"
                    f"- الفارق (Difference): **{diff_str}**\n"
                    f"- المتصدر (Winner): **{winner_str}**"
                )
            return (
                f"Comparison Summary: Comparison between **{label_a}** and **{label_b}** shows **{winner_str}** leading.\n\n"
                f"Breakdown:\n"
                f"- Entity A ({label_a}): **{self._format_value(val_a)}**\n"
                f"- Entity B ({label_b}): **{self._format_value(val_b)}**\n"
                f"- Difference: **{diff_str}**\n"
                f"- Winner / Leader: **{winner_str}**"
            )

        return self._format_smart_rows_summary(results, is_arabic=is_arabic)

    def _format_trend_report(
        self,
        question: str,
        results: list[dict[str, Any]],
        analysis_result: Optional[AnalysisResult] = None,
        is_arabic: bool = True,
    ) -> str:
        """Archetype 4: Trend (Overall trend, Peak, Lowest, Growth)."""
        metrics = analysis_result.metrics if analysis_result else {}
        trend_dir = metrics.get("trend_direction", metrics.get("direction", "صاعد (Upward)" if is_arabic else "upward"))
        growth_rate = metrics.get("growth_rate_pct", metrics.get("overall_growth_pct", metrics.get("growth_pct", "N/A")))
        peak = metrics.get("peak", metrics.get("max_value", "N/A"))
        lowest = metrics.get("lowest", metrics.get("min_value", "N/A"))

        if (peak == "N/A" or peak is None) and results:
            for col, val in results[0].items():
                if isinstance(val, (int, float)):
                    vals = [r[col] for r in results if isinstance(r.get(col), (int, float))]
                    if vals:
                        peak = f"{max(vals):,.2f}"
                        lowest = f"{min(vals):,.2f}"
                        if vals[0] != 0:
                            growth = (vals[-1] - vals[0]) / vals[0] * 100
                            growth_rate = f"{growth:+.1f}%"
                            trend_dir = "صاعد (Upward)" if growth > 0 else ("هابط (Downward)" if growth < 0 else "مستقر (Stable)")

        if is_arabic:
            return (
                f"الخلاصة: المسار العام يوضح اتجاهاً **{trend_dir}**.\n\n"
                f"تحليل المسار الزمني:\n"
                f"- الاتجاه العام (Overall Trend): **{trend_dir}**\n"
                f"- أعلى نقطة (Peak): **{peak}**\n"
                f"- أدنى نقطة (Lowest): **{lowest}**\n"
                f"- معدل النمو (Growth Rate): **{growth_rate}**"
            )
        return (
            f"Trend Summary: The overall trajectory is **{trend_dir}**.\n\n"
            f"Time-Series Analysis:\n"
            f"- Overall Trend: **{trend_dir}**\n"
            f"- Peak: **{peak}**\n"
            f"- Lowest: **{lowest}**\n"
            f"- Growth Rate: **{growth_rate}**"
        )

    def _format_root_cause_report(
        self,
        question: str,
        results: list[dict[str, Any]],
        analysis_result: Optional[AnalysisResult] = None,
        is_arabic: bool = True,
    ) -> str:
        """Archetype 5: Root Cause (Main finding, Contributors, Evidence, Limitations)."""
        findings = analysis_result.findings if analysis_result and analysis_result.findings else ["تم رصد انحراف ملحوظ في النتائج" if is_arabic else "Variance observed in results"]
        evidence = analysis_result.evidence if analysis_result and analysis_result.evidence else [f"مبني على {len(results)} سجلات" if is_arabic else f"Based on {len(results)} records"]
        limitations = analysis_result.limitations if analysis_result and analysis_result.limitations else ["التحليل مقيد بالبيانات المخزنة في قاعدة البيانات" if is_arabic else "Analysis bounded by stored records"]

        main_find = findings[0] if findings else "N/A"
        contributors = findings[1:] if len(findings) > 1 else [evidence[0] if evidence else "N/A"]

        if is_arabic:
            contrib_str = "\n".join(f"- {c}" for c in contributors)
            ev_str = "\n".join(f"- {e}" for e in evidence[:3])
            lim_str = "\n".join(f"- {l}" for l in limitations[:2])
            return (
                f"الخلاصة: {main_find}.\n\n"
                f"تحليل الأسباب والمساهمين:\n"
                f"- النتيجة الرئيسية (Main Finding): {main_find}\n"
                f"- أكبر المساهمين (Contributors):\n{contrib_str}\n"
                f"- الأدلة الداعمة (Evidence):\n{ev_str}\n"
                f"- حدود التحليل (Limitations):\n{lim_str}"
            )
        contrib_str = "\n".join(f"- {c}" for c in contributors)
        ev_str = "\n".join(f"- {e}" for e in evidence[:3])
        lim_str = "\n".join(f"- {l}" for l in limitations[:2])
        return (
            f"Root Cause Summary: {main_find}.\n\n"
            f"Decomposition & Attribution:\n"
            f"- Main Finding: {main_find}\n"
            f"- Top Contributors:\n{contrib_str}\n"
            f"- Supporting Evidence:\n{ev_str}\n"
            f"- Limitations:\n{lim_str}"
        )

    def _format_exploratory_report(
        self,
        question: str,
        results: list[dict[str, Any]],
        analysis_result: Optional[AnalysisResult] = None,
        insight_result: Optional[InsightResult] = None,
        is_arabic: bool = True,
    ) -> str:
        """Archetype 6: Exploratory Analysis (Overview, Key findings, Patterns, Anomalies, Data quality, Recommendations)."""
        metrics = analysis_result.metrics if analysis_result else {}
        findings = analysis_result.findings if analysis_result else []
        warnings = analysis_result.warnings if analysis_result else []
        recs = analysis_result.recommendations if analysis_result else []

        row_c = len(results)
        col_c = len(results[0]) if results else 0
        overview = f"{row_c} سجل عبر {col_c} حقول" if is_arabic else f"{row_c} records across {col_c} fields"
        key_f = "\n".join(f"- {f}" for f in findings[:3]) if findings else ("- توزيع البيانات منتظم" if is_arabic else "- Regular distribution")
        patterns = "\n".join(f"- {e}" for e in (analysis_result.evidence if analysis_result else [])[:2]) if (analysis_result and analysis_result.evidence) else ("- تم فحص الأنماط الرئيسية" if is_arabic else "- Main patterns verified")
        anomalies = "\n".join(f"- {w}" for w in warnings[:2]) if warnings else ("- لا توجد قيم شاذة حرجة" if is_arabic else "- No critical anomalies detected")
        dq = "100% (سجلات مكتملة)" if is_arabic else "100% (Complete records)"
        recommendations = "\n".join(f"- {r}" for r in recs[:2]) if recs else ("- الاستمرار في رصد المؤشرات الدورية" if is_arabic else "- Continue periodic monitoring")

        if is_arabic:
            return (
                f"الخلاصة: اكتمل الاستكشاف الشامل للبيانات بنجاح.\n\n"
                f"التقرير الاستكشافي الشامل:\n"
                f"- نظرة عامة (Overview): {overview}\n"
                f"- أهم النتائج (Key Findings):\n{key_f}\n"
                f"- الأنماط (Patterns):\n{patterns}\n"
                f"- القيم الشاذة (Anomalies):\n{anomalies}\n"
                f"- جودة البيانات (Data Quality): {dq}\n"
                f"- التوصيات (Recommendations):\n{recommendations}"
            )
        return (
            f"Exploratory Summary: Comprehensive data exploration completed.\n\n"
            f"Comprehensive Profile:\n"
            f"- Overview: {overview}\n"
            f"- Key Findings:\n{key_f}\n"
            f"- Patterns:\n{patterns}\n"
            f"- Anomalies:\n{anomalies}\n"
            f"- Data Quality: {dq}\n"
            f"- Recommendations:\n{recommendations}"
        )

    def _format_conversational_report(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        verified_facts: Optional[list[Any]] = None,
        total_result_rows: Optional[int] = None,
        query_spec: Any = None,
        analysis_result: Optional[AnalysisResult] = None,
        insight_result: Optional[InsightResult] = None,
    ) -> str:
        """Polished final answer style: answer first, explain simply, tailored by question archetype."""
        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
        row_count = total_result_rows if total_result_rows is not None else len(results)

        if not results:
            if is_arabic:
                return (
                    "الخلاصة: مش لاقي نتائج مطابقة للسؤال.\n\n"
                    "المعنى ببساطة: إما الفلتر ضيق شوية، أو الجدول المناسب لم يتحدد بدقة. جرب تسأل بصيغة أوسع أو اذكر اسم الجدول."
                )
            return (
                "Short answer: I couldn't find matching results for that question.\n\n"
                "What this means: the filter may be too narrow, or the right table was not specific enough. Try a broader question or mention the table you want to inspect."
            )

        analysis_type = ""
        if query_spec:
            at = getattr(query_spec, "analysis_type", "")
            analysis_type = at.value if hasattr(at, "value") else str(at).lower()
        elif analysis_result:
            analysis_type = getattr(analysis_result, "analysis_type", "").lower()

        # Dynamic routing by archetype
        if analysis_type == "lookup" or (len(results) == 1 and len(results[0]) > 1 and "SELECT *" in sql.upper()):
            return self._format_lookup_report(question, results, is_arabic)
        elif analysis_type in ("metric", "aggregation", "count") or (len(results) == 1 and len(results[0]) == 1):
            return self._format_metric_report(question, results, verified_facts, analysis_result, sql, is_arabic)
        elif analysis_type == "comparison":
            return self._format_comparison_report(question, results, analysis_result, is_arabic)
        elif analysis_type in ("trend", "forecasting"):
            return self._format_trend_report(question, results, analysis_result, is_arabic)
        elif analysis_type == "root_cause":
            return self._format_root_cause_report(question, results, analysis_result, is_arabic)
        elif analysis_type in (
            "exploratory_analysis", "data_quality", "distribution", "segmentation",
            "correlation", "anomaly_detection", "statistical_test",
        ):
            return self._format_exploratory_report(question, results, analysis_result, insight_result, is_arabic)

        if len(results) == 1 and len(results[0]) == 1:
            col_name, col_val = next(iter(results[0].items()))
            label = self._humanize_identifier(col_name, is_arabic=is_arabic)
            value = self._format_value(col_val)
            if is_arabic:
                return (
                    f"الخلاصة: `{label}` هو **{value}**.\n\n"
                    f"💡 **الشرح والتوضيح**:\n"
                    f"- **القيمة المحتسبة**: يمثل هذا الرقم ناتج استعلام قطعي مباشر من قاعدة البيانات للعمود `{col_name}`.\n"
                    f"- **المعنى العملي**: تم استخراج الرقم بدقة متناهية وبدون أي تقدير أو تقريب غير مبرر.\n\n"
                    f"📌 يمكنك طلب تحليل أعمق لهذا الرقم أو مقارنته بفترات زمنية سابقة."
                )
            return (
                f"Direct Answer: `{label}` is **{value}**.\n\n"
                f"💡 **Explanation & Context**:\n"
                f"- **Result Meaning**: This value was calculated directly from the database for `{col_name}`.\n"
                f"- **Data Precision**: Grounded in deterministic SQL execution with exact precision.\n\n"
                f"📌 You can request a historical comparison or breakdown by categories/dates."
            )

        is_explicit_ranking = bool(re.search(
            r"\b(top|bottom|highest|lowest|best|worst|most|least)\b|أعلى|الأكثر|أقل|الأدنى|أفضل|افضل",
            question,
            re.I
        ))

        # Build clean, complete rows summary with all informative columns
        if len(results[0]) > 2:
            lines = self._format_smart_rows_summary(results, is_arabic=is_arabic, max_rows=5)
        else:
            ranked_facts = []
            if is_explicit_ranking:
                for fact in (verified_facts or []):
                    ft = fact.get("fact_type") if isinstance(fact, dict) else getattr(fact, "fact_type", None)
                    if ft == "ranked_entity":
                        sv = fact.get("source_value") if isinstance(fact, dict) else getattr(fact, "source_value", {})
                        ent = sv.get("entity") if isinstance(sv, dict) else getattr(sv, "entity", "")
                        if ent and str(ent).strip().lower() not in ("none", "null", "record", ""):
                            ranked_facts.append(fact)

            lines = []
            if ranked_facts:
                for index, fact in enumerate(ranked_facts[:5], start=1):
                    sv = fact.get("source_value") if isinstance(fact, dict) else getattr(fact, "source_value", {})
                    if isinstance(sv, dict) and sv.get("entity"):
                        entity = sv.get("entity")
                        metric_name = sv.get("metric_name") or fact.get("source_column") if isinstance(fact, dict) else getattr(fact, "source_column", "value")
                        metric_raw = sv.get("metric_value") or sv.get("metric")
                        metric = self._humanize_identifier(str(metric_name or "value"), is_arabic=is_arabic)
                        metric_value = self._format_value(metric_raw)
                        lines.append(f"{index}. **{entity}** — {metric}: **{metric_value}**")
                    else:
                        statement = fact.get("statement") if isinstance(fact, dict) else getattr(fact, "statement", "")
                        lines.append(f"{index}. {statement}")
            else:
                lines = self._format_smart_rows_summary(results, is_arabic=is_arabic, max_rows=5)

        supporting_facts = [
            line[2:] if line.startswith("- ") else line
            for line in self._format_verified_facts(verified_facts or [], limit=3)
            if "Rank " not in line
        ]
        facts_text = ""
        if supporting_facts:
            facts_text = (
                "\n\n💡 **ملاحظة إحصائية**: " + "؛ ".join(supporting_facts)
                if is_arabic else
                "\n\n💡 **Key Takeaway**: " + "; ".join(supporting_facts)
            )

        results_text = "\n".join(lines)
        if is_arabic:
            if is_explicit_ranking:
                intro = f"إليك أعلى **{row_count}** نتائج مسجلة في قاعدة البيانات مرتبة تنازلياً مع كامل التفاصيل المطلوبة:"
            else:
                intro = f"إليك أهم **{row_count}** نتائج مطابقة لسؤالك من واقع قاعدة البيانات:"
            return (
                f"{intro}\n\n"
                f"{results_text}{facts_text}\n\n"
                "💡 يمكنك طلب تصفية النتائج لفترة زمنية معينة، أو استعراض تفاصيل أي سجل منها."
            )

        intro = f"Here are the top **{row_count}** matching records from the database:"
        return (
            f"{intro}\n\n"
            f"{results_text}{facts_text}\n\n"
            "💡 Feel free to ask to narrow down by date, filter by a specific entity, or inspect full row details."
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

    @staticmethod
    def _describe_table_for_user(table_name: str, is_arabic: bool = False) -> str:
        """Give a short human explanation from a grounded table name."""
        bare = table_name.split(".")[-1]
        normalized = bare.lower()
        if is_arabic:
            descriptions = [
                (("employee", "hr_"), "غالبًا مرتبط ببيانات الموظفين أو الرواتب أو إجراءات HR."),
                (("user", "res_users"), "مرتبط بحسابات المستخدمين والصلاحيات داخل النظام."),
                (("cycle",), "غالبًا يمثل دورة عمل أو مرحلة تشغيلية مرتبطة بالعمليات."),
                (("partner", "customer"), "مرتبط بالعملاء أو الشركاء أو جهات التعامل."),
                (("company",), "مرتبط ببيانات الشركات أو الوحدات التابعة."),
                (("invoice", "account_move"), "مرتبط بالفواتير والحركات المالية."),
                (("product",), "مرتبط بالمنتجات أو الخدمات."),
            ]
            fallback = "جدول قد يكون مفيدًا حسب سياق السؤال، ونقدر نفتحه ونشوف أعمدته لو تحب."
        else:
            descriptions = [
                (("employee", "hr_"), "likely stores employee, payroll, or HR-related information."),
                (("user", "res_users"), "stores system users, logins, permissions, or ownership links."),
                (("cycle",), "looks like a workflow/cycle table that may describe operational stages."),
                (("partner", "customer"), "usually stores customers, partners, or contact records."),
                (("company",), "stores company or business-unit information."),
                (("invoice", "account_move"), "is usually related to invoices or financial transactions."),
                (("product",), "stores products or services."),
            ]
            fallback = "may be relevant based on its name; we can inspect its columns next."
        for needles, description in descriptions:
            if any(needle in normalized for needle in needles):
                return description
        return fallback

    def format_schema_table_answer(
        self,
        question: str,
        rows: list[dict[str, Any]],
    ) -> Optional[str]:
        """Turn single-column table-name results into a helpful human explanation."""
        if not rows or not all(isinstance(row, dict) and set(row.keys()) == {"table_name"} for row in rows):
            return None
        table_names = [str(row.get("table_name")) for row in rows if row.get("table_name")]
        if not table_names:
            return None

        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
        if is_arabic:
            lines = [
                f"الخلاصة: لقيت **{len(table_names)}** جداول غالبًا مرتبطة بسؤالك.",
                "",
                "لو هنتكلم ببساطة، دي الجداول الأقرب:",
            ]
            for index, table in enumerate(table_names[:8], start=1):
                lines.append(f"{index}. **{table}** - {self._describe_table_for_user(table, is_arabic=True)}")
            if len(table_names) > 8:
                lines.append(f"- وفيه **{len(table_names) - 8}** جداول إضافية ممكن نعرضها لو تحب.")
            lines.extend([
                "",
                "المعنى ببساطة: ابدأ بالجدول الأقرب لاحتياجك، ولو عاوز تفاصيل أدق اسألني: \"اشرح أعمدة جدول ...\" أو \"اعرض أول 10 سجلات من ...\".",
                "",
                "للمراجعة: البيانات الخام تحت فيها أسماء الجداول كما رجعت من قاعدة البيانات.",
            ])
            return "\n".join(lines)

        lines = [
            f"Short answer: I found **{len(table_names)}** tables that look related to your question.",
            "",
            "In plain English, these are the best places to start:",
        ]
        for index, table in enumerate(table_names[:8], start=1):
            lines.append(f"{index}. **{table}** - {self._describe_table_for_user(table)}")
        if len(table_names) > 8:
            lines.append(f"- There are **{len(table_names) - 8}** more possible matches if you want to broaden the search.")
        lines.extend([
            "",
            "What this means: start with the table that matches what you want to inspect, then ask me to show its columns, relationships, or sample records.",
            "",
            "To verify it, check the raw table-name results below.",
        ])
        return "\n".join(lines)

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
        complex_types = {
            "comparison", "trend", "root_cause", "correlation", "multi_step",
            "anomaly_detection", "exploratory_analysis", "forecasting",
            "statistical_test", "segmentation", "distribution", "data_quality"
        }
        if getattr(query_spec, "requires_multi_step", False) or analysis_name in complex_types or analysis_type in COMPLEX_ANALYSIS_TYPES:
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
        from app.services.sql.result_verifier import result_verifier
        constrained, _, _ = result_verifier.verify_and_constrain_prose(
            report, rows=rows, facts=facts, sql=sql,
        )
        return constrained

    @classmethod
    def _format_evidence_payload(
        cls,
        question: str,
        query_spec: Any = None,
        analysis_result: Optional[AnalysisResult] = None,
        analytics_result: Optional[AnalyticsResult] = None,
        insight_result: Optional[InsightResult] = None,
        verified_facts: Optional[list[Any]] = None,
        sql: str = "",
        results: Optional[list[dict[str, Any]]] = None,
        total_result_rows: Optional[int] = None,
    ) -> dict[str, str]:
        """Construct a structured, evidence-based payload strictly separating facts from language generation."""
        # 1. Analysis Goal & Plan
        plan_str = f"Analytical question: {question}"
        if query_spec:
            goal = getattr(query_spec, "analysis_goal", "") or getattr(query_spec, "raw_question", "")
            ops = getattr(query_spec, "operations", [])
            ops_str = ", ".join(str(o.value if hasattr(o, "value") else o) for o in ops)
            plan_str = f"Goal: {goal}\nOperations: {ops_str if ops_str else 'General Analysis'}"

        # 2. Findings
        findings_list = []
        if analysis_result and analysis_result.findings:
            findings_list.extend(analysis_result.findings)
        elif analytics_result and getattr(analytics_result, "analytical_findings", None):
            findings_list.extend(analytics_result.analytical_findings)
        findings_str = "\n".join(f"- {f}" for f in findings_list) if findings_list else "Tabular database query result"

        # 3. Metrics
        metrics_dict = {}
        if analysis_result and analysis_result.metrics:
            metrics_dict.update(analysis_result.metrics)
        metrics_str = json.dumps(metrics_dict, indent=2, default=str) if metrics_dict else "{}"

        # 4. Results Data Records with explicit month annotations for total accuracy
        _MONTH_NAMES = {
            "01": "يناير / January", "02": "فبراير / February", "03": "مارس / March",
            "04": "أبريل / April", "05": "مايو / May", "06": "يونيو / June",
            "07": "يوليو / July", "08": "أغسطس / August", "09": "سبتمبر / September",
            "10": "أكتوبر / October", "11": "نوفمبر / November", "12": "ديسمبر / December",
        }
        results_data_str = "No tabular rows returned"
        if results:
            sample_rows = []
            sample_limit = 5 if len(results[0]) > 15 else 10
            for r in results[:sample_limit]:
                annotated_r = {}
                for k, v in list(r.items()):
                    if v is None:
                        continue
                    v_str = str(v)
                    if len(v_str) > 80:
                        v_str = v_str[:77] + "..."
                    if isinstance(v, str) and re.match(r"^\d{4}-\d{2}$", v.strip()):
                        m_code = v.strip().split("-")[1]
                        if m_code in _MONTH_NAMES:
                            v_str = f"{v} [{_MONTH_NAMES[m_code]}]"
                    annotated_r[k] = v_str
                sample_rows.append(annotated_r)
            results_data_str = json.dumps(sample_rows, indent=2, default=str)
            if len(results_data_str) > 3500:
                results_data_str = results_data_str[:3500] + "... [data sample truncated for brevity]"

        # 5. Evidence
        evidence_list = []
        if analysis_result and analysis_result.evidence:
            evidence_list.extend(analysis_result.evidence)
        evidence_str = "\n".join(f"- {e}" for e in evidence_list) if evidence_list else "Derived from executed SQL result set"

        # 6. Verified Facts
        facts_list = cls._format_verified_facts(verified_facts or [])
        facts_str = "\n".join(facts_list) if facts_list else f"Total rows returned: {total_result_rows or (len(results) if results else 0)}"

        # 7. Warnings
        warnings_list = []
        if analysis_result and analysis_result.warnings:
            warnings_list.extend(analysis_result.warnings)
        if insight_result and getattr(insight_result, "critical_warnings", None):
            warnings_list.extend(insight_result.critical_warnings)
        warnings_str = "\n".join(f"- {w}" for w in warnings_list) if warnings_list else "None (clean execution)"

        # 8. Limitations
        limitations_list = []
        if analysis_result and analysis_result.limitations:
            limitations_list.extend(analysis_result.limitations)
        limitations_str = "\n".join(f"- {l}" for l in limitations_list) if limitations_list else "Conclusions strictly bounded by retrieved database records"

        return {
            "question": question,
            "analysis_plan": plan_str,
            "findings": findings_str,
            "metrics": metrics_str,
            "results_data": results_data_str,
            "evidence": evidence_str,
            "verified_facts": facts_str,
            "warnings": warnings_str,
            "limitations": limitations_str,
        }

    @staticmethod
    def _format_verified_facts(facts: list[Any], limit: int = 30) -> list[str]:
        """Render compact facts calculated before any LLM-row truncation."""
        lines = []
        for fact in facts[:limit]:
            statement = fact.get("statement") if isinstance(fact, dict) else getattr(fact, "statement", None)
            if statement:
                lines.append(f"- {statement}")
        return lines

    @staticmethod
    def _strip_subsequent_turn_greetings(text: str, question: str) -> str:
        if not text:
            return ""
        # If the user explicitly greeted in this turn, keep the greeting
        user_greeted = bool(re.search(
            r"^\s*(?:hi|hello|hey|welcome|اهلا|أهلا|مرحبا|مرحباً|صباح\s*الخير|مساء\s*الخير|السلام\s*عليكم)",
            question.strip(),
            re.I
        ))
        if user_greeted:
            return text
        greeting_re = re.compile(
            r"^\s*(?:"
            r"(?:أهلاً\s*(?:بيك|بك|يا\s*فندم)?|أهلا\s*(?:بيك|بك|يا\s*فندم)?|مرحباً|مرحبا|سلام\s*عليكم|السلام\s*عليكم|تحياتي)\s*[!.,،\-:]*\s*"
            r"|(?:Hello|Hi|Hey|Good\s+(?:morning|afternoon|evening))\s*[!.,،\-:]*\s*"
            r")+(?:بناءً?\s+على\s+البيانات\s+(?:اللي\s+عندنا|المتاحة|المسجلة|الموجودة|الواردة)[!.,،\-:]*\s*)?",
            re.IGNORECASE | re.UNICODE
        )
        cleaned = greeting_re.sub("", text).strip()
        cleaned = re.sub(r"^[،,\-–—:\s]+", "", cleaned).strip()
        return cleaned or text

    async def generate_report_and_chart(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        analytics_result: Optional[AnalyticsResult] = None,
        insight_result: Optional[InsightResult] = None,
        analysis_result: Optional[AnalysisResult] = None,
        require_verification: bool = True,
        verified_facts: Optional[list[Any]] = None,
        total_result_rows: Optional[int] = None,
        query_spec: Any = None,
        verification_rows: Optional[list[dict[str, Any]]] = None,
        is_first_turn: bool = True,
        conversation_history: str = "",
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
            analysis_result=analysis_result,
            require_verification=require_verification,
            verified_facts=verified_facts,
            total_result_rows=total_result_rows,
            query_spec=query_spec,
            verification_rows=verification_rows,
            is_first_turn=is_first_turn,
            conversation_history=conversation_history,
        )

        return report, chart

    async def generate_report(
        self,
        question: str,
        sql: str,
        results: list[dict[str, Any]],
        analytics_result: Optional[AnalyticsResult] = None,
        insight_result: Optional[InsightResult] = None,
        analysis_result: Optional[AnalysisResult] = None,
        require_verification: bool = True,
        verified_facts: Optional[list[Any]] = None,
        total_result_rows: Optional[int] = None,
        query_spec: Any = None,
        verification_rows: Optional[list[dict[str, Any]]] = None,
        is_first_turn: bool = True,
        conversation_history: str = "",
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

        # Simple/scalar/list answers are still grounded in rows, but the final
        # wording should be adaptive, not a repeated template. Try the fast LLM
        # presentation layer first; fall back to deterministic wording only if
        # the model is unavailable.
        if report_mode is ReportMode.DETERMINISTIC:
            gate_facts = list(verified_facts or [])
            if total_result_rows is not None and total_result_rows != len(results):
                gate_facts.append({"statement": f"Total records returned: {total_result_rows}."})
            try:
                evidence_payload = self._format_evidence_payload(
                    question=question,
                    query_spec=query_spec,
                    analysis_result=analysis_result,
                    analytics_result=analytics_result,
                    insight_result=insight_result,
                    verified_facts=gate_facts,
                    sql=sql,
                    results=results,
                    total_result_rows=total_result_rows,
                )
                adaptive_prompt = EVIDENCE_BASED_REPORT_TEMPLATE.format(**evidence_payload)
                adaptive_prompt += (
                    "\n\n[ADAPTIVE RESPONSE STYLE]\n"
                    "- Do not force a fixed section template. Choose the structure that best fits this exact question and result.\n"
                    "- For a simple count, answer in one or two natural sentences.\n"
                    "- For a list of tables/columns, explain what the names suggest and how the user can continue.\n"
                    "- For ranked or grouped rows, summarize the pattern first, then list only the useful highlights.\n"
                    "- Never say 'Query retrieved rows', 'Direct Answer', 'Context & Accuracy', or 'Precision'.\n"
                    "- Keep SQL and raw data out of the main answer; the UI already shows them below.\n"
                    "- Sound like a real analyst explaining the result to a human, not a report generator.\n"
                )
                if not is_first_turn:
                    adaptive_prompt += "\nThis is a follow-up in an existing chat, so answer directly without greetings."

                llm = get_langchain_llm(tier="fast", temperature=0.35)
                from langchain_core.messages import HumanMessage
                response = await llm.ainvoke([HumanMessage(content=adaptive_prompt)])
                fast_report = str(response.content).strip()
            except Exception as exc:
                logger.warning("Adaptive deterministic response failed; using safe fallback: %s", exc)
                fast_report = self._format_conversational_report(
                    question=question,
                    sql=sql,
                    results=results,
                    verified_facts=verified_facts,
                    total_result_rows=total_result_rows,
                    query_spec=query_spec,
                    analysis_result=analysis_result,
                    insight_result=insight_result,
                )
            if not is_first_turn:
                fast_report = self._strip_subsequent_turn_greetings(fast_report, question)
            if not (results and all(isinstance(row, dict) and set(row.keys()) == {"table_name"} for row in results)):
                fast_report = self._apply_deterministic_claim_gate(
                    fast_report, verification_rows if verification_rows is not None else results,
                    gate_facts,
                    sql,
                )
            set_cached_report(question, sql, results_fingerprint, fast_report, **report_cache_context)
            return fast_report

        sample_context = f"[Sample rows only — do not calculate totals from this sample]\n{results_str}"
        if insight_result and insight_result.prompt_context:
            results_json = f"{sample_context}\n\n[Insights Summary]\n{insight_result.prompt_context}"
        else:
            results_json = sample_context

        # Inject verified deterministic facts to strictly constrain narrative prose
        from app.services.sql.result_verifier import result_verifier
        facts = verified_facts if verified_facts is not None else result_verifier.generate_deterministic_facts(
            results, sql=sql, question=question
        )
        if facts:
            facts_summary = "\n".join(self._format_verified_facts(facts))
            results_json = f"{results_json}\n\n[Verified facts calculated from ALL {total_result_rows if total_result_rows is not None else len(results)} result rows — rely exclusively on these for totals, averages, ranges, and rankings]\n{facts_summary}"

        # Stage 1: Generate draft report using structured Evidence-Based payload
        evidence_payload = self._format_evidence_payload(
            question=question,
            query_spec=query_spec,
            analysis_result=analysis_result,
            analytics_result=analytics_result,
            insight_result=insight_result,
            verified_facts=verified_facts if verified_facts is not None else facts,
            sql=sql,
            results=results,
            total_result_rows=total_result_rows,
        )
        prompt = EVIDENCE_BASED_REPORT_TEMPLATE.format(**evidence_payload)

        try:
            if not is_first_turn:
                prompt += "\n\n[CONVERSATION CONTEXT - SUBSEQUENT TURN]: This is an ongoing conversation (NOT the first turn). DO NOT include any greetings, welcomes, or introductory phrases (do not say 'أهلاً بك', 'أهلاً بيك', 'مرحباً', 'Hello', 'Hi', 'Hey'). Answer the question directly and immediately."
            else:
                prompt += "\n\n[CONVERSATION CONTEXT - FIRST TURN]: This is the first interaction in the session. You may include a single brief, warm greeting if natural."

            if tone == "technical":
                prompt += "\n\n[USER PREFERENCE - TONE]: Adopt a Detailed Technical style with precise statistical breakdown and quantitative rigor."
            elif tone == "concise":
                prompt += "\n\n[USER PREFERENCE - TONE]: Keep the briefing extremely concise, formatting findings as brief bullet points."

            is_arabic_q = any("\u0600" <= c <= "\u06FF" for c in question)
            if lang == "ar" or (lang == "auto" and is_arabic_q):
                prompt += f"\n\n[USER PREFERENCE - LANGUAGE & DIALECT]: Respond in Arabic (العربية), subtly tailoring idiomatic vocabulary toward the {dialect.upper()} Arabic dialect style while maintaining professional clarity."
            else:
                prompt += "\n\n[USER PREFERENCE - LANGUAGE]: The user asked in English. Respond strictly in English. Do NOT output Arabic words or greetings."
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
            draft_report, rows=verification_source_rows, facts=facts, sql=sql, question=question,
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
            final_report, rows=verification_source_rows, facts=facts, sql=sql, question=question,
        )
        if not is_first_turn:
            constrained_report = self._strip_subsequent_turn_greetings(constrained_report, question)
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
        error_type: Optional[str] = None,
    ) -> str:
        """
        Generate a clear, deterministic human explanation for why the question
        couldn't be answered (unanswerable from schema, no matching rows, execution failed, or validation blocked).
        Eliminates unnecessary LLM calls for unanswerable queries.
        """
        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
        sit_clean = situation.rstrip(".")
        reas_clean = reason.rstrip(".")
        err_type = (error_type or "").lower()

        # 1. Empty Result (Query ran successfully, 0 rows returned)
        if err_type == "empty_result" or "no matching rows" in sit_clean.lower() or "returned 0 rows" in sit_clean.lower():
            if is_arabic:
                return (
                    "الخلاصة: تم تنفيذ الاستعلام بنجاح ولكن لم يتم العثور على أي سجلات (0 نتيجة).\n\n"
                    "المعنى ببساطة: الجدول فارغ حالياً في قاعدة البيانات أو لا توجد سجلات مطابقة لشروط الاستعلام."
                )
            return (
                "Short answer: The query executed successfully, but returned 0 matching records.\n\n"
                "What this means: The table currently contains no records, or no rows matched the specified query conditions."
            )

        # 2. Unanswerable from Schema (Missing tables / entities / columns)
        if err_type == "unanswerable" or "cannot be answered" in sit_clean.lower() or "schema" in sit_clean.lower():
            tables_str = ""
            if table_names and len(table_names) <= 5:
                tables_str = f" ({', '.join(table_names)})"
            if is_arabic:
                return (
                    f"الخلاصة: لا يمكن الإجابة على هذا السؤال باستخدام قاعدة البيانات المتاحة{tables_str}.\n\n"
                    f"المعنى ببساطة: {reas_clean}."
                )
            return (
                f"Short answer: This question cannot be answered using the current database schema{tables_str}.\n\n"
                f"What this means: {reas_clean}."
            )

        # 3. Cost Guard / Safety / Validation Blocked
        if err_type in ("cost_guard", "safety", "validation", "identifier_grounding", "join_validation", "semantic_alignment") or "blocked" in sit_clean.lower() or "safely" in sit_clean.lower():
            if is_arabic:
                return f"تنبيه التحقق من الاستعلام: {sit_clean}.\n\nالتفاصيل: {reas_clean}."
            return f"Query Validation Notice: {sit_clean}.\n\nDetails: {reas_clean}."

        # 4. Execution / Repair Error
        if "execution" in err_type or "failed to execute" in sit_clean.lower() or "plan step failed" in sit_clean.lower():
            if is_arabic:
                return f"خطأ في التنفيذ: {sit_clean}.\n\nالتفاصيل: {reas_clean}."
            return f"Execution Error: {sit_clean}.\n\nDetails: {reas_clean}."

        # 5. Quality Gate / Verification Failure
        if "verification" in err_type or "quality gates" in sit_clean.lower():
            if is_arabic:
                return f"تنبيه جودة النتائج: {sit_clean}.\n\nالتفاصيل: {reas_clean}."
            return f"Result Quality Notice: {sit_clean}.\n\nDetails: {reas_clean}."

        # 6. Default Fallback
        if is_arabic:
            return f"الخلاصة: {sit_clean}.\n\nالتفاصيل: {reas_clean}."
        return f"Short answer: {sit_clean}.\n\nDetails: {reas_clean}."



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
