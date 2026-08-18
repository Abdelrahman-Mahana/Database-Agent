import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config.settings import settings

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
