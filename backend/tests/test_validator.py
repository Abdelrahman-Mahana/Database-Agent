import pytest
from app.utils.validator import validate_sql, transpile_sql_to_dialect

def test_validate_sql_safe_queries(monkeypatch):
    monkeypatch.setattr("app.utils.validator.get_target_dialect", lambda: "postgres")
    
    # Valid SELECT
    res = validate_sql("SELECT * FROM users;")
    assert res["valid"] is True
    assert res["query_type"] == "select"

    # Valid SELECT with JOIN
    res = validate_sql("SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id;")
    assert res["valid"] is True

    # Valid CTE
    res = validate_sql("WITH active_users AS (SELECT * FROM users WHERE active = True) SELECT * FROM active_users;")
    assert res["valid"] is True

def test_validate_sql_forbidden_queries(monkeypatch):
    monkeypatch.setattr("app.utils.validator.get_target_dialect", lambda: "postgres")
    
    # DELETE
    res = validate_sql("DELETE FROM users;")
    assert res["valid"] is False
    assert "Disallowed SQL statement structure" in res["reason"] or "Disallowed SQL operation detected" in res["reason"]

    # DROP TABLE
    res = validate_sql("DROP TABLE users;")
    assert res["valid"] is False
    assert "Disallowed SQL operation detected: Drop" in res["reason"]

    # UPDATE
    res = validate_sql("UPDATE users SET admin = True;")
    assert res["valid"] is False
    assert "Disallowed SQL statement structure" in res["reason"] or "Disallowed SQL operation detected" in res["reason"]

    # Multi-statement injection is safely truncated by sanitize_query to just the SELECT, so it passes validation as a safe SELECT.
    res = validate_sql("SELECT * FROM users; DROP TABLE users;")
    assert res["valid"] is True

def test_transpile_sql_to_dialect_limit_enforced(monkeypatch):
    # It should automatically append LIMIT 500 if no limit exists
    transpiled = transpile_sql_to_dialect("SELECT * FROM users", "sqlite")
    assert "LIMIT 500" in transpiled.upper()

    # It should NOT append another LIMIT if one exists
    transpiled = transpile_sql_to_dialect("SELECT * FROM users LIMIT 10", "sqlite")
    assert "LIMIT 10" in transpiled.upper()
    assert "LIMIT 500" not in transpiled.upper()


def test_dialect_aware_sql_prompt_builder():
    from app.sql.prompt_builder import SQLPromptBuilder
    from app.sql.dialect_rules import get_dialect_guidelines

    builder = SQLPromptBuilder()

    # 1. PostgreSQL Prompt
    pg_payload = builder.build_generation_input(
        schema_text="users(id:INT PK, name:VARCHAR)",
        question="Find active users",
        dialect="postgresql",
    )
    formatted_pg = builder.zero_shot_template.format(**pg_payload)
    assert "Target SQL Dialect: PostgreSQL" in formatted_pg
    assert "ILIKE" in formatted_pg
    assert "EXTRACT(YEAR FROM date_col)" in formatted_pg

    # 2. MySQL Prompt
    mysql_payload = builder.build_generation_input(
        schema_text="users(id:INT PK, name:VARCHAR)",
        question="Find active users",
        dialect="mysql",
    )
    formatted_mysql = builder.zero_shot_template.format(**mysql_payload)
    assert "Target SQL Dialect: MySQL" in formatted_mysql
    assert "CONCAT(a, b)" in formatted_mysql
    assert "YEAR(date_col)" in formatted_mysql

    # 3. MSSQL Prompt
    mssql_payload = builder.build_generation_input(
        schema_text="users(id:INT PK, name:VARCHAR)",
        question="Find active users",
        dialect="mssql",
    )
    formatted_mssql = builder.zero_shot_template.format(**mssql_payload)
    assert "Target SQL Dialect: Microsoft SQL Server" in formatted_mssql
    assert "TOP n" in formatted_mssql
    assert "STRING_AGG" in formatted_mssql

    # 4. Oracle Prompt
    oracle_payload = builder.build_generation_input(
        schema_text="users(id:INT PK, name:VARCHAR)",
        question="Find active users",
        dialect="oracle",
    )
    formatted_oracle = builder.zero_shot_template.format(**oracle_payload)
    assert "Target SQL Dialect: Oracle SQL" in formatted_oracle
    assert "FETCH FIRST n ROWS ONLY" in formatted_oracle

    # 5. Fix Template Dialect Awareness
    fix_payload = builder.build_fix_input(
        schema_text="users(id:INT PK)",
        question="Top 10 users",
        failed_sql="SELECT * FROM users LIMIT 10;",
        error="Incorrect syntax near LIMIT",
        dialect="mssql",
    )
    formatted_fix = builder.fix_template.format(**fix_payload)
    assert "Target SQL Dialect: Microsoft SQL Server" in formatted_fix
    assert "TOP n" in formatted_fix
