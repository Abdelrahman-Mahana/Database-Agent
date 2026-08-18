import asyncio
import json
import logging
import random
from typing import AsyncGenerator

import httpx
try:
    from langchain.globals import set_llm_cache
except ImportError:
    from langchain_core.globals import set_llm_cache
try:
    from langchain_community.cache import InMemoryCache
except ImportError:
    from langchain_core.caches import InMemoryCache

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    try:
        from langchain_community.chat_models import ChatOpenAI
    except ImportError:
        ChatOpenAI = None

try:
    from langchain_ollama import ChatOllama
except ImportError:
    try:
        from langchain_community.chat_models import ChatOllama
    except ImportError:
        ChatOllama = None

from app.config.settings import settings
from app.utils.token_tracker import ContextTokenTrackerCallback

logger = logging.getLogger(__name__)

# Static fallback prices in USD per 1M tokens.  Runtime workflows must always
# be able to price a request without depending on OpenRouter's model catalog.
_OPENROUTER_STATIC_PRICING: dict[str, dict[str, float]] = {
    "google/gemini-2.5-flash": {"prompt": 0.075, "completion": 0.30},
    "google/gemini-2.5-pro": {"prompt": 1.25, "completion": 5.00},
    "anthropic/claude-3.5-sonnet": {"prompt": 3.00, "completion": 15.00},
    "meta-llama/llama-3.3-70b-instruct": {"prompt": 0.60, "completion": 0.60},
    "deepseek/deepseek-chat": {"prompt": 0.14, "completion": 0.28},
}
_OPENROUTER_UNKNOWN_PRICE = {"prompt": 0.0, "completion": 0.0}
_openrouter_pricing_cache: dict[str, dict[str, float]] = dict(_OPENROUTER_STATIC_PRICING)


async def refresh_openrouter_pricing() -> bool:
    """Refresh the process cache outside request workflows.

    Failure intentionally leaves the static/previous cache intact so cost
    tracking stays local and deterministic during an OpenRouter outage.
    """
    global _openrouter_pricing_cache
    pricing_map: dict[str, dict[str, float]] = {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.openrouter_base_url.rstrip('/')}/models")
            if response.status_code == 200:
                data = response.json()
                for model_data in data.get("data", []):
                    model_id = model_data.get("id")
                    pricing = model_data.get("pricing", {})
                    # Convert pricing (USD per single token) to USD per 1M tokens
                    prompt_rate = float(pricing.get("prompt", 0)) * 1_000_000
                    completion_rate = float(pricing.get("completion", 0)) * 1_000_000
                    pricing_map[model_id] = {
                        "prompt": prompt_rate,
                        "completion": completion_rate
                    }
                if pricing_map:
                    # Keep static known-model prices as a fallback for an
                    # incomplete catalog response.
                    _openrouter_pricing_cache = {**_OPENROUTER_STATIC_PRICING, **pricing_map}
                    logger.info("Refreshed OpenRouter pricing cache with %d models.", len(pricing_map))
                    return True
    except Exception as e:
        logger.warning("Failed to fetch OpenRouter model pricing from API: %s", e)
    return False


async def run_openrouter_pricing_refresh() -> None:
    """Refresh pricing at startup and periodically; never runs in request paths."""
    interval = max(60, settings.openrouter_pricing_refresh_seconds)
    while True:
        await refresh_openrouter_pricing()
        await asyncio.sleep(interval)

# Initialize global cache
try:
    set_llm_cache(InMemoryCache())
    logger.info("LangChain InMemoryCache initialized.")
