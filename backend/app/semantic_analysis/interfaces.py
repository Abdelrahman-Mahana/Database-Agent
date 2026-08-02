from abc import ABC, abstractmethod
from typing import List, Dict, Any
from app.result_processing.models import ProcessedResult, ColumnMetadata
from app.semantic_analysis.models import (
    SemanticClass, ColumnProfile, DatasetProfile, RelationshipDetection, SemanticAnalysisResult, QualityMetrics
)

class IColumnClassifier(ABC):
    @abstractmethod
    def classify(self, column: ColumnMetadata, values: List[Any]) -> SemanticClass:
        pass

class IAnalyzer(ABC):
    @abstractmethod
    def analyze(self, result: ProcessedResult) -> SemanticAnalysisResult:
        pass

class IProfileAnalyzer(ABC):
    @abstractmethod
    def analyze(self, values: List[Any]) -> Dict[str, Any]:
        pass

class IOutlierDetector(ABC):
    @abstractmethod
    def detect_outliers(self, values: List[Any], semantic_class: SemanticClass) -> Dict[str, Any]:
        pass

class IRelationshipDetector(ABC):
    @abstractmethod
    def detect(self, profiles: Dict[str, ColumnProfile], rows: List[Dict[str, Any]]) -> RelationshipDetection:
        pass

class IStatisticsEngine(ABC):
    @abstractmethod
    def compute(self, profiles: Dict[str, ColumnProfile]) -> Dict[str, Any]:
        pass

class IQualityAnalyzer(ABC):
    @abstractmethod
    def analyze(self, values: List[Any]) -> QualityMetrics:
        pass
        
class IDistributionAnalyzer(ABC):
    @abstractmethod
    def analyze(self, values: List[Any], semantic_class: SemanticClass) -> Dict[str, Any]:
        pass

class IMetadataBuilder(ABC):
    @abstractmethod
    def build(self, result: ProcessedResult, profiles: Dict[str, ColumnProfile], dataset: DatasetProfile, rels: RelationshipDetection, stats: Dict[str, Any], processing_time_ms: float) -> SemanticAnalysisResult:
        pass
