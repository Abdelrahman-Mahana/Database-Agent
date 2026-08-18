"""Schema API routes."""
from fastapi import APIRouter

from app.database.db import DATABASE_URL
from app.schemas.chat import SchemaResponse
from app.services.sql_service import SchemaService
from app.services.connection_manager import connection_manager

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

@router.post("/refresh/{table_name}")
async def refresh_table_profile(table_name: str, schema_name: str = None):
    """
    Incrementally refresh the data profile (row counts, values) for a specific table 
    without rebuilding the entire catalog.
    """
    from app.schema_catalog.catalog_builder import CatalogBuilder
    
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

