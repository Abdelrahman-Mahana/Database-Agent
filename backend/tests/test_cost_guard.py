import pytest
from app.security.cost_guard import check_query_cost, CostCheckResult, _extract_referenced_tables
from app.schema_catalog.models import SchemaCatalog, TableProfile

@pytest.fixture
def mock_catalog():
    catalog = SchemaCatalog(fingerprint="mock", dialect="sqlite", database_name="mock_db")
    
    t1 = TableProfile(name="users")
    t1.row_count = 600000
    
    t2 = TableProfile(name="orders")
    t2.row_count = 100
    
    catalog.tables["users"] = t1
    catalog.tables["orders"] = t2
    return catalog

def test_extract_referenced_tables():
    sql = "SELECT * FROM users JOIN orders ON users.id = orders.user_id"
    known = {"users", "orders", "products"}
    tables = _extract_referenced_tables(sql, known)
    assert set(tables) == {"users", "orders"}

def test_check_query_cost_allowed(mock_catalog):
    # Has LIMIT
    res = check_query_cost("SELECT * FROM users LIMIT 10", mock_catalog, max_unfiltered_rows=500000)
    assert res.allowed is True

    # Has WHERE
    res = check_query_cost("SELECT * FROM users WHERE id = 1", mock_catalog, max_unfiltered_rows=500000)
    assert res.allowed is True

    # Has AGGREGATION
    res = check_query_cost("SELECT COUNT(*) FROM users", mock_catalog, max_unfiltered_rows=500000)
    assert res.allowed is True

    # Small table (orders has 100 rows, threshold is 500k)
    res = check_query_cost("SELECT * FROM orders", mock_catalog, max_unfiltered_rows=500000)
    assert res.allowed is True
    assert res.estimated_rows_scanned == 100

def test_check_query_cost_blocked(mock_catalog):
    # Large table, no filter/limit (users has 600k rows, threshold is 500k)
    res = check_query_cost("SELECT * FROM users", mock_catalog, max_unfiltered_rows=500000)
    assert res.allowed is False
    assert res.estimated_rows_scanned == 600000
    assert "Query has no WHERE/LIMIT" in res.reason
