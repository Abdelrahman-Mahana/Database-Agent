"""Phase 0 baseline evaluation runner.

Two modes:

  python -m eval.run_baseline
      Offline mode (default, free, no API key needed). Exercises only the
      deterministic layers — SemanticQueryParser, SchemaGroundingEngine,
      classify_analysis_type — against the real Chinook/Northwind databases
      shipped with the repo. Reports:
        - analysis-type classification accuracy
        - schema-grounding recall (did we keep the tables the question needs?)
        - schema-grounding token reduction (grounded vs full schema text size)

  python -m eval.run_baseline --live
      Also runs the off-schema questions through the *real* agent (requires
      a configured LLM provider) to check the UNANSWERABLE sentinel fires
      correctly, and prints actual token/cost usage per question via the
      existing token_tracker. Use this before/after any prompt or model
      change to see the real cost delta, not a guess.

Run this BEFORE making any further changes to the pipeline, save the output,
then re-run after each change. A change that doesn't move these numbers (or
moves them the wrong way) is not a real improvement.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.sql_service import SchemaService
from app.schema_grounding.grounding_engine import SchemaGroundingEngine
from app.semantic.parser import SemanticQueryParser
from app.utils.text_processor import classify_analysis_type

from eval.golden_dataset import CHINOOK_CASES, NORTHWIND_CASES, OFF_SCHEMA_CASES

# Rough token estimate (no tiktoken dependency needed for a ballpark figure);
# ~4 chars/token is a standard approximation for English/code-like text.
def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _run_offline_suite(db_url: str, cases: list[dict], label: str) -> dict:
    os.environ["DATABASE_URL"] = db_url
    SchemaService.clear_cache()

    schema_service = SchemaService()
    grounding_engine = SchemaGroundingEngine(schema_service)
    parser = SemanticQueryParser()

    full_schema = schema_service.get_schema()
    full_schema_text = schema_service.get_schema_text()
    full_tokens = _approx_tokens(full_schema_text)

    n = len(cases)
    type_correct = 0
    recall_hits = 0
    total_grounded_tokens = 0

    print(f"\n=== {label} ({n} questions, {len(full_schema)} tables, "
          f"full schema ≈ {full_tokens} tokens) ===")

    for case in cases:
        q = case["q"]
        expected_type = case["expected_analysis_type"]
        expected_tables = {t.lower() for t in case["expected_tables"]}

        got_type = classify_analysis_type(q).value
        understanding = parser.parse(q, full_schema)
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
        print(f"  [{status}] \"{q[:60]}\" -> type={got_type} (expected {expected_type}), "
              f"tables={sorted(grounded_tables) or '?'} (need {sorted(expected_tables)})")

    avg_grounded_tokens = total_grounded_tokens / n if n else 0
    reduction_pct = (1 - (avg_grounded_tokens / full_tokens)) * 100 if full_tokens else 0

    print(f"  -> analysis-type accuracy: {type_correct}/{n} ({100*type_correct/n:.0f}%)")
    print(f"  -> schema-grounding recall: {recall_hits}/{n} ({100*recall_hits/n:.0f}%)")
    print(f"  -> avg grounded schema size: ≈{avg_grounded_tokens:.0f} tokens "
          f"vs full schema ≈{full_tokens} tokens ({reduction_pct:.0f}% reduction per question)")

    return {
        "label": label,
        "n": n,
        "type_accuracy": type_correct / n if n else 0,
        "grounding_recall": recall_hits / n if n else 0,
        "avg_grounded_tokens": avg_grounded_tokens,
        "full_schema_tokens": full_tokens,
        "reduction_pct": reduction_pct,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Also run off-schema cases through the real agent (needs an LLM key)")
    parser.add_argument("--save", metavar="PATH", help="Save results as JSON to PATH (for regression comparison via compare_baseline.py)")
    args = parser.parse_args()

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    t0 = time.time()

    results = []
    results.append(_run_offline_suite(f"sqlite:///{backend_dir}/chinook.db", CHINOOK_CASES, "Chinook"))
    results.append(_run_offline_suite(f"sqlite:///{backend_dir}/Northwind.db", NORTHWIND_CASES, "Northwind"))

    print(f"\n=== SUMMARY (offline, no LLM cost) — completed in {time.time()-t0:.2f}s ===")
    for r in results:
        print(f"  {r['label']}: type_acc={r['type_accuracy']*100:.0f}% "
              f"grounding_recall={r['grounding_recall']*100:.0f}% "
              f"token_reduction={r['reduction_pct']:.0f}%")

    if args.save:
        import json
        with open(args.save, "w", encoding="utf-8") as f:
            json.dump({"timestamp": time.time(), "results": results}, f, indent=2)
        print(f"\nSaved results to {args.save}")

    if args.live:
        import asyncio
        from sqlalchemy.orm import sessionmaker
        from app.agents.analyst_agent import AnalystAgent
        from app.database.db import engine as default_engine

        async def run_live():
            print("\n=== LIVE off-schema (UNANSWERABLE) checks ===")
            agent = AnalystAgent()
            SessionLocal = sessionmaker(bind=default_engine)
            db = SessionLocal()
            try:
                correct = 0
                for case in OFF_SCHEMA_CASES:
                    result = await agent.ask(case["q"], db)
                    flagged = ("cannot" in result.get("report", "").lower()
                               or "unanswerable" in str(result.get("error", "")).lower()
                               or not result.get("results"))
                    correct += int(flagged)
                    print(f"  [{ 'OK' if flagged else 'FAIL' }] \"{case['q']}\" -> "
                          f"success={result.get('success')}, sql={result.get('sql', '')[:60]!r}")
                print(f"  -> off-schema refusal rate: {correct}/{len(OFF_SCHEMA_CASES)}")
            finally:
                db.close()

        asyncio.run(run_live())


if __name__ == "__main__":
    main()
