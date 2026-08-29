import pytest
from app.utils.helpers import validate_sql, transpile_sql_to_dialect

def test_validate_sql_safe_queries(monkeypatch):
    monkeypatch.setattr("app.utils.helpers.get_target_dialect", lambda: "postgres")
    
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
    monkeypatch.setattr("app.utils.helpers.get_target_dialect", lambda: "postgres")
    
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

    # Multi-statement injection is strictly rejected
    res = validate_sql("SELECT * FROM users; DROP TABLE users;")
    assert res["valid"] is False
    assert "Multiple SQL statements" in res["reason"]

def test_transpile_sql_to_dialect_limit_enforced(monkeypatch):
    # It should automatically append LIMIT 500 if no limit exists
    transpiled = transpile_sql_to_dialect("SELECT * FROM users", "sqlite")
    assert "LIMIT 500" in transpiled.upper()

    # It should NOT append another LIMIT if one exists
    transpiled = transpile_sql_to_dialect("SELECT * FROM users LIMIT 10", "sqlite")
    assert "LIMIT 10" in transpiled.upper()
    assert "LIMIT 500" not in transpiled.upper()


def test_dialect_aware_sql_prompt_builder():
    from app.services.sql.prompt_builder import SQLPromptBuilder
    from app.services.sql.dialect_rules import get_dialect_guidelines

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


def test_validate_execution_ast_and_explain():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.sql.validator import SQLValidator
    from app.services.sql_service import SQLExecutor

    # Create in-memory SQLite database
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(create_engine("sqlite:///:memory:").dialect.statement_compiler(None, None).compile) if False else None
        from sqlalchemy import text
        conn.execute(text("CREATE TABLE customers (id INT PRIMARY KEY, name VARCHAR, balance FLOAT);"))
        conn.execute(text("INSERT INTO customers VALUES (1, 'Alice', 100.0);"))
        conn.commit()

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    validator = SQLValidator()

    # 1. Valid SELECT passes AST and EXPLAIN
    valid, err = validator.validate_execution("SELECT name, balance FROM customers WHERE balance > 50;", session)
    assert valid is True
    assert err is None

    # 2. Invalid column fails at EXPLAIN level
    valid, err = validator.validate_execution("SELECT nonexistent_column FROM customers;", session)
    assert valid is False
    assert "no such column" in str(err).lower()

    # 3. Invalid table fails at EXPLAIN level
    valid, err = validator.validate_execution("SELECT * FROM nonexistent_table;", session)
    assert valid is False
    assert "no such table" in str(err).lower()

    # 4. Unsafe mutation query (DELETE/DROP) fails at AST level before hitting DB
    valid, err = validator.validate_execution("DELETE FROM customers WHERE id = 1;", session)
    assert valid is False
    assert "Disallowed SQL" in str(err) or "AST validation failed" in str(err)

    # 5. Explain does not modify state
    valid, err = SQLExecutor.explain("SELECT * FROM customers;", session)
    assert valid is True
    assert err is None

    session.close()
