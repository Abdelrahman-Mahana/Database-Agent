from typing import List, Any, Dict
from collections import Counter
from app.semantic_analysis.interfaces import IProfileAnalyzer

class CategoricalAnalyzer(IProfileAnalyzer):
    def analyze(self, values: List[Any]) -> Dict[str, Any]:
        valid_vals = [str(v) for v in values if v is not None]
        if not valid_vals:
            return {}
            
        counter = Counter(valid_vals)
        unique_count = len(counter)
        total_count = len(valid_vals)
        
        top_values = counter.most_common(5)
        
        return {
            "unique_values": unique_count,
            "cardinality_ratio": unique_count / total_count if total_count else 0.0,
            "top_values": [{"value": k, "frequency": v} for k, v in top_values]
        }
