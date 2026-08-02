import structlog
from typing import Optional
from app.planning.models import ExecutionPlan
from app.planning.interfaces import IExecutionPlanner
from app.planning.cache import ExecutionPlanCache
from app.query_understanding.service import QueryUnderstandingService
from app.database.intelligence.service import SchemaIntelligenceService
from app.database.profiling.service import DataProfilingService
from app.query_understanding.utils import generate_query_hash

logger = structlog.get_logger(__name__)

class ExecutionPlanningService:
    def __init__(
        self,
        planner: IExecutionPlanner,
        cache: ExecutionPlanCache,
        qu_service: QueryUnderstandingService,
        intelligence_service: SchemaIntelligenceService,
        profiling_service: DataProfilingService
    ):
        self.planner = planner
        self.cache = cache
        self.qu_service = qu_service
        self.intelligence_service = intelligence_service
        self.profiling_service = profiling_service

    async def create_plan(self, plugin_name: str, query: str) -> ExecutionPlan:
        query_hash = generate_query_hash(plugin_name, query)
        
        cached = self.cache.get_by_query_hash(query_hash)
        if cached:
            return cached
            
        qu = await self.qu_service.understand(plugin_name, query)
        intelligence = self.intelligence_service.get_intelligence(plugin_name)
        profile = self.profiling_service.get_profile(plugin_name)
        
        plan = self.planner.create_plan(query_hash, qu, intelligence, profile)
        self.cache.set(plan)
        return plan

    def get_plan(self, plan_id: str) -> Optional[ExecutionPlan]:
        return self.cache.get(plan_id)
