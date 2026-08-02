"""Tests for Phase 3 (retrieval), 5 (safety), 6 (report cache), 7 (long-term
memory), 8 (cost dashboard), and 10 (rate limiting) additions.

Run with: pytest backend/tests/test_rebuild_plan_2.py -v
(requires project dependencies installed — see test_rebuild_plan.py's note)
"""
import pytest

from app.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile


# --------------------------------------------------------------------------
# Phase 3: TF-IDF retrieval for large schemas
# --------------------------------------------------------------------------

def _big_catalog() -> SchemaCatalog:
    cat = SchemaCatalog(fingerprint="x", dialect="SQLITE", database_name="BigDB")
    cat.tables["tbl_orders"] = TableProfile(
        name="tbl_orders", description="Customer purchase orders and totals",
        synonyms=["orders", "purchases"],
        columns=[ColumnProfile(name="freight", type="DECIMAL", description="shipping cost")],
    )
    cat.tables["tbl_employees_hr"] = TableProfile(
        name="tbl_employees_hr", description="HR records of staff members",
        synonyms=["employees", "staff"],
        columns=[ColumnProfile(name="salary", type="DECIMAL", description="employee salary")],
    )
    cat.glossary_enriched = True
    return cat


def test_tfidf_retrieval_ranks_relevant_table_first():
    from app.schema_catalog.retrieval import retrieve_relevant_tables

    top = retrieve_relevant_tables("show me all customer orders and shipping cost", _big_catalog(), k=2)
    assert top[0] == "tbl_orders"


def test_tfidf_retrieval_empty_without_glossary():
    from app.schema_catalog.retrieval import retrieve_relevant_tables

    cat = SchemaCatalog(fingerprint="y", dialect="SQLITE", database_name="X")
    assert retrieve_relevant_tables("anything", cat) == []


# --------------------------------------------------------------------------
# Phase 5: cost guard + data masking
# --------------------------------------------------------------------------

def test_cost_guard_blocks_large_unfiltered_scan():
    from app.security.cost_guard import check_query_cost

    cat = SchemaCatalog(fingerprint="x", dialect="SQLITE", database_name="Test")
    cat.tables["Orders"] = TableProfile(name="Orders", columns=[], row_count=2_000_000)

    blocked = check_query_cost("SELECT * FROM Orders", cat, max_unfiltered_rows=500_000)
    assert blocked.allowed is False

    allowed = check_query_cost("SELECT * FROM Orders WHERE OrderID = 1", cat, max_unfiltered_rows=500_000)
    assert allowed.allowed is True

    agg_allowed = check_query_cost("SELECT COUNT(*) FROM Orders", cat, max_unfiltered_rows=500_000)
    assert agg_allowed.allowed is True


def test_cost_guard_fails_open_without_catalog():
    from app.security.cost_guard import check_query_cost

    result = check_query_cost("SELECT * FROM AnyTable", None, max_unfiltered_rows=100)
    assert result.allowed is True


def test_data_masking_masks_sensitive_columns_only():
    from app.security.data_masking import mask_sensitive_columns

    rows = [{"id": 1, "name": "Ali", "password": "hunter2"}]
    masked, masked_cols = mask_sensitive_columns(rows)
    assert masked_cols == ["password"]
    assert masked[0]["password"] == "***MASKED***"
    assert masked[0]["name"] == "Ali"
    assert rows[0]["password"] == "hunter2"  # original untouched


# --------------------------------------------------------------------------
# Phase 7: long-term memory
# --------------------------------------------------------------------------

def test_long_term_memory_save_list_delete(monkeypatch):
    from app.services import long_term_memory as ltm_module

    # Force the in-process fallback path regardless of test-env Redis config.
    monkeypatch.setattr(ltm_module, "_redis_client", None)
    monkeypatch.setattr(ltm_module, "_local_store", {})
    store = ltm_module.LongTermMemoryStore()

    saved = store.save_query("user1", "How many customers?", "SELECT COUNT(*) FROM Customer", label="fav")
    assert len(store.list_saved_queries("user1")) == 1

    store.set_preference("user1", "chart_type", "bar")
    assert store.get_preferences("user1")["chart_type"] == "bar"

    assert store.delete_saved_query("user1", saved.id) is True
    assert store.list_saved_queries("user1") == []


# --------------------------------------------------------------------------
# Phase 8: cost dashboard
# --------------------------------------------------------------------------

def test_cost_dashboard_aggregates_by_type_and_day():
    from app.utils.cost_dashboard import CostDashboard

    dash = CostDashboard()
    dash.record(prompt_tokens=1000, completion_tokens=200, model="google/gemini-2.5-flash", analysis_type="count")
    dash.record(prompt_tokens=2000, completion_tokens=500, model="google/gemini-2.5-flash", analysis_type="comparison")

    summary = dash.summary()
    assert summary["total_requests"] == 2
    assert summary["total_estimated_cost_usd"] > 0
    assert summary["by_analysis_type"]["count"]["prompt_tokens"] == 1000


# --------------------------------------------------------------------------
# Phase 10: rate limiting
# --------------------------------------------------------------------------

def test_token_bucket_limits_bursts():
    from app.middleware.rate_limit import _TokenBucket

    bucket = _TokenBucket(rate_per_minute=3)
    results = [bucket.try_consume() for _ in range(5)]
    assert results == [True, True, True, False, False]
