"""
Manual smoke test - runs a handful of representative questions (Arabic +
English, simple + Planner + off-topic) against a live AnalystAgent and
prints the full response for eyeballing. Not part of the pytest suite -
use `pytest tests/` for automated tests.

Run from anywhere: `python backend/scripts/manual_smoke_test.py`
"""
import asyncio
import json
import os
import sys

# This script lives in backend/scripts/; go up one level to reach backend/
# (the actual project root that `app` is importable from).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.agents.analyst_agent import AnalystAgent

async def run_tests():
    agent = AnalystAgent()
    db = SessionLocal()
    
    questions = [
        "اعرض كل البيانات من الجداول", # Test LIMIT
        "قارن مبيعات يناير بفبراير", # Test Planner / Arabic
        "What are the top 3 product categories with the highest average order value, and how do their sales volumes compare to each other?", # Test Planner
        "احكيلي نكتة" # Test off-topic
    ]
    
    results = {}
    for q in questions:
        print(f"\n--- Running question: {q} ---")
        try:
            resp = await agent.ask(q, db)
            # Remove full results from print to avoid spamming the console
            num_results = len(resp.get("results", []))
            resp["results"] = f"[{num_results} rows]"
            print(json.dumps(resp, indent=2, ensure_ascii=False))
            results[q] = resp
        except Exception as e:
            print(f"Error: {e}")
            
    db.close()

if __name__ == "__main__":
    asyncio.run(run_tests())