except Exception as e:
    logger.warning("Failed to initialize InMemoryCache: %s", e)


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    json_payload: dict,
    max_retries: int = 4,
    initial_delay: float = 2.0,
) -> httpx.Response:
    """Execute HTTP POST with exponential backoff on 429 Rate Limits and transient errors."""
    for attempt in range(max_retries + 1):
        try:
            response = await client.post(url, headers=headers, json=json_payload)
            if response.status_code == 429:
                if attempt < max_retries:
                    retry_after = response.headers.get("retry-after")
                    if retry_after:
                        try:
                            delay = max(float(retry_after), 1.0) + random.uniform(0.5, 1.5)
                        except ValueError:
                            delay = (initial_delay * (2 ** attempt)) + random.uniform(0.5, 1.5)
                    else:
                        delay = (initial_delay * (2 ** attempt)) + random.uniform(0.5, 1.5)
                    logger.warning(
                        "Rate limit 429 encountered from LLM API. Retrying in %.1fs (attempt %d/%d)...",
                        delay, attempt + 1, max_retries
                    )
                    await asyncio.sleep(delay)
                    continue
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < max_retries:
                retry_after = e.response.headers.get("retry-after")
                try:
                    delay = max(float(retry_after), 1.0) + random.uniform(0.5, 1.5) if retry_after else ((initial_delay * (2 ** attempt)) + random.uniform(0.5, 1.5))
                except ValueError:
                    delay = (initial_delay * (2 ** attempt)) + random.uniform(0.5, 1.5)
                logger.warning(
                    "Rate limit 429 encountered from LLM API. Retrying in %.1fs (attempt %d/%d)...",
                    delay, attempt + 1, max_retries
                )
                await asyncio.sleep(delay)
                continue
            raise
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            if attempt < max_retries:
                delay = (1.5 * (2 ** attempt)) + random.uniform(0.2, 0.8)
                logger.warning("Network error connecting to LLM API (%s). Retrying in %.1fs...", e, delay)
                await asyncio.sleep(delay)
                continue
            raise
    raise RuntimeError("Exceeded maximum retries for LLM API request.")


SYSTEM_PROMPT = """You are an expert database analyst and SQL writer.
Your task is to generate accurate, read-only SQL queries based on the provided database schema.
Only generate SELECT statements. Never generate DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE, or CREATE statements."""


class OllamaClient:
    """Client for Ollama local LLM API."""

    def __init__(self, base_url: str = None, model: str = None):
        self.provider = "ollama"
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.client = httpx.AsyncClient(timeout=120.0)

    async def generate(self, prompt: str, system: str = SYSTEM_PROMPT, temperature: float = 0.1) -> str:
        """Generate a response from the LLM."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 2048,
            },
        }
        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "").strip()
        except httpx.HTTPError as e:
            raise RuntimeError(f"Ollama API error: {e}") from e

    async def generate_stream(self, prompt: str, system: str = SYSTEM_PROMPT, temperature: float = 0.1) -> AsyncGenerator[str, None]:
        """Stream a response from the LLM."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": 2048,
            },
        }
        async with self.client.stream("POST", f"{self.base_url}/api/generate", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip():
                    try:
                        data = json.loads(line)
                        if "response" in data:
                            yield data["response"]
                    except json.JSONDecodeError:
                        continue

    async def health_check(self) -> tuple[bool, float]:
        """Check if Ollama is available and measure latency."""
        import time
        try:
            start_time = time.time()
            response = await self.client.get(f"{self.base_url}/api/tags", timeout=5.0)
            response.raise_for_status()
            latency = (time.time() - start_time) * 1000
            return True, latency
        except Exception:
            return False, 0.0

    async def get_pricing(self) -> dict[str, float]:
        """Ollama runs locally, so it is free."""
        return {"prompt": 0.0, "completion": 0.0}


class OpenRouterClient:
    """Client for OpenRouter LLM API."""

    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        base_url: str = None,
    ):
        self.provider = "openrouter"
        self.api_key = api_key or settings.openrouter_api_key
        self.model = model or settings.openrouter_model
        self.base_url = (base_url or settings.openrouter_base_url).rstrip("/")
        self.client = httpx.AsyncClient(timeout=120.0)

    async def generate(self, prompt: str, system: str = SYSTEM_PROMPT, temperature: float = 0.1) -> str:
        """Generate a response from the LLM via OpenRouter."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "AI Database Analyst Agent",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
        }
        try:
            response = await _post_with_retry(
                self.client,
                f"{self.base_url}/chat/completions",
                headers=headers,
                json_payload=payload,
            )
            data = response.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
            return ""
        except httpx.HTTPError as e:
            raise RuntimeError(f"OpenRouter API error: {e}") from e

    async def generate_stream(self, prompt: str, system: str = SYSTEM_PROMPT, temperature: float = 0.1) -> AsyncGenerator[str, None]:
        """Stream a response from the LLM via OpenRouter."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "AI Database Analyst Agent",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "stream": True,
        }
        async with self.client.stream("POST", f"{self.base_url}/chat/completions", headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                    except json.JSONDecodeError:
                        continue

    async def health_check(self) -> tuple[bool, float]:
        """Check OpenRouter connectivity without a billable generation call."""
        import time
        if not self.api_key:
            return False, 0.0
        try:
            start_time = time.time()
            response = await self.client.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=5.0,
            )
            response.raise_for_status()
            latency = (time.time() - start_time) * 1000
            return True, latency
        except Exception:
            return False, 0.0

    async def get_pricing(self) -> dict[str, float]:
        """Return cached/static pricing only; this method never performs I/O."""
        if "free" in self.model:
            return {"prompt": 0.0, "completion": 0.0}
        return dict(_openrouter_pricing_cache.get(self.model, _OPENROUTER_UNKNOWN_PRICE))


