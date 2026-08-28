"""Phase 8 — cost dashboard & execution telemetry API."""
import os
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.services.database import db as global_db
from app.services.database.db import get_db
from app.utils.cost_dashboard import cost_dashboard
from app.utils.validator import validate_sql, transpile_sql_to_dialect, get_target_dialect
from app.services.sql_service import SqlExecutor
from app.services.connection_manager import connection_manager

router = APIRouter(prefix="/stats", tags=["stats"])


class ValidateQueryRequest(BaseModel):
    query: str


class ExecuteSqlRequest(BaseModel):
    query: str
    max_rows: Optional[int] = 100
    explain: Optional[bool] = True


@router.get("")
async def get_stats_overview():
    """Consolidated telemetry overview for the system and execution engine."""
    try:
        engine = global_db.get_engine()
        db_url_str = str(engine.url)
        db_name = "Database"
        if hasattr(engine.url, "database") and engine.url.database:
            db_name = os.path.splitext(os.path.basename(str(engine.url.database)))[0].capitalize()
        elif hasattr(engine.url, "host") and engine.url.host:
            db_name = str(engine.url.host)
        
        db_type = getattr(getattr(engine, "dialect", None), "name", "SQL").upper()
        masked_url = connection_manager.mask_connection_url(db_url_str)
    except Exception:
        db_name = "Connected Database"
        db_type = "SQL"
        masked_url = ""

    cost_data = cost_dashboard.summary()

    return {
        "status": "operational",
        "database": {
            "name": db_name,
            "type": db_type,
            "url": masked_url,
        },
        "cost_summary": cost_data,
        "dialect": get_target_dialect(),
    }


@router.get("/cost")
async def get_cost_summary():
    """Aggregated token usage / estimated cost, broken down by day and by
    question analysis-type. Resets on process restart (in-process store)."""
    return cost_dashboard.summary()


@router.get("/cost/recent")
async def get_recent_usage(limit: int = 50):
    """Most recent individual request usage records (for a live-ish feed)."""
    return [vars(r) for r in cost_dashboard.recent(limit=limit)]


@router.post("/validate-sql")
async def validate_sql_endpoint(req: ValidateQueryRequest):
    """Live test bench for SQL safety guard and dialect transpilation."""
    val_res = validate_sql(req.query)
    dialect = get_target_dialect()
    transpiled = req.query
    if val_res.get("valid"):
        transpiled = transpile_sql_to_dialect(req.query, dialect)
    return {
        "valid": val_res.get("valid", False),
        "reason": val_res.get("reason", ""),
        "query_type": val_res.get("query_type", "unknown"),
        "sanitized_sql": transpiled,
        "dialect": dialect,
    }


@router.post("/execute-sql")
async def execute_direct_sql_endpoint(req: ExecuteSqlRequest, db: Session = Depends(get_db)):
    """
    Safely execute a user SQL query in read-only mode with validation,
    row bounding, dialect transpilation, execution timing, and plan explain.
    """
    query_str = req.query.strip()
    if not query_str:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    dialect = get_target_dialect()
    val_res = validate_sql(query_str)
    
    if not val_res.get("valid", False):
        return {
            "success": False,
            "sql": query_str,
            "error": f"SQL Validation Failed: {val_res.get('reason', 'Forbidden or invalid SQL construct')}",
            "query_type": val_res.get("query_type", "unknown"),
            "columns": [],
            "rows": [],
            "row_count": 0,
            "execution_time_ms": 0.0,
            "plan": None,
            "dialect": dialect,
        }

    transpiled = transpile_sql_to_dialect(query_str, dialect)
    start_time = time.time()
    
    # Optional Plan Check / EXPLAIN
    plan_text = None
    if req.explain:
        try:
            ok, exp_msg = SqlExecutor.explain(transpiled, db)
            plan_text = "EXPLAIN plan check succeeded" if ok else f"Plan note: {exp_msg}"
        except Exception as plan_err:
            plan_text = f"Plan check skipped: {plan_err}"

    try:
        max_rows = min(max(1, req.max_rows or 100), 500)
        rows = SqlExecutor.execute(transpiled, db, max_rows=max_rows)
        duration_ms = round((time.time() - start_time) * 1000, 2)
        
        columns = list(rows[0].keys()) if rows else []
        
        return {
            "success": True,
            "sql": query_str,
            "sanitized_sql": transpiled,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "execution_time_ms": duration_ms,
            "plan": plan_text,
            "dialect": dialect,
            "error": None,
        }
    except Exception as exec_err:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "success": False,
            "sql": query_str,
            "sanitized_sql": transpiled,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "execution_time_ms": duration_ms,
            "plan": plan_text,
            "dialect": dialect,
            "error": str(exec_err),
        }
