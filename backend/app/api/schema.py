"""Schema API routes."""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.database.db import DATABASE_URL, get_db
from app.models.schemas.chat import SchemaResponse
from app.services.sql_service import SchemaService, SqlExecutor
from app.services.connection_manager import connection_manager
from app.utils.validator import get_target_dialect

router = APIRouter(prefix="/schema", tags=["schema"])
schema_service = SchemaService()


@router.get("", response_model=SchemaResponse)
async def get_schema(force_refresh: bool = False):
    """Return the auto-discovered database schema and metadata."""
    if force_refresh:
        schema_service.refresh_cache()

    valid_entry = schema_service._get_valid_entry()
    cache_hit = bool(valid_entry) and not force_refresh

    schema = schema_service.get_schema()
    schema_text = schema_service.get_schema_text()
    db_name = schema_service.get_database_name()
    db_type = schema_service.get_database_type()
    questions = schema_service.get_recommended_questions()
    explorer_data = schema_service.get_explorer_data()

    return SchemaResponse(
        database_schema=schema,
        schema_text=schema_text,
        database_url=connection_manager.mask_connection_url(str(schema_service.engine.url)),
        database_name=db_name,
        database_type=db_type,
        recommended_questions=questions,
        tables=explorer_data.get("tables", []),
        views=explorer_data.get("views", []),
        procedures=explorer_data.get("procedures", []),
        collections=explorer_data.get("collections", []),
        schema_tree=explorer_data.get("schema_tree", []),
        summary=explorer_data.get("summary", {}),
        cache_hit=cache_hit,
        fingerprint=schema_service._get_db_fingerprint(),
    )


@router.get("/preview/{table_name}")
async def preview_table_data(
    table_name: str,
    schema_name: Optional[str] = None,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """
    Fetch a live sample preview (top 10-50 rows) for any table in the active database.
    """
    clean_table = table_name.strip()
    if not clean_table or any(c in clean_table for c in ";'\":"):
        raise HTTPException(status_code=400, detail="Invalid table name")

    limit_count = min(max(1, limit), 50)
    dialect = get_target_dialect()
    
    # Construct safe quoted identifier based on dialect
    if dialect in ("postgresql", "postgres"):
        if schema_name and schema_name != "public":
            target_table = f'"{schema_name}"."{clean_table}"'
        else:
            target_table = f'public."{clean_table}"' if "." not in clean_table else clean_table
    elif dialect in ("mysql", "mariadb"):
        target_table = f'`{clean_table}`'
    else:
        target_table = f'"{clean_table}"'

    query = f"SELECT * FROM {target_table} LIMIT {limit_count}"
    
    try:
        rows = SqlExecutor.execute(query, db, max_rows=limit_count)
        columns = list(rows[0].keys()) if rows else []
        return {
            "status": "success",
            "table_name": clean_table,
            "schema_name": schema_name or "public",
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "limit": limit_count,
        }
    except Exception as exc:
        # Try fallback without schema prefix or without double quotes
        fallback_query = f"SELECT * FROM {clean_table} LIMIT {limit_count}"
        try:
            rows = SqlExecutor.execute(fallback_query, db, max_rows=limit_count)
            columns = list(rows[0].keys()) if rows else []
            return {
                "status": "success",
                "table_name": clean_table,
                "schema_name": schema_name or "public",
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "limit": limit_count,
            }
        except Exception as fallback_exc:
            raise HTTPException(
                status_code=400,
                detail=f"Unable to preview table '{clean_table}': {str(exc)}"
            )


@router.post("/refresh/{table_name}")
async def refresh_table_profile(table_name: str, schema_name: str = None):
    """
    Incrementally refresh the data profile (row counts, values) for a specific table 
    without rebuilding the entire catalog.
    """
    from app.models.schema_catalog.catalog_builder import CatalogBuilder
    
    # Fast structural refresh first if needed, though this specifically targets data profiling
    profile_data = schema_service.profile_table_data(table_name, schema_name=schema_name)
    
    # Save the updated profile to the persistent catalog
    builder = CatalogBuilder(schema_service)
    catalog = builder.get_or_build(force_rebuild=False)
    
    fqn = f"{schema_name}.{table_name}" if schema_name and schema_name != "public" else table_name
    
    if fqn in catalog.tables:
        tprof = catalog.tables[fqn]
        tprof.row_count = profile_data.get("row_count")
        
        col_updates = profile_data.get("columns", {})
        for col in tprof.columns:
            if col.name in col_updates:
                col.samples = col_updates[col.name].get("samples", [])
                col.date_range = col_updates[col.name].get("date_range")
                
        builder.save(catalog)
        return {"status": "success", "table": fqn, "message": "Table profile incrementally updated"}
    else:
        return {"status": "error", "message": f"Table {fqn} not found in catalog"}
