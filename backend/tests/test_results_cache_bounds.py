import pytest
from unittest.mock import patch
from app.utils.cache import (
    get_cached_results,
    set_cached_results,
    clear_all_caches,
    is_volatile_query,
)
from app.config.settings import settings


@pytest.fixture(autouse=True)
def clear_caches_before_test():
    clear_all_caches()
    yield
    clear_all_caches()


def test_results_cache_small_result_set_stored_and_retrieved():
    """Verify standard bounded query results are cached and retrieved."""
    sql = "SELECT id, name FROM customers WHERE country = 'USA';"
    sample_rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]

    set_cached_results(sql, sample_rows, database_fingerprint="fp_1", dialect="sqlite")
    cached = get_cached_results(sql, database_fingerprint="fp_1", dialect="sqlite")

    assert cached == sample_rows


def test_results_cache_bypasses_large_row_counts():
    """Verify result sets exceeding cache_results_max_rows (500) bypass the cache."""
    sql = "SELECT * FROM large_table;"
    # 501 rows (> 500 limit)
    large_rows = [{"id": i, "val": f"item_{i}"} for i in range(501)]

    set_cached_results(sql, large_rows, database_fingerprint="fp_1", dialect="sqlite")
    cached = get_cached_results(sql, database_fingerprint="fp_1", dialect="sqlite")

    assert cached is None, "Results with > 500 rows should not be cached!"


def test_results_cache_bypasses_large_payload_bytes():
    """Verify payload exceeding cache_results_max_bytes (512 KB) bypasses the cache."""
    sql = "SELECT * FROM heavy_blobs;"
    # 5 rows with 150 KB string each (> 750 KB total > 512 KB limit)
    heavy_rows = [{"id": i, "data": "X" * 150_000} for i in range(5)]

    set_cached_results(sql, heavy_rows, database_fingerprint="fp_1", dialect="sqlite")
    cached = get_cached_results(sql, database_fingerprint="fp_1", dialect="sqlite")

    assert cached is None, "Payload exceeding 512 KB should not be cached!"


def test_is_volatile_query_detection():
    """Verify is_volatile_query detects non-deterministic functions and volatile table patterns."""
    assert is_volatile_query("SELECT NOW();") is True
    assert is_volatile_query("SELECT * FROM audit_logs WHERE id = 1;") is True
    assert is_volatile_query("SELECT * FROM transactions WHERE amount > 100;") is True
    assert is_volatile_query("SELECT RANDOM() * 100;") is True

    # Standard static query
    assert is_volatile_query("SELECT id, name FROM dim_customer WHERE region = 'EMEA';") is False


def test_results_cache_data_freshness_isolation():
    """Verify that different data_version tags isolate cache entries on mutable datasets."""
    sql = "SELECT COUNT(*) FROM inventory;"
    old_data = [{"count": 100}]
    new_data = [{"count": 150}]

    set_cached_results(sql, old_data, database_fingerprint="fp_1", dialect="sqlite", data_version="v1")
    set_cached_results(sql, new_data, database_fingerprint="fp_1", dialect="sqlite", data_version="v2")

    cached_v1 = get_cached_results(sql, database_fingerprint="fp_1", dialect="sqlite", data_version="v1")
    cached_v2 = get_cached_results(sql, database_fingerprint="fp_1", dialect="sqlite", data_version="v2")

    assert cached_v1 == old_data
    assert cached_v2 == new_data


def test_results_cache_disabled_flag():
    """Verify setting enable_results_cache=False disables caching."""
    with patch.object(settings, "enable_results_cache", False):
        sql = "SELECT 1;"
        rows = [{"val": 1}]

        set_cached_results(sql, rows, database_fingerprint="fp_1", dialect="sqlite")
        cached = get_cached_results(sql, database_fingerprint="fp_1", dialect="sqlite")

        assert cached is None
