from typing import List, Any, Dict
from app.semantic_analysis.interfaces import IProfileAnalyzer

class TextAnalyzer(IProfileAnalyzer):
    def analyze(self, values: List[Any]) -> Dict[str, Any]:
        strs = [str(v) for v in values if v is not None]
        if not strs:
            return {}
            
        lengths = [len(s) for s in strs]
        empty_count = sum(1 for l in lengths if l == 0)
        
        return {
            "average_length": sum(lengths) / len(lengths),
            "min_length": min(lengths),
            "max_length": max(lengths),
            "empty_ratio": empty_count / len(lengths)
        }
