import asyncio

from app.llm.model import OpenRouterClient


def test_openrouter_pricing_lookup_is_local(monkeypatch):
    """Pricing retrieval in a workflow must not invoke the catalog refresh."""
    client = OpenRouterClient(api_key="key", model="google/gemini-2.5-flash")

    async def fail_refresh():
        raise AssertionError("workflow pricing lookup must not use the network")

    monkeypatch.setattr("app.llm.model.refresh_openrouter_pricing", fail_refresh)
    pricing = asyncio.run(client.get_pricing())

    assert pricing == {"prompt": 0.075, "completion": 0.30}


def test_openrouter_pricing_has_static_unknown_model_fallback():
    client = OpenRouterClient(api_key="key", model="provider/unknown-model")

    assert asyncio.run(client.get_pricing()) == {"prompt": 0.0, "completion": 0.0}
