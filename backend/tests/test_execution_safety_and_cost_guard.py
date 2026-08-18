import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.services.sql_service import SQLExecutor
from app.security.cost_guard import check_query_cost, _detect_cartesian_product
from app.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile


@pytest.fixture
def sqlite_db_session():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, bio TEXT)")
        for i in range(100):
            conn.exec_driver_sql(f"INSERT INTO users (id, username, bio) VALUES ({i}, 'user_{i}', 'bio_{i * 10}')")

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_sql_executor_row_limit_truncation(sqlite_db_session):
    """Test SQLExecutor.execute truncates results exceeding max_rows."""
    executor = SQLExecutor()
    # Request 100 rows with a max_rows limit of 25
    rows = executor.execute("SELECT * FROM users", sqlite_db_session, max_rows=25)
    assert len(rows) == 25


def test_sql_executor_byte_limit_truncation(sqlite_db_session, monkeypatch):
    """Test SQLExecutor.execute safely truncates results exceeding cost_guard_max_returned_bytes."""
    from app.config.settings import settings
    # Set tight byte limit (e.g. 500 bytes)
    monkeypatch.setattr(settings, "cost_guard_max_returned_bytes", 500)

    executor = SQLExecutor()
    rows = executor.execute("SELECT * FROM users", sqlite_db_session, max_rows=100)
    assert len(rows) < 100
    assert len(rows) > 0


def test_sql_executor_read_only_pragma(sqlite_db_session):
    """SQLite query_only is scoped to the execution and does not leak in the session."""
    executor = SQLExecutor()
    rows = executor.execute("SELECT count(*) as count FROM users", sqlite_db_session)
    assert len(rows) == 1
    assert rows[0]["count"] == 100

    # The same physical SQLite connection is usable for writes afterwards.
    # This guards against pooled connections inheriting PRAGMA query_only = ON.
    assert sqlite_db_session.execute(text("PRAGMA query_only")).scalar() == 0
    sqlite_db_session.execute(text("INSERT INTO users (id, username, bio) VALUES (101, 'next', 'ok')"))
    sqlite_db_session.commit()


def test_cartesian_product_detection():
    """Test AST detection of unconstrained cross joins and Cartesian products."""
    assert _detect_cartesian_product("SELECT * FROM table_a CROSS JOIN table_b") is True
    assert _detect_cartesian_product("SELECT * FROM table_a, table_b") is True
    assert _detect_cartesian_product("SELECT * FROM table_a JOIN table_b ON table_a.id = table_b.a_id") is False
    assert _detect_cartesian_product("SELECT * FROM table_a, table_b WHERE table_a.id = table_b.a_id") is False


def test_cost_guard_fail_closed_on_cartesian_product():
    """Test cost guard blocks unconstrained Cartesian products without LIMIT."""
    catalog = SchemaCatalog(
        fingerprint="fp_guard",
        dialect="sqlite",
        database_name="TestDB",
        tables={
            "table_a": TableProfile(name="table_a", columns=[], row_count=2000),
            "table_b": TableProfile(name="table_b", columns=[], row_count=2000),
        },
    )

    # 1. Unconstrained cross join fails closed
    cross_join_sql = "SELECT * FROM table_a CROSS JOIN table_b"
    result = check_query_cost(cross_join_sql, catalog=catalog)
    assert result.allowed is False
    assert "Cartesian product" in (result.reason or "")

    # 2. Bounded with small LIMIT passes
    bounded_sql = "SELECT * FROM table_a CROSS JOIN table_b LIMIT 50"
    bounded_result = check_query_cost(bounded_sql, catalog=catalog)
    assert bounded_result.allowed is True


def test_cost_guard_fail_closed_on_massive_unfiltered_scan():
    """Test cost guard blocks full table scans on large tables exceeding threshold without WHERE/LIMIT."""
    catalog = SchemaCatalog(
        fingerprint="fp_guard_large",
        dialect="sqlite",
        database_name="TestDB",
        tables={
            "big_table": TableProfile(name="big_table", columns=[], row_count=1_000_000),
        },
    )

    # Unfiltered scan on 1M row table fails closed
    unfiltered_sql = "SELECT * FROM big_table"
    result = check_query_cost(unfiltered_sql, catalog=catalog, max_unfiltered_rows=500_000)
    assert result.allowed is False
    assert "would scan an estimated 1,000,000 rows" in (result.reason or "")
