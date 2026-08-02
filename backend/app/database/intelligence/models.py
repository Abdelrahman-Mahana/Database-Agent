from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class NodeType(str, Enum):
    TABLE = "table"
    VIEW = "view"
    COLUMN = "column"
    SCHEMA = "schema"
    INDEX = "index"

class EdgeType(str, Enum):
    FK = "fk"
    INFERRED = "inferred"
    BELONGS_TO = "belongs_to"
    USES = "uses"
    REFERENCES = "references"
    RELATIONSHIP = "relationship"

class GraphNode(BaseModel):
    id: str
    label: str
    type: NodeType

class GraphEdge(BaseModel):
    source: str
    target: str
    label: str
    type: EdgeType = EdgeType.RELATIONSHIP
    weight: float

class IntelligenceGraph(BaseModel):
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)

class ColumnSemantic(BaseModel):
    column_name: str
    semantic_type: str
    confidence: float
    evidence: str = ""
    reason: str = ""

class TableClassification(BaseModel):
    table_name: str
    role: str
    confidence: float
    evidence: str = ""
    reason: str = ""
    columns: List[ColumnSemantic] = Field(default_factory=list)

class DomainConfidence(BaseModel):
    domain: str
    confidence: float
    matched_tables: List[str] = Field(default_factory=list)
    matched_columns: List[str] = Field(default_factory=list)
    matched_keywords: List[str] = Field(default_factory=list)

class SchemaIntelligence(BaseModel):
    database_name: str
    relationship_graph: IntelligenceGraph = Field(default_factory=IntelligenceGraph)
    tables: List[TableClassification] = Field(default_factory=list)
    business_domains: List[DomainConfidence] = Field(default_factory=list)
    generated_at: Optional[datetime] = None
