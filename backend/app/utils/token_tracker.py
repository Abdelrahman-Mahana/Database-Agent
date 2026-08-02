import logging
from contextvars import ContextVar
from typing import Any

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)

token_usage_var: ContextVar[dict[str, int]] = ContextVar(
    "token_usage", default={"prompt_tokens": 0, "completion_tokens": 0}
)

class ContextTokenTrackerCallback(AsyncCallbackHandler):
    """LangChain callback to track tokens across a single request using ContextVars."""
    
    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        usage = token_usage_var.get()
        try:
            # 1. Try standard LLM output format
            if response.llm_output and "token_usage" in response.llm_output:
                tokens = response.llm_output["token_usage"]
                usage["prompt_tokens"] += tokens.get("prompt_tokens", 0)
                usage["completion_tokens"] += tokens.get("completion_tokens", 0)
                return

            # 2. Try looking into message response_metadata (often used by Chat models, Ollama, Gemini)
            if response.generations:
                for gen_list in response.generations:
                    for gen in gen_list:
                        if hasattr(gen, "message") and hasattr(gen.message, "response_metadata"):
                            meta = gen.message.response_metadata or {}
                            tokens = meta.get("token_usage", {})
                            p = tokens.get("prompt_tokens") or meta.get("prompt_eval_count") or meta.get("prompt_token_count") or 0
                            c = tokens.get("completion_tokens") or meta.get("eval_count") or meta.get("candidates_token_count") or 0
                            if p or c:
                                usage["prompt_tokens"] += int(p)
                                usage["completion_tokens"] += int(c)
                                return
        except Exception as e:
            logger.debug(f"Failed to track tokens: {e}")

def get_current_token_usage() -> dict[str, int]:
    return token_usage_var.get()

def reset_token_usage() -> None:
    token_usage_var.set({"prompt_tokens": 0, "completion_tokens": 0})
