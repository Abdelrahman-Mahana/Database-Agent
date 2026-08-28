"""Tests for delayed final-approval SQL caching and robust semantic/schema versioning."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.orchestration.sql_generator import SQLGenerator
from app.utils.cache import (
    clear_all_caches,
    get_cached_sql,
    set_cached_sql,
    get_cached_results,
    set_cached_results,
)
from app.utils.text_processor import normalize_sql
from app.models.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile


@pytest.fixture(autouse=True)
def clean_cache():
    clear_all_caches()
    yield
    clear_all_caches()


@pytest.mark.asyncio
async def test_generate_sql_does_not_prematurely_cache_unverified_sql():
    """Verify generate_sql alone does NOT commit candidate SQL to cache before execution."""
    generator = SQLGenerator(MagicMock(), MagicMock())
    generator.self_consistency_chain = MagicMock()

    mock_resp = MagicMock()
    mock_resp.content = "SELECT total FROM invoices WHERE id = 1"
    mock_resp.response_metadata = {}
    generator.sql_generation_chain = MagicMock()
    generator.sql_generation_chain.ainvoke = AsyncMock(return_value=mock_resp)

    mock_db = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.schema = {"invoices": {"columns": [{"name": "total", "type": "FLOAT"}]}}
    mock_ctx.catalog = None
    mock_ctx.total_tables = 1
    mock_ctx.total_columns = 1
    mock_ctx.get_semantic_version.return_value = "sem_v1"

    with patch.object(generator.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(generator.schema_service, "_get_db_fingerprint", return_value="fp1"), \
         patch.object(generator.schema_service, "get_semantic_schema_version", return_value="sem_v1"), \
         patch.object(generator.validator, "validate_execution", return_value=(True, None)), \
         patch("app.agent.orchestration.sql_generator.settings") as mock_settings:

        mock_settings.enable_self_consistency = False
        mock_settings.sql_candidates = 1

        sql = await generator.generate_sql("What is total for invoice 1?", "schema_text", db=mock_db)

    assert "total" in sql and "invoices" in sql

    # Verify that get_cached_sql returns None because it was NOT executed yet!
    cached, _ = get_cached_sql(
        "What is total for invoice 1?",
        "schema_text",
        database_fingerprint="fp1",
        dialect="sqlite",
        schema_version="sem_v1",
    )
    assert cached is None, "Unexecuted candidate SQL must NOT be written to cache!"


@pytest.mark.asyncio
async def test_execute_with_repair_caches_repaired_sql_on_success():
    """Verify that when SQL is repaired, the final repaired SQL is committed to cache."""
    generator = SQLGenerator(MagicMock(), MagicMock())
    mock_db = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.schema = {"invoices": {"columns": [{"name": "total", "type": "FLOAT"}]}}
    mock_ctx.catalog = None
    mock_ctx.total_tables = 1
    mock_ctx.total_columns = 1
    mock_ctx.get_semantic_version.return_value = "sem_v1"

    initial_bad_sql = "SELECT invalid_col FROM invoices"
    repaired_good_sql = "SELECT total FROM invoices LIMIT 500"

    with patch.object(generator.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(generator.schema_service, "_get_db_fingerprint", return_value="fp1"), \
         patch.object(generator.schema_service, "get_database_type", return_value="SQLITE"), \
         patch.object(generator.schema_service, "get_semantic_schema_version", return_value="sem_v1"), \
         patch.object(generator.schema_service, "get_data_freshness_token", return_value="fresh_1"), \
         patch.object(generator, "fix_sql", new_callable=AsyncMock) as mock_fix, \
         patch.object(generator.sql_executor, "execute") as mock_exec:

        mock_fix.return_value = repaired_good_sql
        # First call on initial_bad_sql fails, second call on repaired_good_sql succeeds
        mock_exec.side_effect = [Exception("no such column: invalid_col"), [{"total": 100.0}]]

        rows, final_sql, err, err_type, _ = await generator.execute_with_repair(
            question="What is total revenue?",
            schema_text="schema_text",
            sql=initial_bad_sql,
            db=mock_db,
            max_fix_attempts=1,
        )

    assert err is None
    assert rows == [{"total": 100.0}]
    assert normalize_sql(final_sql) == normalize_sql(repaired_good_sql)

    # Verify that the REPAIRED SQL was cached, NOT the initial bad SQL!
    cached, meta = get_cached_sql(
        "What is total revenue?",
        "schema_text",
        database_fingerprint="fp1",
        dialect="sqlite",
        schema_version="sem_v1",
    )
    assert normalize_sql(cached) == normalize_sql(repaired_good_sql)
    assert meta.get("origin_generation_tier") == "primary_repair"


@pytest.mark.asyncio
async def test_semantic_schema_version_change_isolates_cache():
    """Verify that changing semantic schema version invalidates and isolates cached SQL and results."""
    question = "List top customers"
    sql = "SELECT customer_id, name FROM customers ORDER BY total DESC LIMIT 5"
    results = [{"customer_id": 1, "name": "Alice"}]

    # Cache under schema version 1
    set_cached_sql(
        question=question,
        sql=sql,
        database_fingerprint="fp1",
        dialect="sqlite",
        schema_version="sem_v1",
    )
    set_cached_results(
        sql=sql,
        results=results,
        database_fingerprint="fp1",
        dialect="sqlite",
        schema_version="sem_v1",
    )

    # Hits under sem_v1
    cached_sql_v1, _ = get_cached_sql(question, database_fingerprint="fp1", dialect="sqlite", schema_version="sem_v1")
    cached_res_v1 = get_cached_results(sql, database_fingerprint="fp1", dialect="sqlite", schema_version="sem_v1")
    assert cached_sql_v1 == sql
    assert cached_res_v1 == results

    # Misses under sem_v2 (e.g. after schema migration or glossary change)
    cached_sql_v2, _ = get_cached_sql(question, database_fingerprint="fp1", dialect="sqlite", schema_version="sem_v2")
    cached_res_v2 = get_cached_results(sql, database_fingerprint="fp1", dialect="sqlite", schema_version="sem_v2")
    assert cached_sql_v2 is None
    assert cached_res_v2 is None
