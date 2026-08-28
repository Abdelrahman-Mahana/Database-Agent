"""Dialect-specific SQL syntax rules, date functions, and query guidelines."""
from __future__ import annotations

from typing import Dict


_DIALECT_RULES: Dict[str, str] = {
    "postgresql": """Target SQL Dialect: PostgreSQL
- Case-Sensitivity & Quoting: In PostgreSQL, unquoted identifiers are automatically folded to lowercase. You MUST enclose table names and column names that have capital/uppercase letters, mixed casing, or special characters in double quotes (e.g., "public"."Dose", "Dose", "ColumnName"). Match the exact casing from the <schema>.
- String matching: Use ILIKE for case-insensitive matching (e.g. name ILIKE '%term%').
- Date extraction: Use EXTRACT(YEAR FROM date_col), EXTRACT(MONTH FROM date_col) or TO_CHAR(date_col, 'YYYY-MM').
- Date arithmetic: Use date_col + INTERVAL '1 day', CURRENT_DATE, NOW().
- String concatenation: Use || or CONCAT(a, b).
- Pagination: Use LIMIT n OFFSET m.
- Type casting: Use standard CAST(col AS type) or col::type.
- Nulls sorting: Supports NULLS FIRST / NULLS LAST.""",

    "postgres": """Target SQL Dialect: PostgreSQL
- Case-Sensitivity & Quoting: In PostgreSQL, unquoted identifiers are automatically folded to lowercase. You MUST enclose table names and column names that have capital/uppercase letters, mixed casing, or special characters in double quotes (e.g., "public"."Dose", "Dose", "ColumnName"). Match the exact casing from the <schema>.
- String matching: Use ILIKE for case-insensitive matching (e.g. name ILIKE '%term%').
- Date extraction: Use EXTRACT(YEAR FROM date_col), EXTRACT(MONTH FROM date_col) or TO_CHAR(date_col, 'YYYY-MM').
- Date arithmetic: Use date_col + INTERVAL '1 day', CURRENT_DATE, NOW().
- String concatenation: Use || or CONCAT(a, b).
- Pagination: Use LIMIT n OFFSET m.
- Type casting: Use standard CAST(col AS type) or col::type.
- Nulls sorting: Supports NULLS FIRST / NULLS LAST.""",

    "mysql": """Target SQL Dialect: MySQL / MariaDB
- String matching: Use LIKE for text search (default collation is case-insensitive).
- Date extraction: Use YEAR(date_col), MONTH(date_col), DATE_FORMAT(date_col, '%Y-%m').
- Date arithmetic: Use DATE_ADD(date_col, INTERVAL 1 DAY), DATE_SUB(), CURDATE(), NOW().
- String concatenation: MUST use CONCAT(a, b) (do NOT use || as it defaults to logical OR).
- Pagination: Use LIMIT n OFFSET m.
- Grouping aggregation: Use GROUP_CONCAT(col SEPARATOR ', ').
- Quoting: Use backticks `table_name` if table or column names clash with keywords.""",

    "mariadb": """Target SQL Dialect: MariaDB / MySQL
- String matching: Use LIKE for text search (default collation is case-insensitive).
- Date extraction: Use YEAR(date_col), MONTH(date_col), DATE_FORMAT(date_col, '%Y-%m').
- Date arithmetic: Use DATE_ADD(date_col, INTERVAL 1 DAY), DATE_SUB(), CURDATE(), NOW().
- String concatenation: MUST use CONCAT(a, b) (do NOT use || as it defaults to logical OR).
- Pagination: Use LIMIT n OFFSET m.
- Grouping aggregation: Use GROUP_CONCAT(col SEPARATOR ', ').""",

    "tsql": """Target SQL Dialect: Microsoft SQL Server (T-SQL)
- String matching: Use LIKE for case-insensitive matching.
- Date extraction: Use YEAR(date_col), MONTH(date_col), FORMAT(date_col, 'yyyy-MM'), DATEPART(year, date_col).
- Date arithmetic: Use DATEADD(day, 1, date_col), DATEDIFF(day, start_date, end_date), GETDATE().
- String concatenation: Use + or CONCAT(a, b).
- Pagination: Use TOP n in SELECT or OFFSET 0 ROWS FETCH NEXT n ROWS ONLY with ORDER BY. (Do NOT use LIMIT).
- Grouping aggregation: Use STRING_AGG(col, ', ').
- Quoting: Use square brackets [table_name] if names clash with keywords.""",

    "mssql": """Target SQL Dialect: Microsoft SQL Server (T-SQL)
- String matching: Use LIKE for case-insensitive matching.
- Date extraction: Use YEAR(date_col), MONTH(date_col), FORMAT(date_col, 'yyyy-MM'), DATEPART(year, date_col).
- Date arithmetic: Use DATEADD(day, 1, date_col), DATEDIFF(day, start_date, end_date), GETDATE().
- String concatenation: Use + or CONCAT(a, b).
- Pagination: Use TOP n in SELECT or OFFSET 0 ROWS FETCH NEXT n ROWS ONLY with ORDER BY. (Do NOT use LIMIT).
- Grouping aggregation: Use STRING_AGG(col, ', ').
- Quoting: Use square brackets [table_name] if names clash with keywords.""",

    "oracle": """Target SQL Dialect: Oracle SQL
- String matching: Use REGEXP_LIKE(col, 'term', 'i') or UPPER(col) LIKE '%TERM%'.
- Date extraction: Use EXTRACT(YEAR FROM date_col), TO_CHAR(date_col, 'YYYY-MM'), TO_CHAR(date_col, 'YYYY').
- Date arithmetic: Use date_col + 1, ADD_MONTHS(date_col, 1), SYSDATE.
- String concatenation: Use || or CONCAT(a, b).
- Pagination: Use FETCH FIRST n ROWS ONLY (or ROWNUM <= n). (Do NOT use LIMIT).
- Grouping aggregation: Use LISTAGG(col, ', ') WITHIN GROUP (ORDER BY col).
- Quoting: Use double quotes "TABLE_NAME" for case-sensitive identifiers.""",

    "sqlite": """Target SQL Dialect: SQLite
- String matching: Use LIKE for case-insensitive ASCII matching.
- Date extraction: Use strftime('%Y', date_col), strftime('%m', date_col), strftime('%Y-%m', date_col).
- Date arithmetic: Use date(date_col, '+1 day'), datetime(date_col, '+1 hour'), DATE('now').
- String concatenation: Use ||.
- Pagination: Use LIMIT n OFFSET m.
- Grouping aggregation: Use GROUP_CONCAT(col, ', ').""",

    "duckdb": """Target SQL Dialect: DuckDB
- String matching: Use ILIKE for case-insensitive matching.
- Date extraction: Use EXTRACT(YEAR FROM date_col), strftime(date_col, '%Y-%m').
- Date arithmetic: Use date_col + INTERVAL 1 DAY, current_date.
- String concatenation: Use || or CONCAT(a, b).
- Pagination: Use LIMIT n OFFSET m.""",

    "snowflake": """Target SQL Dialect: Snowflake
- String matching: Use ILIKE for case-insensitive matching.
- Date extraction: Use DATE_TRUNC('month', date_col), EXTRACT(YEAR FROM date_col), TO_VARCHAR(date_col, 'YYYY-MM').
- Date arithmetic: Use DATEADD(day, 1, date_col), CURRENT_TIMESTAMP().
- String concatenation: Use || or CONCAT(a, b).
- Pagination: Use LIMIT n OFFSET m.""",

    "bigquery": """Target SQL Dialect: Google BigQuery (Standard SQL)
- String matching: Use REGEXP_CONTAINS(col, r'(?i)term') or LOWER(col) LIKE '%term%'.
- Date extraction: Use EXTRACT(YEAR FROM date_col), FORMAT_DATE('%Y-%m', date_col).
- Date arithmetic: Use DATE_ADD(date_col, INTERVAL 1 DAY), CURRENT_DATE().
- String concatenation: Use CONCAT(a, b).
- Pagination: Use LIMIT n OFFSET m.""",

    "clickhouse": """Target SQL Dialect: ClickHouse
- String matching: Use ilike(col, '%term%') or positionCaseInsensitive(col, 'term') > 0.
- Date extraction: Use toYear(date_col), toMonth(date_col), formatDateTime(date_col, '%Y-%m').
- Date arithmetic: Use addDays(date_col, 1), today(), now().
- String concatenation: Use concat(a, b).
- Pagination: Use LIMIT n OFFSET m.""",
}


def get_dialect_guidelines(dialect: str) -> str:
    """Return tailored syntax guidelines and functions for the specified database dialect."""
    d = (dialect or "").lower().strip()
    return _DIALECT_RULES.get(d, f"Target SQL Dialect: {dialect.upper() or 'Standard SQL'}\n- Write clean, standard ANSI SQL queries.\n- Use standard CAST(col AS type) for conversions.\n- Use appropriate date and aggregation functions compatible with {dialect}.")
