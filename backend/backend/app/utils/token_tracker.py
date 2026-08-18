import logging
import time
from contextvars import ContextVar
from typing import Any, Dict, List

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)

token_usage_var: ContextVar[dict[str, int]] = ContextVar(
    "token_usage", default={"prompt_tokens": 0, "completion_tokens": 0}
)
llm_trace_var: ContextVar[List[Dict[str, Any]]] = ContextVar(
    "llm_trace", default=[]
)


class ContextTokenTrackerCallback(AsyncCallbackHandler):
    """LangChain callback to track tokens and detailed invocation traces across a single request."""

    def __init__(self, stage: str = "general", component: str = "LLM", purpose: str = "generation", tier: str = "primary"):
        super().__init__()
        self.stage = stage
        self.component = component
        self.purpose = purpose
        self.tier = tier
        self._start_times: Dict[Any, float] = {}

    async def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        run_id = kwargs.get("run_id")
        if run_id:
            self._start_times[run_id] = time.perf_counter()

    async def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        run_id = kwargs.get("run_id")
        start_time = self._start_times.pop(run_id, None)
        latency_ms = (time.perf_counter() - start_time) * 1000 if start_time else 0.0

        usage = token_usage_var.get()
        p_tokens = 0
        c_tokens = 0
        model_name = "unknown"

        try:
            if response.llm_output:
                tokens = response.llm_output.get("token_usage", {})
                p_tokens = tokens.get("prompt_tokens", 0) or 0
                c_tokens = tokens.get("completion_tokens", 0) or 0
                model_name = response.llm_output.get("model_name", model_name)

            output_text = ""
            if response.generations:
                for gen_list in response.generations:
                    for gen in gen_list:
                        if hasattr(gen, "text") and gen.text:
                            output_text += gen.text
                        elif hasattr(gen, "message") and hasattr(gen.message, "content"):
                            output_text += str(gen.message.content or "")
                        if hasattr(gen, "message") and hasattr(gen.message, "response_metadata"):
                            meta = gen.message.response_metadata or {}
                            tokens = meta.get("token_usage", {})
                            p = tokens.get("prompt_tokens") or meta.get("prompt_eval_count") or meta.get("prompt_token_count") or 0
                            c = tokens.get("completion_tokens") or meta.get("eval_count") or meta.get("candidates_token_count") or 0
                            if p or c:
                                p_tokens = max(p_tokens, int(p))
                                c_tokens = max(c_tokens, int(c))
                            if "model" in meta:
                                model_name = meta["model"]

            usage["prompt_tokens"] += p_tokens
            usage["completion_tokens"] += c_tokens
        except Exception as e:
            logger.debug(f"Failed to track tokens: {e}")

        # Compute prompt/completion char counts
        prompt_chars = 0
        if response.llm_output and "prompts" in response.llm_output:
            prompt_chars = sum(len(p) for p in response.llm_output["prompts"])
        elif response.generations and hasattr(response, "run_id"):
            prompt_chars = len(output_text) * 2  # rough fallback

        output_chars = len(output_text)

        trace_entry = {
            "stage": self.stage,
            "component": self.component,
            "purpose": self.purpose,
            "tier": self.tier,
            "model": model_name,
            "prompt_chars": prompt_chars,
            "estimated_input_tokens": p_tokens or (prompt_chars // 4 if prompt_chars else 0),
            "output_chars": output_chars,
            "estimated_output_tokens": c_tokens or (output_chars // 4 if output_chars else 0),
            "latency_ms": round(latency_ms, 2),
            "success": True,
            "cache_hit": False,
        }
        record_llm_trace(trace_entry)


def get_current_token_usage() -> dict[str, int]:
    return token_usage_var.get()


def reset_token_usage() -> None:
    token_usage_var.set({"prompt_tokens": 0, "completion_tokens": 0})


def record_llm_trace(entry: Dict[str, Any]) -> None:
    current = list(llm_trace_var.get())
    current.append(entry)
    llm_trace_var.set(current)


def get_llm_trace() -> List[Dict[str, Any]]:
    return list(llm_trace_var.get())


def reset_llm_trace() -> None:
    llm_trace_var.set([])
