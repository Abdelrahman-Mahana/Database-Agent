"""Phase 8 — cost dashboard & execution telemetry API."""
from fastapi import APIRouter
from pydantic import BaseModel

from app.utils.cost_dashboard import cost_dashboard
from app.utils.validator import validate_sql, transpile_sql_to_dialect, get_target_dialect

router = APIRouter(prefix="/stats", tags=["stats"])


class ValidateQueryRequest(BaseModel):
    query: str


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
