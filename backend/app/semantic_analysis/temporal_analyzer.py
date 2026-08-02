from typing import List, Any, Dict
from datetime import datetime
from app.semantic_analysis.interfaces import IProfileAnalyzer

class TemporalAnalyzer(IProfileAnalyzer):
    def analyze(self, values: List[Any]) -> Dict[str, Any]:
        dates = []
        for v in values:
            if v is not None:
                if isinstance(v, datetime):
                    dates.append(v)
                elif isinstance(v, str):
                    try:
                        dates.append(datetime.fromisoformat(v.replace("Z", "+00:00")))
                    except ValueError:
                        pass
                        
        if not dates:
            return {}
            
        min_date = min(dates)
        max_date = max(dates)
        
        return {
            "min_date": min_date.isoformat(),
            "max_date": max_date.isoformat(),
            "date_range_days": (max_date - min_date).days,
            "detected_granularity": "days" # simplified heuristic
        }
