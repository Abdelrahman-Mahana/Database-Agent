import pytest
from app.core.config import settings
from app.llm.model import (
    get_llm_client,
    get_langchain_llm,
    OpenAIClient,
    GroqClient,
    OpenRouterClient,
    OllamaClient,
)


def test_llm_client_provider_switching(monkeypatch):
    """Test switching LLM providers between OpenAI, Groq, OpenRouter, and Ollama."""
    # Test OpenAI provider
    monkeypatch.setattr(settings, "llm_provider", "openai")
    client = get_llm_client()
    assert isinstance(client, OpenAIClient)
    assert client.provider == "openai"

    # Test Groq provider
    monkeypatch.setattr(settings, "llm_provider", "groq")
    client = get_llm_client()
    assert isinstance(client, GroqClient)
    assert client.provider == "groq"

    # Test OpenRouter provider
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    client = get_llm_client()
    assert isinstance(client, OpenRouterClient)
    assert client.provider == "openrouter"

    # Test fallback/Ollama provider
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    client = get_llm_client()
    assert isinstance(client, OllamaClient)
    assert client.provider == "ollama"


def test_langchain_llm_provider_switching(monkeypatch):
    """Test getting LangChain LLM instances for OpenAI, Groq, and OpenRouter."""
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test-openai-key")
    monkeypatch.setattr(settings, "openai_model", "gpt-4o")
    llm = get_langchain_llm("primary")
    assert llm.model_name == "gpt-4o"

    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "test-groq-key")
    monkeypatch.setattr(settings, "groq_model", "llama-3.3-70b-versatile")
    llm = get_langchain_llm("primary")
    assert llm.model_name == "llama-3.3-70b-versatile"

    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", "test-openrouter-key")
    monkeypatch.setattr(settings, "openrouter_model", "google/gemini-2.5-flash")
    llm = get_langchain_llm("primary")
    assert llm.model_name == "google/gemini-2.5-flash"

    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_model", "gemma3:4b")
    monkeypatch.setattr(settings, "ollama_fast_model", "gemma3:2b")
    llm_primary = get_langchain_llm("primary")
    assert getattr(llm_primary, "model", getattr(llm_primary, "model_name", None)) == "gemma3:4b"
    llm_fast = get_langchain_llm("fast")
    assert getattr(llm_fast, "model", getattr(llm_fast, "model_name", None)) == "gemma3:2b"