class GroqClient:
    """Client for Groq LLM API."""

    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        base_url: str = None,
    ):
        self.provider = "groq"
        self.api_key = api_key or settings.groq_api_key
        self.model = model or settings.groq_model
        self.base_url = (base_url or settings.groq_base_url).rstrip("/")
        self.client = httpx.AsyncClient(timeout=120.0)

    async def generate(self, prompt: str, system: str = SYSTEM_PROMPT, temperature: float = 0.1) -> str:
        """Generate a response from the LLM via Groq."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
        }
        try:
            response = await _post_with_retry(
                self.client,
                f"{self.base_url}/chat/completions",
                headers=headers,
                json_payload=payload,
            )
            data = response.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
            return ""
        except httpx.HTTPError as e:
            raise RuntimeError(f"Groq API error: {e}") from e

    async def generate_stream(self, prompt: str, system: str = SYSTEM_PROMPT, temperature: float = 0.1) -> AsyncGenerator[str, None]:
        """Stream a response from the LLM via Groq."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "stream": True,
        }
        async with self.client.stream("POST", f"{self.base_url}/chat/completions", headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                    except json.JSONDecodeError:
                        continue

    async def health_check(self) -> tuple[bool, float]:
        """Check Groq connectivity without a billable generation call."""
        import time
        if not self.api_key:
            return False, 0.0
        try:
            start_time = time.time()
            response = await self.client.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=5.0,
            )
            response.raise_for_status()
            latency = (time.time() - start_time) * 1000
            return True, latency
        except Exception:
            return False, 0.0

    async def get_pricing(self) -> dict[str, float]:
        """Get model pricing per 1M tokens for Groq models."""
        fallbacks = {
            "llama-3.3-70b-versatile": {"prompt": 0.59, "completion": 0.79},
            "llama-3.1-8b-instant": {"prompt": 0.05, "completion": 0.08},
            "llama3-70b-8192": {"prompt": 0.59, "completion": 0.79},
            "llama3-8b-8192": {"prompt": 0.05, "completion": 0.08},
            "mixtral-8x7b-32768": {"prompt": 0.24, "completion": 0.24},
            "gemma2-9b-it": {"prompt": 0.20, "completion": 0.20},
            "deepseek-r1-distill-llama-70b": {"prompt": 0.75, "completion": 0.99},
        }
        return fallbacks.get(self.model, {"prompt": 0.10, "completion": 0.10})


