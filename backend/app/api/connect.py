"""Database Connection API routes."""
import os
import shutil
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.database.db import set_database_url
from app.schemas.chat import (
    ConnectionConfigRequest,
    ConnectionValidationResponse,
    SchemaResponse,
)
from app.services.connection_manager import connection_manager
from app.services.memory import memory_manager
from app.services.onboarding import onboard_database
from app.services.sql_service import SchemaService
from app.utils.cache import clear_all_caches

router = APIRouter(prefix="/connect", tags=["connect"])


class ConnectURLRequest(BaseModel):
    database_url: str


class ConnectPresetRequest(BaseModel):
    filename: str


def _get_backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _reset_and_get_schema_service(engine) -> SchemaService:
    SchemaService.clear_cache()
    clear_all_caches()
    memory_manager.clear_all()
    return SchemaService(bind_engine=engine)


def _build_schema_response(schema_service: SchemaService, connection_id: str | None = None) -> SchemaResponse:
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
        cache_hit=False,
        connection_id=connection_id,
    )


@router.post("/validate", response_model=ConnectionValidationResponse)
async def validate_connection(body: ConnectionConfigRequest):
    """Test database connectivity without persisting active engine state."""
    try:
        url = connection_manager.build_connection_url(
            db_type=body.db_type,
            host=body.host,
            port=body.port,
            database=body.database,
            username=body.username,
            password=body.password,
            file_path=body.file_path,
            ssl_enabled=body.ssl_enabled,
            ssl_mode=body.ssl_mode,
            connection_url=body.connection_url,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid configuration parameters: {str(e)}")

    success, error_msg, details = connection_manager.validate_connection(url, body.db_type)
    if not success:
        raise HTTPException(status_code=400, detail=error_msg)

    return ConnectionValidationResponse(
        valid=True,
        database_name=details.get("database_name", "Database"),
        database_type=details.get("database_type", body.db_type.upper()),
        summary={
            "objects": details.get("object_count", 0),
            "catalogs": 1,
            "schemas": 1,
        },
    )


@router.post("/config", response_model=SchemaResponse)
async def connect_by_config(body: ConnectionConfigRequest, background_tasks: BackgroundTasks):
    """Connect using structured configuration form parameters and optionally save encrypted profile."""
    try:
        url = connection_manager.build_connection_url(
            db_type=body.db_type,
            host=body.host,
            port=body.port,
            database=body.database,
            username=body.username,
            password=body.password,
            file_path=body.file_path,
            ssl_enabled=body.ssl_enabled,
            ssl_mode=body.ssl_mode,
            connection_url=body.connection_url,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Configuration error: {str(e)}")

    success, error_msg, _ = connection_manager.validate_connection(url, body.db_type)
    if not success:
        raise HTTPException(status_code=400, detail=error_msg)

    profile_id = None
    if body.store_credentials:
        profile = connection_manager.save_profile(
            db_type=body.db_type,
            display_name=body.display_name or body.database or "Connection Profile",
            connection_url=url,
        )
        profile_id = profile.connection_id

    try:
        engine = set_database_url(url)
        schema_service = _reset_and_get_schema_service(engine)
        background_tasks.add_task(onboard_database, schema_service)
        return _build_schema_response(schema_service, profile_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to switch database: {str(e)}")


@router.get("/profiles")
async def list_saved_profiles():
    """List all saved encrypted database connection profiles."""
    profiles = connection_manager.list_saved_profiles()
    return {"profiles": profiles}


@router.post("/reconnect/{connection_id}", response_model=SchemaResponse)
async def reconnect_profile(connection_id: str, background_tasks: BackgroundTasks):
    """Reconnect using a saved encrypted profile ID."""
    url = connection_manager.get_profile_url(connection_id)
    if not url:
        raise HTTPException(status_code=404, detail=f"Saved profile ID '{connection_id}' not found.")

    try:
        engine = set_database_url(url)
        schema_service = _reset_and_get_schema_service(engine)
        background_tasks.add_task(onboard_database, schema_service)
        return _build_schema_response(schema_service, connection_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to reconnect profile: {str(e)}")


@router.get("/databases")
async def list_available_databases():
    """List all available local SQLite database files (presets and uploads)."""
    backend_dir = _get_backend_dir()
    db_files = []
    seen = set()

    def add_file(p: Path, is_upload: bool = False):
        if p.name in seen or not p.is_file():
            return
        seen.add(p.name)
        rel = f"uploads/{p.name}" if is_upload else p.name
        label = f"{p.stem.capitalize()} (Uploaded)" if is_upload else p.stem.capitalize()
        db_files.append({
            "name": label,
            "filename": rel,
            "size_mb": round(p.stat().st_size / (1024 * 1024), 2)
        })

    # 1. Check root backend dir for .db / .sqlite files
    for p in backend_dir.glob("*.db"):
        add_file(p, False)
    for p in backend_dir.glob("*.sqlite"):
        add_file(p, False)

    # 2. Check uploads dir
    uploads_dir = backend_dir / "uploads"
    if uploads_dir.exists():
        for p in uploads_dir.glob("*.*"):
            if p.suffix.lower() in [".db", ".sqlite", ".sqlite3", ".db3"]:
                add_file(p, True)

    return {"databases": db_files}


@router.post("/url", response_model=SchemaResponse)
async def connect_by_url(body: ConnectURLRequest, background_tasks: BackgroundTasks):
    """Switch active database connection using a SQLAlchemy URL."""
    db_url = body.database_url.strip()
    if not db_url:
        raise HTTPException(status_code=400, detail="Database URL cannot be empty.")

    try:
        engine = set_database_url(db_url)
        schema_service = _reset_and_get_schema_service(engine)
        background_tasks.add_task(onboard_database, schema_service)

        schema = schema_service.get_schema()
        schema_text = schema_service.get_schema_text()
        db_name = schema_service.get_database_name()
        db_type = schema_service.get_database_type()
        questions = schema_service.get_recommended_questions()

        return SchemaResponse(
            database_schema=schema,
            schema_text=schema_text,
            database_url=str(engine.url),
            database_name=db_name,
            database_type=db_type,
            recommended_questions=questions,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to connect to database: {str(e)}")


@router.post("/preset", response_model=SchemaResponse)
async def connect_by_preset(body: ConnectPresetRequest, background_tasks: BackgroundTasks):
    """Switch active database connection to a local preset or uploaded SQLite database file."""
    backend_dir = _get_backend_dir()
    rel_path = body.filename.strip()
    
    db_path = (backend_dir / rel_path).resolve()
    if not db_path.exists() or not str(db_path).startswith(str(backend_dir)):
        raise HTTPException(status_code=404, detail=f"Database file '{rel_path}' not found.")

    db_url = f"sqlite:///{db_path}"

    try:
        engine = set_database_url(db_url)
        schema_service = _reset_and_get_schema_service(engine)
        background_tasks.add_task(onboard_database, schema_service)

        schema = schema_service.get_schema()
        schema_text = schema_service.get_schema_text()
        db_name = schema_service.get_database_name()
        db_type = schema_service.get_database_type()
        questions = schema_service.get_recommended_questions()

        return SchemaResponse(
            database_schema=schema,
            schema_text=schema_text,
            database_url=str(engine.url),
            database_name=db_name,
            database_type=db_type,
            recommended_questions=questions,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load database file: {str(e)}")


@router.post("/upload", response_model=SchemaResponse)
async def connect_by_upload(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Upload a SQLite database file (.db, .sqlite, .db3) and set it as active database."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    ext = Path(file.filename).suffix.lower()
    if ext not in [".db", ".sqlite", ".sqlite3", ".db3"]:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Please upload a valid SQLite database file (.db, .sqlite)."
        )

    uploads_dir = _get_backend_dir() / "uploads"
    uploads_dir.mkdir(exist_ok=True)
    
    save_path = uploads_dir / file.filename
    try:
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded database file: {str(e)}")

    db_url = f"sqlite:///{save_path}"

    try:
        engine = set_database_url(db_url)
        schema_service = _reset_and_get_schema_service(engine)
        background_tasks.add_task(onboard_database, schema_service)

        schema = schema_service.get_schema()
        schema_text = schema_service.get_schema_text()
        db_name = schema_service.get_database_name()
        db_type = schema_service.get_database_type()
        questions = schema_service.get_recommended_questions()

        return SchemaResponse(
            database_schema=schema,
            schema_text=schema_text,
            database_url=str(engine.url),
            database_name=db_name,
            database_type=db_type,
            recommended_questions=questions,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load uploaded SQLite database: {str(e)}")
