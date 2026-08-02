import structlog
from typing import Optional
from app.logical_query.models import LogicalQuery
from app.logical_query.interfaces import ILogicalQueryBuilder, ILogicalOptimizer
from app.logical_query.cache import LogicalQueryCache
from app.planning.service import ExecutionPlanningService

logger = structlog.get_logger(__name__)

class LogicalQueryService:
    def __init__(
        self,
        builder: ILogicalQueryBuilder,
        optimizer: ILogicalOptimizer,
        cache: LogicalQueryCache,
        planning_service: ExecutionPlanningService
    ):
        self.builder = builder
        self.optimizer = optimizer
        self.cache = cache
        self.planning_service = planning_service

    def build_query(self, plan_id: str) -> LogicalQuery:
        logger.info("Building logical query from plan", plan_id=plan_id)
        
        plan = self.planning_service.get_plan(plan_id)
        if not plan:
            raise ValueError(f"Execution plan {plan_id} not found")
            
        lq = self.builder.build(plan)
        optimized = self.optimizer.optimize(lq)
        
        self.cache.set(optimized)
        return optimized

    def get_query(self, query_id: str) -> Optional[LogicalQuery]:
        return self.cache.get(query_id)
