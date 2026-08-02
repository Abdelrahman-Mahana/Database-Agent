from typing import List, Any, Dict
from app.semantic_analysis.interfaces import IProfileAnalyzer

class UniquenessAnalyzer(IProfileAnalyzer):
    def analyze(self, values: List[Any]) -> Dict[str, Any]:
        valid_vals = [v for v in values if v is not None]
        unique_count = len(set(valid_vals))
        total_count = len(valid_vals)
        uniqueness = unique_count / total_count if total_count else 0.0
        return {
            "is_unique": uniqueness == 1.0,
            "uniqueness_ratio": uniqueness,
            "duplicate_count": total_count - unique_count
        }
