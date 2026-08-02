from typing import Dict, Any
from app.result_processing.models import ProcessedResult
from app.semantic_analysis.interfaces import IMetadataBuilder
from app.semantic_analysis.models import SemanticAnalysisResult, ColumnProfile, DatasetProfile, RelationshipDetection, AnalysisMetrics

class SchemaSemantics:
    def extract_schema_semantics(self, result: ProcessedResult) -> Dict[str, Any]:
        return {"original_columns": len(result.schema_def.columns)}

class MetadataBuilder(IMetadataBuilder):
    def build(self, result: ProcessedResult, profiles: Dict[str, ColumnProfile], dataset: DatasetProfile, rels: RelationshipDetection, stats: Dict[str, Any], processing_time_ms: float) -> SemanticAnalysisResult:
        metrics = AnalysisMetrics(
            processing_time_ms=processing_time_ms,
            peak_memory_mb=0.0 # Can be calculated if needed
        )
        return SemanticAnalysisResult(
            result_id=result.result_id,
            column_profiles=profiles,
            dataset_profile=dataset,
            relationships=rels,
            statistics=stats,
            semantic_metadata={"generated_by": "deterministic_analyzer"},
            analysis_metrics=metrics
        )
