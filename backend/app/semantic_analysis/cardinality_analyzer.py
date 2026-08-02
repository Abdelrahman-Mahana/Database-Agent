from typing import List, Any, Dict
from app.semantic_analysis.interfaces import IProfileAnalyzer

class CardinalityAnalyzer(IProfileAnalyzer):
    def analyze(self, values: List[Any]) -> Dict[str, Any]:
        valid_vals = [v for v in values if v is not None]
        unique_count = len(set(valid_vals))
        total_count = len(valid_vals)
        return {
            "cardinality": unique_count,
            "cardinality_ratio": unique_count / total_count if total_count else 0.0
        }
