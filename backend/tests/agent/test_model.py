import pytest
import httpx
from app.agent.llm.model import (
    OllamaClient,
    OpenAIClient,
    OpenRouterClient,
    GroqClient,
    get_llm_client,
    get_langchain_llm
)
from app.core.config.settings import settings

class MockResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code
        self.headers = {}
        
    def json(self):
        return self._json_data
        
    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("Error", request=None, response=self)

@pytest.mark.asyncio
async def test_ollama_client_generate(monkeypatch):
    """Test Ollama client text generation."""
    async def mock_post(*args, **kwargs):
        return MockResponse({"response": "Hello from Ollama"})
        
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    
    client = OllamaClient()
    response = await client.generate("Say hello")
    assert response == "Hello from Ollama"

@pytest.mark.asyncio
async def test_openai_client_generate(monkeypatch):
    """Test OpenAI client text generation."""
    async def mock_post(*args, **kwargs):
        return MockResponse({"choices": [{"message": {"content": "Hello from OpenAI"}}]})
        
    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    
    client = OpenAIClient(api_key="test_key")
    response = await client.generate("Say hello")
    assert response == "Hello from OpenAI"

def test_get_llm_client(monkeypatch):
    """Test the factory for LLM clients."""
    monkeypatch.setattr(settings, "llm_provider", "openai")
    assert isinstance(get_llm_client(), OpenAIClient)
    
    monkeypatch.setattr(settings, "llm_provider", "groq")
    assert isinstance(get_llm_client(), GroqClient)
    
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    assert isinstance(get_llm_client(), OpenRouterClient)
    
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    assert isinstance(get_llm_client(), OllamaClient)
