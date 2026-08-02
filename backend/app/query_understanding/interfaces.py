from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from app.query_understanding.models import (
    QueryIntent, QueryEntities, QueryFilter, TimeRange, 
    QueryAmbiguity, QueryContext, QueryRouting, ConfidenceScore, QueryUnderstanding
)
from app.database.discovery.models import DatabaseMetadata
from app.database.intelligence.models import SchemaIntelligence
from app.database.profiling.models import DatabaseProfile

class IQueryNormalizer(ABC):
    @abstractmethod
    def normalize(self, query: str) -> str:
        pass

class IIntentClassifier(ABC):
    @abstractmethod
    def classify(self, normalized_query: str) -> QueryIntent:
        pass

class IEntityExtractor(ABC):
    @abstractmethod
    def extract(self, normalized_query: str, metadata: DatabaseMetadata) -> QueryEntities:
        pass

class IMetricDetector(ABC):
    @abstractmethod
    def detect(self, entities: QueryEntities, metadata: DatabaseMetadata, intelligence: SchemaIntelligence) -> List[str]:
        pass

class IDimensionDetector(ABC):
    @abstractmethod
    def detect(self, entities: QueryEntities, metadata: DatabaseMetadata, intelligence: SchemaIntelligence) -> List[str]:
        pass

class IFilterExtractor(ABC):
    @abstractmethod
    def extract(self, normalized_query: str, entities: QueryEntities, metadata: DatabaseMetadata) -> List[QueryFilter]:
        pass

class ITimeParser(ABC):
    @abstractmethod
    def parse(self, time_expressions: List[str]) -> Optional[TimeRange]:
        pass

class IAmbiguityDetector(ABC):
    @abstractmethod
    def detect(self, query: str, entities: QueryEntities, metrics: List[str], dimensions: List[str], metadata: DatabaseMetadata) -> List[QueryAmbiguity]:
        pass

class IContextBuilder(ABC):
    @abstractmethod
    def build(self, entities: QueryEntities, metrics: List[str], dimensions: List[str], metadata: DatabaseMetadata, intelligence: SchemaIntelligence, profile: DatabaseProfile) -> QueryContext:
        pass

class IRouter(ABC):
    @abstractmethod
    def route(self, intent: QueryIntent, entities: QueryEntities) -> QueryRouting:
        pass

class IConfidenceScorer(ABC):
    @abstractmethod
    def score(self, intent: QueryIntent, entities: QueryEntities, ambiguities: List[QueryAmbiguity]) -> ConfidenceScore:
        pass
