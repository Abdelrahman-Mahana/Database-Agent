import asyncio
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.agents.analyst_agent import AnalystAgent
import json

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
