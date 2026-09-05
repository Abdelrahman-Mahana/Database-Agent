import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from app.core.exceptions.handlers import setup_exception_handlers

def test_global_exception_handler():
    app = FastAPI()
    setup_exception_handlers(app)
    
    @app.get("/error")
    def error_route():
        raise ValueError("Simulated failure")
        
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/error")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
