from typing import List, Optional, Dict
from pydantic import BaseModel, Field

class StatisticsMetadata(BaseModel):
    row_count: Optional[int] = None
    size_bytes: Optional[int] = None
    last_analyzed: Optional[str] = None

class ColumnMetadata(BaseModel):
    name: str
    data_type: str
    nullable: bool = True
    unique: bool = False
    indexed: bool = False
    primary_key: bool = False
    foreign_key: bool = False
    default: Optional[str] = None
    comment: Optional[str] = None

class IndexMetadata(BaseModel):
    name: str
    columns: List[str]
    unique: bool

class ForeignKeyMetadata(BaseModel):
    name: str
    constrained_columns: List[str]
    referred_schema: Optional[str]
    referred_table: str
    referred_columns: List[str]

class ConstraintMetadata(BaseModel):
    name: str
    type: str  # CHECK, UNIQUE
    definition: Optional[str] = None

class ProcedureMetadata(BaseModel):
    name: str
    definition: Optional[str] = None

class FunctionMetadata(BaseModel):
    name: str
    definition: Optional[str] = None

class TriggerMetadata(BaseModel):
    name: str
    definition: Optional[str] = None

class TableMetadata(BaseModel):
    name: str
    columns: List[ColumnMetadata] = Field(default_factory=list)
    primary_keys: List[str] = Field(default_factory=list)
    foreign_keys: List[ForeignKeyMetadata] = Field(default_factory=list)
    indexes: List[IndexMetadata] = Field(default_factory=list)
    constraints: List[ConstraintMetadata] = Field(default_factory=list)
    triggers: List[TriggerMetadata] = Field(default_factory=list)
    statistics: StatisticsMetadata = Field(default_factory=StatisticsMetadata)
    is_view: bool = False
    is_materialized_view: bool = False

class SchemaMetadata(BaseModel):
    name: str
    tables: List[TableMetadata] = Field(default_factory=list)
    views: List[TableMetadata] = Field(default_factory=list)
    materialized_views: List[TableMetadata] = Field(default_factory=list)
    procedures: List[ProcedureMetadata] = Field(default_factory=list)
    functions: List[FunctionMetadata] = Field(default_factory=list)

class RelationshipEdge(BaseModel):
    source_schema: str
    source_table: str
    source_columns: List[str]
    target_schema: str
    target_table: str
    target_columns: List[str]
    relationship_name: str

class DatabaseMetadata(BaseModel):
    name: str
    version: Optional[str] = None
    schemas: List[SchemaMetadata] = Field(default_factory=list)
    relationships: List[RelationshipEdge] = Field(default_factory=list)
    created_at: Optional[str] = None
