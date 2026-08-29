from __future__ import annotations


"""Extract the missing table/column name a DB engine's error message names.

Factored out of `app.services.sql.repair_engine.SQLRepairEngine.analyze_db_error`
(same regexes, same behavior) so `app.services.schema_learning` (Phase 5)
can reuse the exact identifier the error was actually about, not just the
fuzzy-matched suggestion list `analyze_db_error` returns. Kept dependency-free
(stdlib only) so it can be imported from anywhere without pulling in the LLM
stack.
"""

import re
from typing import Optional, Tuple

_TABLE_PATTERNS = (
    re.compile(r"no such table:\s*(\w+)", re.IGNORECASE),
    re.compile(r'relation\s*"([^"]+)"\s*does not exist', re.IGNORECASE),
)
_COLUMN_PATTERNS = (
    re.compile(r"no such column:\s*([\w.]+)", re.IGNORECASE),
    re.compile(r'column\s*"([^"]+)"\s*does not exist', re.IGNORECASE),
)


def extract_missing_identifier(error_msg: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (kind, name) where kind is "table" or "column", or (None, None)
    if the error message doesn't match a known "unknown identifier" shape
    (e.g. it's a syntax error, permissions error, timeout, ...).

    For columns, any leading "table." qualifier is stripped - callers only
    get the bare column name, matching what `analyze_db_error` already does.
    """
    if not error_msg:
        return None, None
    for pattern in _TABLE_PATTERNS:
        m = pattern.search(error_msg)
        if m:
            return "table", m.group(1)
    for pattern in _COLUMN_PATTERNS:
        m = pattern.search(error_msg)
        if m:
            return "column", m.group(1).split(".")[-1]
    return None, None


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
    DISTRIBUTION = "distribution"
    CORRELATION = "correlation"
    ANOMALY_DETECTION = "anomaly_detection"
    SEGMENTATION = "segmentation"
    ROOT_CAUSE = "root_cause"
    FORECASTING = "forecasting"
    STATISTICAL_TEST = "statistical_test"
    DATA_QUALITY = "data_quality"
    EXPLORATORY_ANALYSIS = "exploratory_analysis"
    MULTI_STEP = "multi_step"
    UNKNOWN = "unknown"


COMPLEX_ANALYSIS_TYPES = {
    AnalysisType.COMPARISON,
    AnalysisType.TREND,
    AnalysisType.ROOT_CAUSE,
    AnalysisType.MULTI_STEP,
    AnalysisType.CORRELATION,
    AnalysisType.ANOMALY_DETECTION,
    AnalysisType.FORECASTING,
    AnalysisType.STATISTICAL_TEST,
    AnalysisType.EXPLORATORY_ANALYSIS,
    AnalysisType.SEGMENTATION,
    AnalysisType.DISTRIBUTION,
    AnalysisType.DATA_QUALITY,
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
    Categorizes questions into distinct analytical purposes:
    LOOKUP, COUNT, AGGREGATION, RANKING, COMPARISON, TREND, DISTRIBUTION,
    CORRELATION, ANOMALY_DETECTION, SEGMENTATION, ROOT_CAUSE, FORECASTING,
    STATISTICAL_TEST, DATA_QUALITY, EXPLORATORY_ANALYSIS, MULTI_STEP, or UNKNOWN.
    """
    if not question or not question.strip():
        return AnalysisType.UNKNOWN

    q = question.lower().strip()

    # 1. Multiple distinct questions or sequential execution -> MULTI_STEP
    if (q.count("?") + q.count("؟")) >= 2:
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
        r"\bأسباب\b",
        r"\bتأثير\b",
        r"\bليه\b",
        r"\bاشرح لي\b",
    ]
    for pattern in root_cause_indicators:
        if re.search(pattern, q):
            return AnalysisType.ROOT_CAUSE

    # 3. Anomaly detection & outlier indicators -> ANOMALY_DETECTION
    anomaly_indicators = [
        r"\banomaly\b",
        r"\banomalies\b",
        r"\boutlier\b",
        r"\boutliers\b",
        r"\babnormal\b",
        r"\bunusual\b",
        r"\bقيم شاذة\b",
        r"\bشاذة\b",
        r"\bشواذ\b",
        r"\bشذوذ\b",
        r"\bانحراف\b",
        r"\bغير طبيعي\b",
        r"\bغير معتاد\b",
    ]
    for pattern in anomaly_indicators:
        if re.search(pattern, q):
            return AnalysisType.ANOMALY_DETECTION

    # 4. Correlation & relationship indicators -> CORRELATION
    correlation_indicators = [
        r"\bcorrelation\b",
        r"\bcorrelate\b",
        r"\brelationship between\b",
        r"\bassociated with\b",
        r"\bعلاقة بين\b",
        r"\bارتباط بين\b",
        r"\bعلاقة\b",
        r"\bارتباط\b",
        r"\bتأثير متبادل\b",
    ]
    for pattern in correlation_indicators:
        if re.search(pattern, q):
            return AnalysisType.CORRELATION

    # 5. Forecasting & predictive indicators -> FORECASTING
    forecasting_indicators = [
        r"\bforecast\b",
        r"\bforecasting\b",
        r"\bpredict\b",
        r"\bprediction\b",
        r"\bprojected\b",
        r"\bprojection\b",
        r"\bnext month\b",
        r"\bnext year\b",
        r"\bnext quarter\b",
        r"\bfuture\b",
        r"\bتوقع\b",
        r"\bتنبؤ\b",
        r"\bالشهر القادم\b",
        r"\bالسنة القادمة\b",
        r"\bالمستقبل\b",
    ]
    for pattern in forecasting_indicators:
        if re.search(pattern, q):
            return AnalysisType.FORECASTING

    # 6. Comparative indicators -> COMPARISON
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

    # 7. Data quality & missing/null/duplicate checks -> DATA_QUALITY
    data_quality_indicators = [
        r"\bdata quality\b",
        r"\bmissing values\b",
        r"\bnull values\b",
        r"\bnulls\b",
        r"\bduplicates\b",
        r"\bduplicate records\b",
        r"\binconsistency\b",
        r"\bجودة البيانات\b",
        r"\bقيم فارغة\b",
        r"\bقيم مفقودة\b",
        r"\bسجلات مكررة\b",
        r"\bتكرار\b",
        r"\bفارغ\b",
    ]
    for pattern in data_quality_indicators:
        if re.search(pattern, q):
            return AnalysisType.DATA_QUALITY

    # 8. Statistical tests & hypothesis validation -> STATISTICAL_TEST
    statistical_indicators = [
        r"\bstatistical test\b",
        r"\bhypothesis\b",
        r"\bt-test\b",
        r"\bchi-square\b",
        r"\bp-value\b",
        r"\bvariance\b",
        r"\bstandard deviation\b",
        r"\bstddev\b",
        r"\bانحراف معياري\b",
        r"\bتباين\b",
        r"\bاختبار إحصائي\b",
        r"\bدلالة إحصائية\b",
        r"\bفرضية\b",
    ]
    for pattern in statistical_indicators:
        if re.search(pattern, q):
            return AnalysisType.STATISTICAL_TEST

    # 9. Segmentation & cohort clustering -> SEGMENTATION
    segmentation_indicators = [
        r"\bsegment\b",
        r"\bsegments\b",
        r"\bsegmentation\b",
        r"\bcohort\b",
        r"\bcohorts\b",
        r"\bcluster\b",
        r"\bclusters\b",
        r"\brfm\b",
        r"\bشرائح\b",
        r"\bشريحة\b",
        r"\bتقسيم العملاء\b",
        r"\bتصنيف العملاء\b",
        r"\bفئات العملاء\b",
    ]
    for pattern in segmentation_indicators:
        if re.search(pattern, q):
            return AnalysisType.SEGMENTATION

    # 10. Distribution & category spread -> DISTRIBUTION
    distribution_indicators = [
        r"\bdistribution\b",
        r"\bdistributed\b",
        r"\bspread\b",
        r"\bhistogram\b",
        r"\bbreakdown by\b",
        r"\bتوزيع\b",
        r"\bتوزيع العملاء\b",
        r"\bتوزيع المبيعات\b",
        r"\bانتشار\b",
    ]
    for pattern in distribution_indicators:
        if re.search(pattern, q):
            return AnalysisType.DISTRIBUTION

    # 11. Exploratory analysis & open-ended deep dives -> EXPLORATORY_ANALYSIS
    exploratory_indicators = [
        r"\bexplore\b",
        r"\bexploratory\b",
        r"\bdeep dive\b",
        r"\boverview\b",
        r"\banalyze\b",
        r"\banalysis\b",
        r"\bperformance\b",
        r"\bevaluate\b",
        r"\bevaluation\b",
        r"\bحلل\b",
        r"\bتحليل\b",
        r"\bأداء\b",
        r"\bاداء\b",
        r"\bاستكشف\b",
        r"\bاستكشاف\b",
        r"\bنظرة عامة\b",
        r"\bتقييم\b",
    ]
    for pattern in exploratory_indicators:
        if re.search(pattern, q):
            return AnalysisType.EXPLORATORY_ANALYSIS

    # 12. Temporal trends & trajectories -> TREND
    trend_indicators = [
        r"\btrend\b",
        r"\btrends\b",
        r"\bover time\b",
        r"\bchange over\b",
        r"\bchanged over\b",
        r"\bchange across\b",
        r"\byear over year\b",
        r"\bmonth over month\b",
        r"\bgrowth rate\b",
        r"\bgrowth\b",
        r"\bhistorical\b",
        r"\bاتجاه\b",
        r"\bمسار\b",
        r"\bبمرور الوقت\b",
        r"\bعبر الزمن\b",
        r"\bتغير عبر\b",
        r"\bنمو\b",
        r"\bتطور\b",
        r"\bتاريخي\b",
    ]
    for pattern in trend_indicators:
        if re.search(pattern, q):
            return AnalysisType.TREND

    # 13. Simple Count -> COUNT
    if re.search(r"\b(how many|count|number of|كم|كام|كم عدد|عدد|احسب)\b", q):
        return AnalysisType.COUNT

    # 14. Ranking -> RANKING
    if re.search(r"\b(top|bottom|best|worst|highest|lowest|most|least|اعلى|أعلى|اقل|أقل|افضل|أفضل|اسوأ|أسوأ|اكثر|أكثر|اكتر)\b", q):
        return AnalysisType.RANKING

    # 15. Aggregation -> AGGREGATION
    if re.search(r"\b(total|sum|average|avg|min|max|minimum|maximum|اجمالي|إجمالي|مجموع|متوسط|معدل|حد ادنى|حد أقصى|اكبر|أكبر|اصغر|أصغر)\b", q):
        return AnalysisType.AGGREGATION

    # 16. Simple Lookup -> LOOKUP
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


def filter_schema_by_query(schema_text: str, query: str) -> str:
    """
    Extracts table names mentioned in a query (e.g., SQL statement or sub-question)
    and filters a DDL-formatted schema_text to only include those tables.
    Returns the original schema_text if no matching tables are found.
    """
    if not schema_text or not query:
        return schema_text

    # Extract all table names defined in the schema_text.
    # We look for lines like "table_name(" in the compact DDL format.
    table_lines = {}
    header_lines = []
    
    for line in schema_text.splitlines():
        if line.startswith("Database Schema") or line.startswith("..."):
            header_lines.append(line)
            continue
            
        match = re.match(r"^([a-zA-Z0-9_]+)\s*\(", line)
        if match:
            table_name = match.group(1)
            table_lines[table_name.lower()] = line

    if not table_lines:
        return schema_text

    # Find which tables are mentioned in the query
    q_lower = query.lower()
    matched_tables = set()
    for t_name in table_lines.keys():
        # Match table name as a distinct word in the query
        if re.search(rf"\b{re.escape(t_name)}\b", q_lower):
            matched_tables.add(t_name)

    if not matched_tables:
        return schema_text

    # Reconstruct the schema_text with only matched tables
    filtered_lines = list(header_lines)
    for t_name in sorted(matched_tables):
        filtered_lines.append(table_lines[t_name])

    return "\n".join(filtered_lines)


"""SQL query validator — enforces SELECT-only, read-only queries using sqlglot."""
import logging
import re
import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

# List of forbidden sqlglot expression types to enforce read-only SELECT safety
FORBIDDEN_EXPRESSION_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create,
    exp.Command, exp.Transaction, exp.Merge, exp.Schema, exp.Pragma,
)

