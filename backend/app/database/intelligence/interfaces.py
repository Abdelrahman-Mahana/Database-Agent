from abc import ABC, abstractmethod
from typing import List, Dict
from app.database.discovery.models import DatabaseMetadata, RelationshipEdge, TableMetadata, ColumnMetadata
from app.database.intelligence.models import (
    IntelligenceGraph, ColumnSemantic, TableClassification, DomainConfidence
)

class IRelationshipDetector(ABC):
    @abstractmethod
    def detect(self, metadata: DatabaseMetadata) -> List[RelationshipEdge]:
        pass

class ISemanticClassifier(ABC):
    @abstractmethod
    def classify_column(self, column: ColumnMetadata) -> ColumnSemantic:
        pass

class ITableClassifier(ABC):
    @abstractmethod
    def classify_table(self, table: TableMetadata) -> TableClassification:
        pass

class IBusinessDomainDetector(ABC):
    @abstractmethod
    def detect(self, tables: List[TableMetadata]) -> List[DomainConfidence]:
        pass

class IGraphBuilder(ABC):
    @abstractmethod
    def build(self, metadata: DatabaseMetadata, relationships: List[RelationshipEdge]) -> IntelligenceGraph:
        pass
