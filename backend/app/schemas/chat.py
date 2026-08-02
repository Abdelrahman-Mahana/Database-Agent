"""Pydantic schemas for chat API."""
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    question: str
    sql: str
    results: list[dict[str, Any]]
    report: str
    chart_suggestion: dict[str, Any]
    success: bool
    error: str | None
    attempted_sql: str | None = None
    error_type: str | None = None
    suggestions: list[str] | None = None
    intent: str | None = None
    analysis_type: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class HealthResponse(BaseModel):
    status: str
    llm_available: bool
    llm_provider: str
    ollama_available: bool
    model: str
    llm_latency_ms: float | None = None
    pricing: dict[str, float] | None = None


class BaseDBObject(BaseModel):
    name: str
    qualified_name: str
    catalog: str = "main"
    schema_name: str = Field(default="main", serialization_alias="schema")
    object_type: str = "table"
    columns: list[dict[str, Any]] = []
    primary_key: list[str] = []
    foreign_keys: list[dict[str, Any]] = []
    indexes: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []
    definition: str | None = None
    document_count: int | None = None


class SchemaTreeNode(BaseModel):
    id: str
    kind: str
    name: str
    path: list[str] = []
    children: list["SchemaTreeNode"] = []
    meta: dict[str, Any] | None = None


class SchemaSummary(BaseModel):
    catalogs: int = 1
    schemas: int = 1
    tables: int = 0
    views: int = 0
    procedures: int = 0
    collections: int = 0
    columns: int = 0
    indexes: int = 0
    foreign_keys: int = 0
    constraints: int = 0
    objects: int = 0


class SavedProfileSchema(BaseModel):
    connection_id: str
    db_type: str
    display_name: str
    database_name: str
    masked_url: str
    updated_at: float = 0.0


class SchemaResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    database_schema: dict[str, Any] = Field(alias="schema")
    schema_text: str
    database_url: str
    database_name: str = "Database"
    database_type: str = "SQL"
    recommended_questions: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []
    procedures: list[dict[str, Any]] = []
    collections: list[dict[str, Any]] = []
    schema_tree: list[dict[str, Any]] = []
    summary: dict[str, Any] = Field(default_factory=dict)
    cache_hit: bool = False
    connection_id: str | None = None


class ConnectionConfigRequest(BaseModel):
    db_type: str
    display_name: str | None = None
    connection_url: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    username: str | None = None
    password: str | None = None
    file_path: str | None = None
    ssl_enabled: bool = False
    ssl_mode: str | None = None
    store_credentials: bool = True


class ConnectionValidationResponse(BaseModel):
    valid: bool
    database_name: str
    database_type: str
    summary: dict[str, Any] = Field(default_factory=dict)