class OpenAIClient:
    """Client for OpenAI LLM API."""

    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        base_url: str = None,
    ):
        self.provider = "openai"
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model
        self.base_url = (base_url or settings.openai_base_url).rstrip("/")
        self.client = httpx.AsyncClient(timeout=120.0)

    async def generate(self, prompt: str, system: str = SYSTEM_PROMPT, temperature: float = 0.1) -> str:
        """Generate a response from the LLM via OpenAI."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
        }
        try:
            response = await _post_with_retry(
                self.client,
                f"{self.base_url}/chat/completions",
                headers=headers,
                json_payload=payload,
            )
            data = response.json()
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
            return ""
        except httpx.HTTPError as e:
            raise RuntimeError(f"OpenAI API error: {e}") from e

    async def generate_stream(self, prompt: str, system: str = SYSTEM_PROMPT, temperature: float = 0.1) -> AsyncGenerator[str, None]:
        """Stream a response from the LLM via OpenAI."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "stream": True,
        }
        async with self.client.stream("POST", f"{self.base_url}/chat/completions", headers=headers, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            if "content" in delta:
                                yield delta["content"]
                    except json.JSONDecodeError:
                        continue

    async def health_check(self) -> tuple[bool, float]:
        """Check OpenAI connectivity without a billable generation call."""
        import time
        if not self.api_key:
            return False, 0.0
        try:
            start_time = time.time()
            response = await self.client.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=5.0,
            )
            response.raise_for_status()
            latency = (time.time() - start_time) * 1000
            return True, latency
        except Exception:
            return False, 0.0

    async def get_pricing(self) -> dict[str, float]:
        """Get model pricing per 1M tokens for OpenAI models."""
        fallbacks = {
            "gpt-4o": {"prompt": 2.50, "completion": 10.00},
            "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
            "o1": {"prompt": 15.00, "completion": 60.00},
            "o1-mini": {"prompt": 1.10, "completion": 4.40},
            "o3-mini": {"prompt": 1.10, "completion": 4.40},
            "gpt-4-turbo": {"prompt": 10.00, "completion": 30.00},
            "gpt-3.5-turbo": {"prompt": 0.50, "completion": 1.50},
        }
        return fallbacks.get(self.model, {"prompt": 1.00, "completion": 3.00})


def get_llm_client():
    """Factory function to get the appropriate LLM client."""
    provider = settings.llm_provider
    if provider == "openai":
        return OpenAIClient()
    elif provider == "groq":
        return GroqClient()
    elif provider == "openrouter":
        return OpenRouterClient()
    return OllamaClient()


def get_langchain_llm(
    tier: str = "primary",
    temperature: float = 0.1,
    stage: str = "general",
    component: str = "LLM",
    purpose: str = "generation",
):
    """Factory function to get a LangChain LLM instance (ChatOpenAI or ChatOllama)."""
    cb = ContextTokenTrackerCallback(stage=stage, component=component, purpose=purpose, tier=tier)
    provider = settings.llm_provider
    if provider == "openai":
        model_name = (
            settings.openai_model
            if tier == "primary"
            else settings.openai_fast_model
        )
        return ChatOpenAI(
            model_name=model_name,
            openai_api_key=settings.openai_api_key,
            openai_api_base=settings.openai_base_url,
            temperature=temperature,
            callbacks=[cb],
            max_retries=3,
            request_timeout=60.0,
        )
    elif provider == "groq":
        model_name = (
            settings.groq_model
            if tier == "primary"
            else settings.groq_fast_model
        )
        return ChatOpenAI(
            model_name=model_name,
            openai_api_key=settings.groq_api_key,
            openai_api_base=settings.groq_base_url,
            temperature=temperature,
            callbacks=[cb],
            max_retries=3,
            request_timeout=60.0,
        )
    elif provider == "openrouter":
        model_name = (
            settings.openrouter_model
            if tier == "primary"
            else settings.openrouter_fast_model
        )
        return ChatOpenAI(
            model_name=model_name,
            openai_api_key=settings.openrouter_api_key,
            openai_api_base=settings.openrouter_base_url,
            temperature=temperature,
            callbacks=[cb],
            max_retries=3,
            request_timeout=60.0,
            model_kwargs={
                "extra_headers": {
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "AI Database Analyst Agent",
                }
            }
        )
    else:
        # Default/fallback to Ollama
        if ChatOllama is None:
            raise RuntimeError("ChatOllama is not installed or unavailable in this environment.")
        model_name = (
            settings.ollama_model
            if tier == "primary"
            else settings.ollama_fast_model
        )
        return ChatOllama(
            base_url=settings.ollama_base_url,
            model=model_name,
            temperature=temperature,
            callbacks=[cb],
        )

