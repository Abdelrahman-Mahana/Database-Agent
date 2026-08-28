"""Hybrid Query Understanding adapter wrapping canonical QuerySpecBuilder."""
import re
from typing import Any, Dict, Optional
from app.agent.semantic.models import QueryUnderstanding
from app.agent.semantic.query_spec_builder import QuerySpecBuilder
from app.agent.semantic.llm_understanding import LLMQueryUnderstander


class _SchemaContextAdapter:
    """Lightweight adapter turning a schema dict into a db_ctx duck-type for QuerySpecBuilder."""

    def __init__(self, schema: Dict[str, Any]):
        self.schema = schema
        self.table_names_set = set(schema.keys())
        self.keyword_to_tables: Dict[str, set[str]] = {}
        for t, info in schema.items():
            t_low = t.lower()
            self.keyword_to_tables.setdefault(t_low, set()).add(t)
            for c in info.get("columns", []):
                self.keyword_to_tables.setdefault(c["name"].lower(), set()).add(t)

    def match_seed_tables_fast(self, text: str, max_tables: int = 15) -> set:
        tokens = set(re.findall(r'[a-zA-Z0-9_\u0621-\u064A]+', text.lower()))
        matched = set()
        for tok in tokens:
            if tok in self.keyword_to_tables:
                matched.update(self.keyword_to_tables[tok])
        return matched


class HybridQueryUnderstander:
    """Adapter wrapping canonical QuerySpecBuilder for backward-compatibility."""

    def __init__(self, fast_llm=None):
        self.builder = QuerySpecBuilder(fast_llm=fast_llm)
        self.llm_understander = LLMQueryUnderstander(fast_llm) if fast_llm is not None else None

    async def understand(
        self,
        question: str,
        schema: Optional[Dict[str, Any]] = None,
        conversation_history: str = "",
        catalog=None,
    ) -> QueryUnderstanding:
        """Delegate to canonical QuerySpecBuilder."""
        ctx = _SchemaContextAdapter(schema) if schema is not None else None
        spec = await self.builder.build_spec_async(
            question=question,
            db_ctx=ctx,
            conversation_history=conversation_history,
            catalog=catalog,
        )
        if spec.source == "unified_query_spec_builder":
            spec.source = "heuristic_fast_path"
        elif spec.source == "llm_query_spec_builder":
            spec.source = "llm_fast_path"
        return spec
