"""One-time, LLM-assisted business-glossary enrichment for a SchemaCatalog.

This is the piece that turns "the model re-guesses what every column means
on every single question" into "we asked once, wrote it down, and reuse it
for free forever (until the schema changes)".

Design constraints:
  - Runs ONLY when explicitly triggered (on first connect to a new DB, or via
    an admin/API action) — never implicitly inside the hot question-answering
    path, so it never silently adds latency/cost to a user's question.
  - A single LLM call per database (not per table) — the whole structural
    catalog is compact enough to fit in one prompt for the vast majority of
    schemas; very large schemas (100+ tables) are chunked in batches so any
    one call stays small.
  - Output is strict JSON, validated defensively — a malformed/partial
    response degrades to "no glossary for this table" rather than crashing.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from loguru import logger

from app.models.schema_catalog.models import SchemaCatalog

BATCH_SIZE = 25  # tables per LLM call, keeps prompts small on large schemas

GLOSSARY_PROMPT_TEMPLATE = """You are documenting a database for future analysts.
For each table and column below, write ONE short business-friendly description
(<= 12 words) and 0-3 common business synonyms a non-technical person might use
instead of the raw name (in the SAME language mix the names suggest — include
Arabic synonyms if the domain looks Arabic-relevant, English otherwise).

Return STRICT JSON only, no markdown fences, no commentary, in this exact shape:
{{
  "tables": {{
    "<table_name>": {{"description": "...", "synonyms": ["...", "..."]}}
  }},
  "columns": {{
    "<table_name>.<column_name>": {{"description": "...", "synonyms": ["...", "..."]}}
  }}
}}
Only include entries for the tables/columns given below. Do not invent new ones.

Schema:
{schema_block}
"""


def _build_schema_block(catalog: SchemaCatalog, table_names: list[str]) -> str:
    lines = []
    for tname in table_names:
        tprof = catalog.tables.get(tname)
        if not tprof:
            continue
        lines.append(f"Table: {tname}")
        for col in tprof.columns:
            lines.append(f"  - {col.name} ({col.type})")
    return "\n".join(lines)


def _extract_json(raw: str) -> Optional[dict]:
    if not raw or not isinstance(raw, str):
        return None
    raw = raw.strip()
    # 1. Remove reasoning / thinking tags (e.g. <think>...</think>)
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.DOTALL).strip()

    # 2. Extract from markdown code fences ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if match:
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except Exception:
            cleaned = candidate  # continue fallback parsing on candidate

    # 3. Direct parse
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # 4. Outermost JSON object substring extraction
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        candidate = cleaned[first_brace:last_brace + 1]
        try:
            return json.loads(candidate)
        except Exception:
            # 5. Fix common LLM JSON syntax errors: trailing commas before } or ]
            try:
                fixed = re.sub(r",\s*([\]}])", r"\1", candidate)
                return json.loads(fixed)
            except Exception:
                pass

    return None


import asyncio


async def build_glossary(catalog: SchemaCatalog, llm_client) -> dict[str, Any]:
    """Generate the business glossary for an entire catalog.

    `llm_client` must expose an async `.generate(prompt: str) -> str` method,
    matching the existing OllamaClient/OpenRouterClient/GroqClient interface
    in app/llm/model.py (get_llm_client()). Any of those work unmodified.

    Returns a merged glossary dict ready for CatalogBuilder.merge_glossary().
    Batches large schemas and paces requests to prevent API rate limits.
    """
    table_names = list(catalog.tables.keys())
    merged: dict[str, Any] = {"tables": {}, "columns": {}}

    # Paced concurrency (max 2 concurrent batch calls) to prevent rate limits (HTTP 429)
    semaphore = asyncio.Semaphore(2)

    async def process_batch(batch: list[str], batch_idx: int):
        async with semaphore:
            # Add stagger between batches to prevent burst token consumption on rate-limited providers
            if batch_idx > 0:
                await asyncio.sleep(0.75 * batch_idx)

            schema_block = _build_schema_block(catalog, batch)
            prompt = GLOSSARY_PROMPT_TEMPLATE.format(schema_block=schema_block)

            try:
                raw = await llm_client.generate(prompt, temperature=0.0)
            except Exception as e:
                logger.warning(
                    f"Glossary enrichment call failed for batch starting at {batch[0] if batch else '?'}: {e}"
                )
                return

            parsed = _extract_json(raw)
            if not parsed:
                sample_preview = (raw[:120] + "...") if len(raw) > 120 else raw
                logger.warning(
                    f"Glossary enrichment returned unparsable JSON for batch {batch}. Output preview: {sample_preview}"
                )
                return

            # Note: dictionary update is thread-safe inside the asyncio event loop since
            # context switches only happen at await boundaries.
            for tname, meta in (parsed.get("tables") or {}).items():
                if tname in catalog.tables and isinstance(meta, dict):
                    merged["tables"][tname] = {
                        "description": str(meta.get("description", ""))[:300],
                        "synonyms": [str(s) for s in (meta.get("synonyms") or [])][:5],
                    }
            for key, meta in (parsed.get("columns") or {}).items():
                if isinstance(meta, dict) and "." in key:
                    merged["columns"][key] = {
                        "description": str(meta.get("description", ""))[:300],
                        "synonyms": [str(s) for s in (meta.get("synonyms") or [])][:5],
                    }

    batches = [table_names[i:i + BATCH_SIZE] for i in range(0, len(table_names), BATCH_SIZE)]
    tasks = [process_batch(batch, idx) for idx, batch in enumerate(batches)]

    if tasks:
        await asyncio.gather(*tasks)

    logger.info(
        f"Glossary enrichment produced {len(merged['tables'])} table entries / {len(merged['columns'])} column entries across {len(tasks)} batch(es)."
    )
    return merged
