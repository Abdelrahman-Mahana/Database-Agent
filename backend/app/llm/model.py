"""LLM client supporting both Ollama (local) and OpenRouter."""
import json
import logging
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

from app.core.config import settings
from app.utils.token_tracker import ContextTokenTrackerCallback

logger = logging.getLogger(__name__)

# A global dictionary to cache OpenRouter model pricing to prevent querying the API repeatedly.
_openrouter_pricing_cache: dict[str, dict[str, float]] | None = None

async def _fetch_openrouter_pricing() -> dict[str, dict[str, float]]:
    global _openrouter_pricing_cache
    if _openrouter_pricing_cache is not None:
        return _openrouter_pricing_cache
    
    pricing_map = {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get("https://openrouter.ai/api/v1/models")
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
                _openrouter_pricing_cache = pricing_map
                logger.info("Successfully fetched and cached OpenRouter model pricing.")
                return pricing_map
    except Exception as e:
        logger.warning("Failed to fetch OpenRouter model pricing from API: %s", e)
    
    return {}

# Initialize global cache
try:
    if settings.redis_url:
        import redis
        from langchain_community.cache import RedisCache
        redis_client = redis.from_url(settings.redis_url)
        set_llm_cache(RedisCache(redis_client))
        logger.info("LangChain RedisCache initialized successfully.")
    else:
        set_llm_cache(InMemoryCache())
        logger.info("LangChain InMemoryCache initialized (no Redis URL).")
except Exception as e:
    try:
        set_llm_cache(InMemoryCache())
    except Exception:
        pass
    logger.warning("Failed to initialize RedisCache, falling back to InMemoryCache: %s", e)


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
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
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
        """Check if OpenRouter is available by pinging it and measuring latency."""
        import time
        if not self.api_key:
            return False, 0.0
        try:
            start_time = time.time()
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "AI Database Analyst Agent",
            }
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            }
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=5.0
            )
            response.raise_for_status()
            latency = (time.time() - start_time) * 1000
            return True, latency
        except Exception:
            return False, 0.0

    async def get_pricing(self) -> dict[str, float]:
        """Get model pricing per 1M tokens."""
        if "free" in self.model:
            return {"prompt": 0.0, "completion": 0.0}
        
        api_pricing = await _fetch_openrouter_pricing()
        if self.model in api_pricing:
            return api_pricing[self.model]
        
        # Fallbacks for popular models (per 1M tokens)
        fallbacks = {
            "google/gemini-2.5-flash": {"prompt": 0.075, "completion": 0.30},
            "google/gemini-2.5-pro": {"prompt": 1.25, "completion": 5.00},
            "anthropic/claude-3.5-sonnet": {"prompt": 3.00, "completion": 15.00},
            "meta-llama/llama-3.3-70b-instruct": {"prompt": 0.60, "completion": 0.60},
            "deepseek/deepseek-chat": {"prompt": 0.14, "completion": 0.28},
        }
        return fallbacks.get(self.model, {"prompt": 0.0, "completion": 0.0})


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
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
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
        """Check if Groq is available by pinging it and measuring latency."""
        import time
        if not self.api_key:
            return False, 0.0
        try:
            start_time = time.time()
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            }
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=5.0
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
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
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
        """Check if OpenAI is available by pinging it and measuring latency."""
        import time
        if not self.api_key:
            return False, 0.0
        try:
            start_time = time.time()
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            }
            response = await self.client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=5.0
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


def get_langchain_llm(tier: str = "primary", temperature: float = 0.1):
    """Factory function to get a LangChain LLM instance (ChatOpenAI or ChatOllama)."""
    cb = ContextTokenTrackerCallback()
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

