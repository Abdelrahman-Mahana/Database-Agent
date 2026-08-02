"""Shared text processing, SQL extraction, JSON cleaning, and result summarization utilities."""
import re
from enum import Enum
from typing import Any


class AnalysisType(str, Enum):
    """Classification of analytical intent for database queries."""
    LOOKUP = "lookup"
    COUNT = "count"
    AGGREGATION = "aggregation"
    RANKING = "ranking"
    COMPARISON = "comparison"
    TREND = "trend"
    ROOT_CAUSE = "root_cause"
    MULTI_STEP = "multi_step"
    UNKNOWN = "unknown"


COMPLEX_ANALYSIS_TYPES = {
    AnalysisType.COMPARISON,
    AnalysisType.TREND,
    AnalysisType.ROOT_CAUSE,
    AnalysisType.MULTI_STEP,
}


def clean_code_fences(text: str) -> str:
    """Strip markdown code fences (```sql, ```json, ```) from text."""
    text = text.strip()
    patterns = [
        r"```(?:sql|json)?\s*(.*?)\s*```",
        r"```\s*(.*?)\s*```",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|sql)?|```$", "", text, flags=re.MULTILINE).strip()
    return text


def extract_sql(text: str) -> str:
    """Extract SQL query from LLM response, handling markdown fences and line searching."""
    text = text.strip()

    # Try to find SQL in markdown code fences
    patterns = [
        r"```sql\s*(.*?)\s*```",
        r"```\s*(.*?)\s*```",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # If no fences, try to find the SQL statement by checking line prefixes
    lines = text.split("\n")
    sql_lines = []
    in_sql = False
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("SELECT") or stripped.upper().startswith("WITH"):
            in_sql = True
        if in_sql:
            sql_lines.append(line)

    if sql_lines:
        return "\n".join(sql_lines).strip()

    # Fallback: return the whole text
    return text


def sanitize_query(query: str) -> str:
    """Extract and sanitize SQL from markdown fences, truncating after first semicolon."""
    text = query.strip()

    # 1. Try to find SQL in markdown code fences
    patterns = [
        r"```sql\s*(.*?)\s*```",
        r"```\s*(.*?)\s*```",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1).strip()
            break

    # 2. Extract only up to the first semicolon if present
    if ";" in text:
        idx = text.find(";")
        text = text[:idx + 1].strip()

    return text


def extract_json_text(text: str) -> str:
    """Extract clean JSON string from LLM response, handling code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    elif "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            candidate = parts[1].strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            text = candidate
    return text


def build_result_summary(rows_list: list[dict[str, Any]]) -> str:
    """Build a compact textual summary of database query result rows for memory turns."""
    if not rows_list:
        return "No rows returned."
    num_rows = len(rows_list)
    sample = rows_list[0]
    sample_str = ", ".join(f"{k}: {v}" for k, v in list(sample.items())[:3])
    if len(sample) > 3:
        sample_str += ", ..."
    return f"{num_rows} row{'s' if num_rows > 1 else ''}. Sample values: {{{sample_str}}}"


def normalize_question(question: str) -> str:
    """Normalize user question to ignore capitalization, spacing, and trailing punctuation."""
    q = question.lower().strip()
    q = re.sub(r"[?.!,;:]+$", "", q)
    return " ".join(q.split())


def normalize_sql(s: str) -> str:
    """Normalize SQL query for majority voting comparisons by removing comments and whitespace."""
    s_clean = re.sub(r"--.*?\n", " ", s)
    s_clean = re.sub(r"/\*.*?\*/", " ", s_clean, flags=re.DOTALL)
    return " ".join(s_clean.strip().split()).lower()


def classify_analysis_type(question: str) -> AnalysisType:
    """
    Deterministic rule-based classification of query analysis type.
    Categorizes questions into LOOKUP, COUNT, AGGREGATION, RANKING, COMPARISON, TREND, ROOT_CAUSE, MULTI_STEP, or UNKNOWN.
    """
    if not question or not question.strip():
        return AnalysisType.UNKNOWN

    q = question.lower().strip()

    # 1. Multiple distinct questions or sequential execution -> MULTI_STEP
    if q.count("?") >= 2:
        return AnalysisType.MULTI_STEP

    sequence_indicators = [
        r"\bthen\b",
        r"\bfirst\b.*\bthen\b",
        r"\bafter that\b",
        r"\bfollowed by\b",
        r"\band also\b",
        r"\bas well as\b",
        r"\bثم\b",
        r"\bوبعد ذلك\b",
        r"\bوبعدها\b",
        r"\bبالإضافة إلى\b",
        r"\bوكذلك\b",
        r"\bأولاً\b.*\bثم\b",
    ]
    for pattern in sequence_indicators:
        if re.search(pattern, q):
            return AnalysisType.MULTI_STEP

    compound_conjunction = r"\b(who|what|show|list|find|get|عرض|هات|من|ما|ماذا)\b.*\b(and|و)\b.*\b(what|how|show|list|find|get|which|عرض|هات|كيف|ما|ماذا)\b"
    if re.search(compound_conjunction, q):
        return AnalysisType.MULTI_STEP

    # 2. Root cause / Explanatory indicators -> ROOT_CAUSE
    root_cause_indicators = [
        r"\bexplain why\b",
        r"\bwhy did\b",
        r"\broot cause\b",
        r"\bimpact of\b",
        r"\bwhy is\b",
        r"\bwhy are\b",
        r"\bلماذا\b",
        r"\bسبب\b",
        r"\bتأثير\b",
        r"\bليه\b",
        r"\bاشرح لي\b",
    ]
    for pattern in root_cause_indicators:
        if re.search(pattern, q):
            return AnalysisType.ROOT_CAUSE

    # 3. Comparative indicators -> COMPARISON
    comparative_indicators = [
        r"\bcompare\b",
        r"\bcomparison\b",
        r"\bversus\b",
        r"\bvs\.?\b",
        r"\bdifference between\b",
        r"\bbefore\b.*\bafter\b",
        r"\bقارن\b",
        r"\bمقارنة\b",
        r"\bمقابل\b",
        r"\bالفرق بين\b",
        r"\bضد\b",
        r"\bقبل\b.*\bبعد\b",
    ]
    for pattern in comparative_indicators:
        if re.search(pattern, q):
            return AnalysisType.COMPARISON

    # 4. Temporal trend & correlation indicators -> TREND
    trend_indicators = [
        r"\btrend\b",
        r"\btrends\b",
        r"\bover time\b",
        r"\byear over year\b",
        r"\bmonth over month\b",
        r"\bgrowth rate\b",
        r"\bcorrelation\b",
        r"\brelationship between\b",
        r"\bاتجاه\b",
        r"\bمسار\b",
        r"\bبمرور الوقت\b",
        r"\bعبر الزمن\b",
        r"\bنمو\b",
        r"\bعلاقة\b",
        r"\bارتباط\b",
        r"\bتطور\b",
    ]
    for pattern in trend_indicators:
        if re.search(pattern, q):
            return AnalysisType.TREND

    # 5. Simple Count -> COUNT
    # 'كام' is the common Egyptian/Gulf colloquial spelling of 'كم' (how many)
    # — without it, everyday phrasing like "كام طلب اتعمل؟" falls through to
    # UNKNOWN and the grounding engine loses its seed-table signal entirely.
    if re.search(r"\b(how many|count|number of|كم|كام|كم عدد|عدد|احسب)\b", q):
        return AnalysisType.COUNT

    # 6. Ranking -> RANKING
    if re.search(r"\b(top|bottom|best|worst|highest|lowest|most|least|اعلى|أعلى|اقل|أقل|افضل|أفضل|اسوأ|أسوأ|اكثر|أكثر|اكتر)\b", q):
        return AnalysisType.RANKING

    # 7. Aggregation -> AGGREGATION
    if re.search(r"\b(total|sum|average|avg|min|max|minimum|maximum|اجمالي|إجمالي|مجموع|متوسط|معدل|حد ادنى|حد أقصى|اكبر|أكبر|اصغر|أصغر)\b", q):
        return AnalysisType.AGGREGATION

    # 8. Simple Lookup -> LOOKUP
    if re.search(r"\b(show|list|find|get|select|details|عرض|اعرض|هات|قائمة|ابحث|تفاصيل|هاتلي|وريني|ورينى)\b", q):
        return AnalysisType.LOOKUP

    return AnalysisType.UNKNOWN


def is_complex_query(question: str) -> bool:
    """Deterministic rule-based check if a question is complex enough to require LLM decomposition."""
    return classify_analysis_type(question) in COMPLEX_ANALYSIS_TYPES


_MONTH_NAMES = (
    # English full + common abbreviations
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    # Arabic (Gregorian month names as commonly used)
    "يناير", "فبراير", "مارس", "أبريل", "ابريل", "مايو", "يونيو", "يوليو",
    "أغسطس", "اغسطس", "سبتمبر", "أكتوبر", "اكتوبر", "نوفمبر", "ديسمبر",
)
_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
_DATA_RANGE_PATTERN = re.compile(r"Data range:\s*([^\n]+?)\s+to\s+([^\n]+)")


def build_temporal_grounding_hint(question: str, schema_text: str) -> str | None:
    """
    If the question references a bare month (no year attached - e.g. "compare
    January to February sales", "مبيعات يناير") and the grounded schema shows
    a "Data range" for a date column, return an explicit instruction pinning
    the year to use - so SQL generation doesn't fall back on the LLM's
    general/training-data assumptions about what this schema "usually"
    contains (e.g. assuming classic Northwind is 1996-1998, when a specific
    connected copy of it might actually span 2012-2023). Returns None when
    the question doesn't need this (already has an explicit year, or no
    month is mentioned, or no date range is available to ground against).
    """
    q_lower = question.lower()
    has_month = any(re.search(rf"\b{re.escape(m)}\b", q_lower) for m in _MONTH_NAMES)
    if not has_month:
        return None
    if _YEAR_PATTERN.search(question):
        return None  # question already pins a year - nothing to resolve

    ranges = _DATA_RANGE_PATTERN.findall(schema_text)
    if not ranges:
        return None

    end_years = []
    for _start, end in ranges:
        m = _YEAR_PATTERN.search(end)
        if m:
            end_years.append(int(m.group(0)))
    if not end_years:
        return None

    most_recent_year = max(end_years)
    return (
        f"Note: the question references a month with no explicit year. "
        f"Based on the actual data available (see 'Data range' comments in the schema), "
        f"use {most_recent_year} (the most recent year present in the data) "
        f"instead of assuming a year from general knowledge about this schema."
    )
