import pytest


def test_api_health_endpoint(api_client):
    """Test health check API endpoint contract."""
    response = api_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "llm_available" in data
    assert "llm_provider" in data
    assert "model" in data


def test_api_schema_endpoint(api_client):
    """Test schema discovery API endpoint contract."""
    response = api_client.get("/schema")
    assert response.status_code == 200
    data = response.json()
    assert "schema" in data
    assert "schema_text" in data
    assert "database_url" in data
    assert "Artist" in data["schema"]


@pytest.mark.usefixtures("mock_llm_chain")
def test_api_chat_endpoint(api_client):
    """Test chat message query processing endpoint contract."""
    payload = {"message": "Which artists have the most albums?"}
    response = api_client.post("/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    # Verify response schema fields match ChatResponse model
    assert "question" in data
    assert "sql" in data
    assert "results" in data
    assert "report" in data
    assert "chart_suggestion" in data
    assert "success" in data
    assert "error" in data
    assert "attempted_sql" in data
    assert "error_type" in data
    assert "suggestions" in data
    
    assert data["success"] is True
    assert data["error"] is None


@pytest.mark.usefixtures("mock_llm_chain")
def test_api_chat_endpoint_with_session(api_client):
    """Test chat message query processing endpoint with session ID and clear endpoint."""
    payload = {"message": "Which artists have the most albums?", "session_id": "api_test_session"}
    response = api_client.post("/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    # Now verify clearing history works
    clear_response = api_client.delete("/chat/history?session_id=api_test_session")
    assert clear_response.status_code == 200
    assert clear_response.json() == {"status": "cleared"}
