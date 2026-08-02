from typing import List, Dict, Any
from app.semantic_analysis.interfaces import IDistributionAnalyzer
from app.semantic_analysis.models import SemanticClass

class DistributionAnalyzer(IDistributionAnalyzer):
    def analyze(self, values: List[Any], semantic_class: SemanticClass) -> Dict[str, Any]:
        # Simple heuristic to bin numeric data or get categorical frequencies
        if semantic_class == SemanticClass.CATEGORICAL:
            from collections import Counter
            counts = Counter([str(v) for v in values if v is not None])
            return {"frequencies": dict(counts.most_common(10))}
        
        if semantic_class == SemanticClass.NUMERIC:
            nums = [float(v) for v in values if v is not None and isinstance(v, (int, float, str)) and str(v).replace('.','',1).isdigit()]
            if not nums:
                return {}
            min_val, max_val = min(nums), max(nums)
            bins = 10
            bin_size = (max_val - min_val) / bins if bins > 0 else 1
            if bin_size == 0:
                bin_size = 1
                
            histogram = [0] * bins
            for x in nums:
                idx = min(int((x - min_val) / bin_size), bins - 1)
                histogram[idx] += 1
            return {"histogram": histogram, "bins": bins, "bin_size": bin_size, "min": min_val, "max": max_val}
            
        return {}
