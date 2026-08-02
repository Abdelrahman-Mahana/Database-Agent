from typing import Dict, Optional
from app.planning.models import ExecutionPlan

class ExecutionPlanCache:
    def __init__(self):
        self._cache: Dict[str, ExecutionPlan] = {}

    def get(self, plan_id: str) -> Optional[ExecutionPlan]:
        return self._cache.get(plan_id)
        
    def get_by_query_hash(self, query_hash: str) -> Optional[ExecutionPlan]:
        for plan in self._cache.values():
            if plan.query_hash == query_hash:
                return plan
        return None

    def set(self, plan: ExecutionPlan):
        self._cache[plan.plan_id] = plan

    def clear(self):
        self._cache.clear()
