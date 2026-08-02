from typing import List, Optional
from datetime import datetime, timedelta
from app.query_understanding.interfaces import ITimeParser
from app.query_understanding.models import TimeRange

class DeterministicTimeParser(ITimeParser):
    def parse(self, time_expressions: List[str]) -> Optional[TimeRange]:
        if not time_expressions:
            return None
            
        now = datetime.now()
        expr = time_expressions[0] # Take first for simplicity
        
        if expr == "today":
            return TimeRange(start_time=now.replace(hour=0, minute=0, second=0), end_time=now, expression=expr)
        elif expr == "yesterday":
            start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
            end = start.replace(hour=23, minute=59, second=59)
            return TimeRange(start_time=start, end_time=end, expression=expr)
        elif expr == "last week":
            start = now - timedelta(days=7)
            return TimeRange(start_time=start, end_time=now, expression=expr)
        elif expr == "last month":
            start = now - timedelta(days=30)
            return TimeRange(start_time=start, end_time=now, expression=expr)
        elif expr == "last year":
            start = now - timedelta(days=365)
            return TimeRange(start_time=start, end_time=now, expression=expr)
            
        return TimeRange(start_time=None, end_time=None, expression=expr)
