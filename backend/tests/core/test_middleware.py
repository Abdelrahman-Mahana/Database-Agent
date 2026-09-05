import pytest
import time
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from app.core.middleware.rate_limit import RateLimitMiddleware, consume_rate_limit_ram, clear_ram_rate_limits

@pytest.fixture(autouse=True)
def reset_rate_limits():
    clear_ram_rate_limits()
    yield
    clear_ram_rate_limits()

def test_consume_rate_limit_ram():
    client_key = "test_client"
    # Consume 2 tokens
    assert consume_rate_limit_ram(client_key, max_requests=2, window_seconds=60.0) is True
    assert consume_rate_limit_ram(client_key, max_requests=2, window_seconds=60.0) is True
    # Third should fail
    assert consume_rate_limit_ram(client_key, max_requests=2, window_seconds=60.0) is False

def test_rate_limit_middleware(monkeypatch):
    from app.core.config.settings import settings
    monkeypatch.setattr(settings, "enable_rate_limit", True)
    
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, requests_per_minute=2)
    
    @app.get("/chat/test")
    def chat_route():
        return {"status": "ok"}
        
    @app.get("/other")
    def other_route():
        return {"status": "ok"}
        
    client = TestClient(app)
    
    # Path starting with /chat should be rate limited
    assert client.get("/chat/test").status_code == 200
    assert client.get("/chat/test").status_code == 200
    assert client.get("/chat/test").status_code == 429
    
    # Other paths shouldn't be rate limited
    assert client.get("/other").status_code == 200
    assert client.get("/other").status_code == 200
    assert client.get("/other").status_code == 200
