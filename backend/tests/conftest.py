"""Pytest configuration and deterministic test isolation fixtures."""
import copy
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.core.config.settings import settings
from app.utils.cache import clear_all_caches
from app.services.database.db import reset_database_layer


@pytest.fixture(autouse=True)
def isolate_settings():
    """
    Snapshots global settings before every test and restores them afterwards.
    Guarantees that test mutations (e.g. strict_privacy_mode, secret_key, enable_data_masking)
    never leak between test cases.
    """
    original_state = {k: copy.deepcopy(v) for k, v in settings.__dict__.items() if not k.startswith("_")}
    yield
    for k, v in original_state.items():
        setattr(settings, k, v)


@pytest.fixture(autouse=True)
def reset_test_caches():
    """
    Clears all L1/L2/L3 caches and active database connection pools
    before and after every test execution.
    """
    clear_all_caches()
    reset_database_layer()
    yield
    clear_all_caches()
    reset_database_layer()


@pytest.fixture
def client():
    """Returns a FastAPI TestClient."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def temp_db_url(tmp_path):
    """Returns a temporary SQLite database URL."""
    db_file = tmp_path / "test.db"
    return f"sqlite:///{db_file}"


@pytest.fixture
def isolated_db_engine(tmp_path):
    """Creates and yields an isolated SQLite database engine with automatic disposal."""
    db_file = tmp_path / "isolated.db"
    engine = create_engine(f"sqlite:///{db_file}", echo=False)
    yield engine
    engine.dispose()
