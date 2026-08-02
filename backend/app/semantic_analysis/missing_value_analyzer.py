from typing import List, Any, Dict
from app.semantic_analysis.interfaces import IQualityAnalyzer
from app.semantic_analysis.models import QualityMetrics

class QualityAnalyzer(IQualityAnalyzer):
    def analyze(self, values: List[Any]) -> QualityMetrics:
        total = len(values)
        if total == 0:
            return QualityMetrics()
            
        null_count = sum(1 for v in values if v is None)
        valid_vals = [str(v) for v in values if v is not None]
        unique_vals = set(valid_vals)
        
        null_ratio = null_count / total
        completeness = 1.0 - null_ratio
        
        duplicate_count = len(valid_vals) - len(unique_vals)
        duplicate_ratio = duplicate_count / len(valid_vals) if valid_vals else 0.0
        
        uniqueness_ratio = len(unique_vals) / len(valid_vals) if valid_vals else 0.0
        
        # Calculate overall quality score
        quality_score = (completeness * 0.7) + (uniqueness_ratio * 0.3)
        if duplicate_ratio > 0.5:
            quality_score -= 0.1
        quality_score = max(0.0, min(1.0, quality_score))
        
        return QualityMetrics(
            null_ratio=null_ratio,
            duplicate_ratio=duplicate_ratio,
            uniqueness_ratio=uniqueness_ratio,
            completeness=completeness,
            quality_score=quality_score
        )

# We map Cardinality, Missing values, and Uniqueness under QualityAnalyzer for simplicity 
# to comply with "uniqueness_analyzer, missing_value_analyzer, cardinality_analyzer" requested files.
