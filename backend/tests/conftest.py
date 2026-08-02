import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi.testclient import TestClient

# Add backend directory to sys.path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.main import app
from app.database.db import SessionLocal


@pytest.fixture(scope="session")
def db_session():
    """Provides a database session for integration tests."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session")
def api_client():
    """Provides a FastAPI test client."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_llm_chain(monkeypatch):
    """Mocks LLM calls to prevent network requests during tests."""
    mock_ainvoke = AsyncMock()

    class MockResponse:
        def __init__(self, text="SELECT * FROM Artist LIMIT 5;"):
            self.content = text
            self.text = text
            self.response_metadata = {
                "token_usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5
                }
            }
        def __getitem__(self, key):
            if key == "text":
                return self.text
            raise KeyError(key)
        def get(self, key, default=None):
            if key == "text":
                return self.text
            if key == "response_metadata":
                return self.response_metadata
            return default

    # Default mock behavior
    default_response = MockResponse()
    mock_ainvoke.return_value = default_response

    # Helper wrapper that handles mock outputs of different types (dict, string, or mock response)
    async def wrapper(*args, **kwargs):
        val = mock_ainvoke.return_value
        if isinstance(val, dict):
            return MockResponse(text=val.get("text", ""))
        elif isinstance(val, str):
            return MockResponse(text=val)
        return val

    # Monkeypatch modern RunnableSequence, BaseChatModel, and legacy LLMChain
    try:
        from langchain_core.runnables import RunnableSequence
        monkeypatch.setattr(RunnableSequence, "ainvoke", wrapper)
    except Exception:
        pass

    try:
        from langchain_core.language_models.chat_models import BaseChatModel
        monkeypatch.setattr(BaseChatModel, "ainvoke", wrapper)
    except Exception:
        pass

    try:
        from langchain.chains import LLMChain  # noqa: F401 - still available in langchain>=0.2
        monkeypatch.setattr(LLMChain, "ainvoke", wrapper)
    except ImportError:
        pass
    except Exception:
        pass

    return mock_ainvoke