FORBIDDEN_FUNCTIONS = {
    "pg_read_file", "pg_write_file", "pg_read_binary_file", "pg_ls_dir",
    "load_file", "into_outfile", "sys_eval", "sys_exec", "xp_cmdshell",
    "system", "eval", "sleep", "benchmark", "pg_sleep",
}

FORBIDDEN_SYSTEM_OBJECTS = {
    "pg_shadow", "pg_authid", "mysql.user", "information_schema.user_privileges",
    "master..syslogins", "master..sysprocesses",
}


def validate_sql(query: str) -> dict:
    """
    Validate that a SQL query is safe to execute using sqlglot AST parsing.
    Returns {"valid": bool, "reason": str, "query_type": str}
    """
    if not query or not query.strip():
        return {"valid": False, "reason": "Empty query", "query_type": "none"}

    # Check for raw multiple statements before sanitization
    raw_statements = [s.strip() for s in query.split(";") if s.strip()]
    if len(raw_statements) > 1:
        return {
            "valid": False,
            "reason": "Multiple SQL statements in a single request are forbidden.",
            "query_type": "unsafe",
        }

    cleaned = sanitize_query(query)
    if not cleaned:
        return {"valid": False, "reason": "No query found after sanitization", "query_type": "none"}

    try:
        target_dialect = get_target_dialect()
        # Parse all statements in the query
        statements = sqlglot.parse(cleaned, read=target_dialect)
        if not statements:
            return {"valid": False, "reason": "Could not parse SQL query", "query_type": "unknown"}

        if len(statements) > 1:
            return {
                "valid": False,
                "reason": "Multiple SQL statements in a single request are forbidden.",
                "query_type": "unsafe",
            }

        expression = statements[0]
        if expression is None:
            return {"valid": False, "reason": "Empty SQL statement", "query_type": "none"}

        # Traverse the AST to check for forbidden node types, functions, and system catalog access
        for node in expression.walk():
            if isinstance(node, FORBIDDEN_EXPRESSION_TYPES):
                return {
                    "valid": False,
                    "reason": f"Disallowed SQL operation detected: {node.__class__.__name__}. Only read-only SELECT queries are allowed.",
                    "query_type": "unsafe",
                }

            # Block dangerous functions
            if isinstance(node, (exp.Anonymous, exp.Func)):
                fname = getattr(node, "name", "") or ""
                if fname.lower() in FORBIDDEN_FUNCTIONS:
                    return {
                        "valid": False,
                        "reason": f"Forbidden administrative or file-access function detected: '{fname}'.",
                        "query_type": "unsafe",
                    }

            # Block sensitive system catalog access
            if isinstance(node, exp.Table):
                tname = node.name.lower()
                db_name = node.db.lower() if node.db else ""
                full_tname = f"{db_name}.{tname}" if db_name else tname
                if tname in FORBIDDEN_SYSTEM_OBJECTS or full_tname in FORBIDDEN_SYSTEM_OBJECTS:
                    return {
                        "valid": False,
                        "reason": f"Access to system catalog table '{full_tname}' is restricted.",
                        "query_type": "unsafe",
                    }

        # Ensure the statement is a Query, Select, Union, or CTE
        if not isinstance(expression, (exp.Query, exp.Select, exp.Union, exp.CTE, exp.Subquery)):
            return {
                "valid": False,
                "reason": f"Disallowed SQL statement structure: {expression.__class__.__name__}. Only SELECT queries are allowed.",
                "query_type": "unsafe",
            }

        return {"valid": True, "reason": "Query is safe", "query_type": "select"}

    except sqlglot.errors.ParseError as e:
        error_msg = re.sub(r'\x1b\[.*?m', '', str(e))
        return {
            "valid": False,
            "reason": f"SQL syntax error: {error_msg}",
            "query_type": "invalid"
        }
    except Exception as e:
        return {
            "valid": False,
            "reason": f"Validation error: {str(e)}",
            "query_type": "invalid"
        }


