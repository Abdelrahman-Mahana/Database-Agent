"""Hybrid Query Understanding (Rebuild Plan - Phase 1, Strangler Fig adapter).

This is the single entry point `AnalystAgent` should call instead of talking
to `SemanticQueryParser` directly. It implements the "adapter, not
replacement" strategy from the rebuild roadmap:

  USE_LLM_UNDERSTANDING=false (default) -> behaves EXACTLY like before:
      calls the deterministic regex parser, nothing else changes.

  USE_LLM_UNDERSTANDING=true -> tries the LLM reasoning node first; if it
      fails, errors, or comes back under-confident, transparently falls
      back to the regex parser so the agent never breaks because of this
      layer. Schema-detected entities/metrics from the regex pass are
      merged in as a safety net even on the LLM path, since that part of
      the regex parser (matching literal schema names/columns against the
      question) is cheap and reliable - no reason to lose it.

Every `QueryUnderstanding` returned here carries `.source` so eval/telemetry
can tell which path actually served a given question.
"""
from typing import Any, Dict, Optional

from loguru import logger

from app.semantic.models import QueryUnderstanding
from app.semantic.parser import SemanticQueryParser
from app.semantic.llm_understanding import LLMQueryUnderstander
from app.core.config import settings


class HybridQueryUnderstander:
    """Feature-flagged: LLM reasoning with a deterministic regex fallback."""

    def __init__(self, fast_llm=None):
        self.regex_parser = SemanticQueryParser()
        self.llm_understander = LLMQueryUnderstander(fast_llm) if fast_llm is not None else None

    async def understand(
        self,
        question: str,
        schema: Optional[Dict[str, Any]] = None,
        conversation_history: str = "",
    ) -> QueryUnderstanding:
        if not settings.use_llm_understanding or self.llm_understander is None:
            return self.regex_parser.parse(question, schema)

        llm_result = await self.llm_understander.understand(question, schema, conversation_history)
        if llm_result is None:
            fallback = self.regex_parser.parse(question, schema)
            fallback.source = "llm_fallback_regex"
            return fallback

        # Safety net: merge in any schema entities/metrics the cheap regex
        # substring match found but the LLM missed, rather than trusting the
        # LLM's schema-name recall alone.
        try:
            regex_result = self.regex_parser.parse(question, schema)
            for entity in regex_result.entities:
                if entity not in llm_result.entities:
                    llm_result.entities.append(entity)
            for metric in regex_result.metrics:
                if metric not in llm_result.metrics:
                    llm_result.metrics.append(metric)
            for dim in regex_result.dimensions:
                if dim not in llm_result.dimensions:
                    llm_result.dimensions.append(dim)
        except Exception as e:
            logger.debug("Regex safety-net merge skipped: %s", e)

        return llm_result
