"""Tests for Production Architecture Hardening (Global State, Secret Key, Caches, Lifecycle)."""
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

from app.core.config.settings import Settings, settings
from app.services.database.db import (
    EngineCache,
    TTLCache,
    reset_database_layer,
    _engine_manager,
    _session_url_cache,
)
from app.utils.cache import clear_all_caches, _sql_cache, _results_cache, _chart_cache


def test_production_mode_strictly_rejects_default_secret_key():
    """Verify that production environment refuses to boot with the default insecure secret key."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            environment="production",
            secret_key="database-analyst-agent-default-secure-key-2026",
        )
    assert "CRITICAL SECURITY CONFIGURATION" in str(exc_info.value)
    assert "Default or empty secret keys are strictly prohibited" in str(exc_info.value)


def test_production_mode_strictly_rejects_empty_or_short_secret_key():
    """Verify that production environment refuses empty keys or keys shorter than 32 characters."""
    # 1. Empty key
    with pytest.raises(ValidationError) as exc_info1:
        Settings(environment="production", secret_key="")
    assert "CRITICAL SECURITY CONFIGURATION" in str(exc_info1.value)

    # 2. Short key (< 32 chars)
    with pytest.raises(ValidationError) as exc_info2:
        Settings(environment="production", secret_key="insecure_short_key_12345")
    assert "must be at least 32 characters long" in str(exc_info2.value)


def test_production_mode_accepts_strong_secret_key():
    """Verify that production mode boots successfully with a strong 32+ char key."""
    strong_key = "a_very_secure_production_secret_key_exceeding_32_characters_2026"
    prod_settings = Settings(
        environment="production",
        secret_key=strong_key,
        database_url="sqlite:///prod.db",
    )
    assert prod_settings.environment == "production"
    assert prod_settings.secret_key == strong_key


def test_development_mode_allows_default_key_for_local_dx():
    """Verify that development/test environments permit default key for frictionless local dev."""
    dev_settings = Settings(
        environment="development",
        database_url="sqlite:///dev.db",
    )
    assert dev_settings.environment == "development"
    assert dev_settings.secret_key == "database-analyst-agent-default-secure-key-2026"


def test_database_engine_cache_lifecycle_and_eviction(tmp_path):
    """Verify that EngineCache properly evicts and disposes of oldest engines when capacity is exceeded."""
    cache = EngineCache(capacity=2)
    
    e1 = create_engine(f"sqlite:///{tmp_path / 'db1.db'}")
    e2 = create_engine(f"sqlite:///{tmp_path / 'db2.db'}")
    e3 = create_engine(f"sqlite:///{tmp_path / 'db3.db'}")

    cache.set("url1", e1, None)
    cache.set("url2", e2, None)
    assert cache.get_engine("url1") is not None
    assert cache.get_engine("url2") is not None

    # Adding third should evict oldest (url1)
    cache.set("url3", e3, None)
    assert cache.get_engine("url1") is None
    assert cache.get_engine("url2") is not None
    assert cache.get_engine("url3") is not None

    # Dispose all cleanly clears cache
    cache.dispose_all()
    assert len(cache.cache) == 0


def test_reset_database_layer_cleans_engines_and_session_urls():
    """Verify that reset_database_layer cleans both engine cache and session TTL cache."""
    _session_url_cache.set("sess_123", "sqlite:///test.db")
    assert _session_url_cache.get("sess_123") == "sqlite:///test.db"

    reset_database_layer()
    assert _session_url_cache.get("sess_123") is None


def test_clear_all_caches_empties_all_l1_l2_caches():
    """Verify that clear_all_caches empties all in-memory L1/L2 caches."""
    _sql_cache["test_k"] = "SELECT 1"
    _results_cache["test_k"] = [{"val": 1}]
    _chart_cache["test_k"] = {"chart": "data"}

    assert len(_sql_cache) > 0
    assert len(_results_cache) > 0
    assert len(_chart_cache) > 0

    clear_all_caches()

    assert len(_sql_cache) == 0
    assert len(_results_cache) == 0
    assert len(_chart_cache) == 0