def transpile_sql_to_dialect(query: str, target_dialect: str) -> str:
    """
    Transpiles a query to the target dialect (e.g. 'sqlite' or 'postgres').
    If transpilation fails, returns the original query.
    """
    cleaned = sanitize_query(query)
    try:
        expression = sqlglot.parse_one(cleaned, read=target_dialect)
        
        # Enforce LIMIT (covers plain SELECT and UNION-style set queries;
        # both support .limit() in sqlglot). CTEs (WITH ... SELECT) are still
        # covered since their top-level node type is exp.Select.
        if isinstance(expression, (exp.Select, exp.Union)):
            if not expression.args.get("limit"):
                expression = expression.limit(500)
                
        return expression.sql(dialect=target_dialect, pretty=True)
    except Exception as e:
        logger.debug("Failed to transpile SQL to dialect '%s': %s", target_dialect, e)
        return cleaned


def get_target_dialect() -> str:
    """Determine target SQL dialect dynamically from active database engine."""
    from app.services.database import db
    try:
        name = db.get_engine().dialect.name.lower()
        if name in ("postgres", "postgresql"):
            return "postgres"
        elif name in ("mysql", "mariadb"):
            return "mysql"
        elif name == "oracle":
            return "oracle"
        elif name in ("mssql", "microsoft"):
            return "tsql"
        return "sqlite"
    except Exception:
        return "sqlite"




