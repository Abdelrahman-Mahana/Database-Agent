"""Phase 1 evaluation — LLM understanding node vs regex baseline.

This is the direct follow-up to eval/run_baseline.py (Phase 0). Where
run_baseline.py measures the deterministic regex parser for free (no LLM
calls), this script spends real tokens to answer the actual question this
rebuild phase is about: *is the LLM understanding node actually better than
the regex parser it's meant to replace, on the same golden dataset?*

Usage (requires a configured LLM provider — see app/core/config.py):

    python -m eval.run_understanding_eval
    python -m eval.run_understanding_eval --save /tmp/llm_understanding.json

Then compare against a regex baseline captured the same way:

    python -m eval.run_baseline --save /tmp/regex_baseline.json
    python -m eval.compare_baseline /tmp/regex_baseline.json /tmp/llm_understanding.json

Do not flip USE_LLM_UNDERSTANDING=true in production until this shows the
LLM path is at or above the regex baseline's type_accuracy and
grounding_recall on both schemas — that's the whole point of keeping the
regex path as a graded fallback instead of deleting it.
"""
import argparse
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.sql_service import SchemaService
from app.schema_grounding.grounding_engine import SchemaGroundingEngine
from app.semantic.llm_understanding import LLMQueryUnderstander
from app.llm.model import get_langchain_llm

from eval.golden_dataset import CHINOOK_CASES, NORTHWIND_CASES


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


async def _run_suite(db_url: str, cases: list[dict], label: str) -> dict:
    os.environ["DATABASE_URL"] = db_url
    SchemaService.clear_cache()

    schema_service = SchemaService()
    grounding_engine = SchemaGroundingEngine(schema_service)
    fast_llm = get_langchain_llm(tier="fast", temperature=0.1)
    understander = LLMQueryUnderstander(fast_llm)

    full_schema = schema_service.get_schema()
    full_schema_text = schema_service.get_schema_text()
    full_tokens = _approx_tokens(full_schema_text)

    n = len(cases)
    type_correct = 0
    recall_hits = 0
    fallback_count = 0
    total_grounded_tokens = 0

    print(f"\n=== {label} (LLM understanding, {n} questions) ===")

    for case in cases:
        q = case["q"]
        expected_type = case["expected_analysis_type"]
        expected_tables = {t.lower() for t in case["expected_tables"]}

        understanding = await understander.understand(q, full_schema)
        if understanding is None:
            # Same policy as production: LLM failed/low-confidence -> regex.
            from app.semantic.parser import SemanticQueryParser
            understanding = SemanticQueryParser().parse(q, full_schema)
            fallback_count += 1

        got_type = understanding.analysis_type.value if hasattr(understanding.analysis_type, "value") else str(understanding.analysis_type)
        grounded = grounding_engine.build_grounded_schema(
            schema=full_schema, query_understanding=understanding, question=q
        )
        grounded_tables = {t.lower() for t in grounded.selected_tables} if hasattr(grounded, "selected_tables") else set()
        grounded_tokens = _approx_tokens(grounded.schema_text)
        total_grounded_tokens += grounded_tokens

        type_ok = (got_type == expected_type)
        recall_ok = expected_tables.issubset(grounded_tables) if grounded_tables else False
        type_correct += int(type_ok)
        recall_hits += int(recall_ok)

        status = "OK " if (type_ok and recall_ok) else "FAIL"
        fb_flag = " [fell back to regex]" if understanding.source != "llm" else ""
        print(f"  [{status}] \"{q[:60]}\" -> type={got_type} (expected {expected_type}), "
              f"tables={sorted(grounded_tables) or '?'} (need {sorted(expected_tables)}){fb_flag}")

    avg_grounded_tokens = total_grounded_tokens / n if n else 0
    reduction_pct = (1 - (avg_grounded_tokens / full_tokens)) * 100 if full_tokens else 0

    print(f"  -> analysis-type accuracy: {type_correct}/{n} ({100*type_correct/n:.0f}%)")
    print(f"  -> schema-grounding recall: {recall_hits}/{n} ({100*recall_hits/n:.0f}%)")
    print(f"  -> regex fallback rate: {fallback_count}/{n} ({100*fallback_count/n:.0f}%)")
    print(f"  -> avg grounded schema size: ≈{avg_grounded_tokens:.0f} tokens vs full ≈{full_tokens} "
          f"({reduction_pct:.0f}% reduction)")

    return {
        "label": label,
        "n": n,
        "type_accuracy": type_correct / n if n else 0,
        "grounding_recall": recall_hits / n if n else 0,
        "fallback_rate": fallback_count / n if n else 0,
        "reduction_pct": reduction_pct,
    }


async def main_async(save_path: str | None):
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    t0 = time.time()

    results = []
    results.append(await _run_suite(f"sqlite:///{backend_dir}/chinook.db", CHINOOK_CASES, "Chinook"))
    results.append(await _run_suite(f"sqlite:///{backend_dir}/Northwind.db", NORTHWIND_CASES, "Northwind"))

    print(f"\n=== SUMMARY (LLM understanding, live LLM cost) — completed in {time.time()-t0:.2f}s ===")
    for r in results:
        print(f"  {r['label']}: type_acc={r['type_accuracy']*100:.0f}% "
              f"grounding_recall={r['grounding_recall']*100:.0f}% "
              f"fallback_rate={r['fallback_rate']*100:.0f}%")

    if save_path:
        import json
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "results": results}, f, indent=2)
        print(f"\nSaved results to {save_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", metavar="PATH", help="Save results as JSON for compare_baseline.py")
    args = parser.parse_args()
    asyncio.run(main_async(args.save))


if __name__ == "__main__":
    main()
