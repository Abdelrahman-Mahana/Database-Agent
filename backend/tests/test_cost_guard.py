import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.security.cost_guard import (
    check_query_cost,
    CostCheckResult,
    cost_guard_failure_result,
    _extract_referenced_tables,
    _analyze_query_ast,
    estimate_db_cost,
)
from app.core.config.settings import settings
from app.models.schema_catalog.models import SchemaCatalog, TableProfile
from app.services.sql_service import SQLExecutor


@pytest.fixture
def mock_catalog():
    catalog = SchemaCatalog(fingerprint="mock", dialect="sqlite", database_name="mock_db")
    
    t1 = TableProfile(name="users")
    t1.row_count = 600000
    
    t2 = TableProfile(name="orders")
    t2.row_count = 100

    t3 = TableProfile(name="large_events")
    t3.row_count = 2000000
    
    catalog.tables["users"] = t1
    catalog.tables["orders"] = t2
    catalog.tables["large_events"] = t3
    return catalog


def test_extract_referenced_tables_ast():
    sql = "WITH active_users AS (SELECT * FROM users WHERE active = 1) SELECT u.name, o.total FROM active_users u JOIN orders o ON u.id = o.user_id"
    known = {"users", "orders", "products"}
    tables = _extract_referenced_tables(sql, known)
    assert set(tables) == {"users", "orders"}


def test_analyze_query_ast():
    ast1 = _analyze_query_ast("SELECT * FROM users LIMIT 25")
    assert ast1["has_limit"] is True
    assert ast1["limit_value"] == 25
    assert ast1["has_where"] is False

    ast2 = _analyze_query_ast("SELECT name, COUNT(*) FROM users WHERE age > 21 GROUP BY name")
    assert ast2["has_limit"] is False
    assert ast2["has_where"] is True
    assert ast2["is_aggregate"] is True


def test_check_query_cost_allowed(mock_catalog):
    # Has LIMIT
    res = check_query_cost("SELECT * FROM users LIMIT 10", mock_catalog, max_unfiltered_rows=500000)
    assert res.allowed is True

    # Has WHERE
    res = check_query_cost("SELECT * FROM users WHERE id = 1", mock_catalog, max_unfiltered_rows=500000)
    assert res.allowed is True

    # Small table (orders has 100 rows, threshold is 500k)
    res = check_query_cost("SELECT * FROM orders", mock_catalog, max_unfiltered_rows=500000)
    assert res.allowed is True
    assert res.estimated_rows_scanned == 100


def test_check_query_cost_blocked_unfiltered_scan(mock_catalog):
    # Large table, no filter/limit (users has 600k rows, threshold is 500k)
    res = check_query_cost("SELECT * FROM users", mock_catalog, max_unfiltered_rows=500000)
    assert res.allowed is False
    assert res.estimated_rows_scanned == 600000
    assert "Query has no WHERE/LIMIT" in res.reason


def test_check_query_cost_with_explain_and_execution_bounds(mock_catalog):
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE test_items (id INT PRIMARY KEY, name VARCHAR, val INT);"))
        for i in range(50):
            conn.execute(text(f"INSERT INTO test_items VALUES ({i}, 'item_{i}', {i * 10});"))
        conn.commit()

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # 1. Test EXPLAIN estimation
    rows, cost, unindexed = estimate_db_cost("SELECT * FROM test_items WHERE val > 100", session)
    assert unindexed is True  # SQLite will use unindexed SCAN on unindexed column `val`

    # 2. Test execution cap in SQLExecutor
    all_rows = SQLExecutor.execute("SELECT * FROM test_items;", session, max_rows=10)
    assert len(all_rows) == 10  # Capped at 10 rows

    session.close()


def test_cost_guard_failure_blocks_high_risk_query(mock_catalog, monkeypatch):
    """A failed guard must not allow an unbounded scan of a known large table."""
    monkeypatch.setattr(settings, "cost_guard_fail_closed_on_high_risk", True)

    result = cost_guard_failure_result(
        "SELECT * FROM users",
        catalog=mock_catalog,
        max_unfiltered_rows=500_000,
        error=RuntimeError("EXPLAIN unavailable"),
    )

    assert result.allowed is False
    assert "cost estimation failed" in (result.reason or "").lower()


def test_cost_guard_failure_warns_but_allows_low_risk_query(mock_catalog, monkeypatch):
    """A failed estimate remains best-effort for a bounded/low-risk query."""
    monkeypatch.setattr(settings, "cost_guard_fail_closed_on_high_risk", True)

    result = cost_guard_failure_result(
        "SELECT * FROM orders WHERE id = 1",
        catalog=mock_catalog,
        error=RuntimeError("EXPLAIN unavailable"),
    )

    assert result.allowed is True
    assert "estimation was unavailable" in (result.reason or "").lower()


def test_cost_guard_failure_respects_fail_closed_setting(mock_catalog, monkeypatch):
    monkeypatch.setattr(settings, "cost_guard_fail_closed_on_high_risk", False)

    result = cost_guard_failure_result("SELECT * FROM users", catalog=mock_catalog)

    assert result.allowed is True
