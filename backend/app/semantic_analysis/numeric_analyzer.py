import math
from typing import List, Any, Dict
from app.semantic_analysis.interfaces import IProfileAnalyzer

class NumericAnalyzer(IProfileAnalyzer):
    def analyze(self, values: List[Any]) -> Dict[str, Any]:
        nums = [float(v) for v in values if v is not None and isinstance(v, (int, float, str)) and str(v).replace('.','',1).isdigit()]
        if not nums:
            return {}
            
        count = len(nums)
        minimum = min(nums)
        maximum = max(nums)
        mean = sum(nums) / count
        
        sorted_nums = sorted(nums)
        mid = count // 2
        median = sorted_nums[mid] if count % 2 != 0 else (sorted_nums[mid - 1] + sorted_nums[mid]) / 2.0
        
        variance = sum((x - mean) ** 2 for x in nums) / count if count > 1 else 0.0
        std = math.sqrt(variance)
        
        q1_index = count // 4
        q3_index = q1_index * 3
        q1 = sorted_nums[q1_index] if count >= 4 else minimum
        q3 = sorted_nums[q3_index] if count >= 4 else maximum
        
        return {
            "count": count,
            "min": minimum,
            "max": maximum,
            "mean": mean,
            "median": median,
            "std": std,
            "variance": variance,
            "q1": q1,
            "q3": q3
        }
