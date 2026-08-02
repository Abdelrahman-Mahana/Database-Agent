"""Schema API routes."""
from fastapi import APIRouter

from app.database.db import DATABASE_URL
from app.schemas.chat import SchemaResponse
from app.services.sql_service import SchemaService

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
        database_url=str(schema_service.engine.url),
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
    )

