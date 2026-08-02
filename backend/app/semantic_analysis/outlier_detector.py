from typing import List, Any, Dict
import math
from app.semantic_analysis.interfaces import IOutlierDetector
from app.semantic_analysis.models import SemanticClass

class OutlierDetector(IOutlierDetector):
    def detect_outliers(self, values: List[Any], semantic_class: SemanticClass) -> Dict[str, Any]:
        if semantic_class != SemanticClass.NUMERIC:
            return {}
            
        nums = sorted([float(v) for v in values if v is not None and isinstance(v, (int, float, str)) and str(v).replace('.','',1).isdigit()])
        count = len(nums)
        if count < 4:
            return {}
            
        q1_index = count // 4
        q3_index = q1_index * 3
        q1 = nums[q1_index]
        q3 = nums[q3_index]
        iqr = q3 - q1
        
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        
        outliers_iqr = [x for x in nums if x < lower_bound or x > upper_bound]
        
        mean = sum(nums) / count
        variance = sum((x - mean) ** 2 for x in nums) / count
        std = math.sqrt(variance)
        
        outliers_z = []
        if std > 0:
            outliers_z = [x for x in nums if abs(x - mean) / std > 3.0]
            
        return {
            "iqr": {
                "lower_bound": lower_bound,
                "upper_bound": upper_bound,
                "outlier_count": len(outliers_iqr)
            },
            "zscore": {
                "outlier_count": len(outliers_z),
                "threshold": 3.0
            }
        }
