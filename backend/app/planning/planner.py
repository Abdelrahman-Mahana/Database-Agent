import structlog
from app.planning.interfaces import (
    IExecutionPlanner, IStepBuilder, IJoinPlanner, IAggregationPlanner,
    IFilterPlanner, ISortPlanner, ILimitPlanner, IDependencyResolver, IPlanOptimizer
)
from app.planning.models import ExecutionPlan, PlanStatistics
from app.query_understanding.models import QueryUnderstanding
from app.database.intelligence.models import SchemaIntelligence
from app.database.profiling.models import DatabaseProfile
from app.planning.utils import estimate_complexity

logger = structlog.get_logger(__name__)

class DeterministicExecutionPlanner(IExecutionPlanner):
    def __init__(
        self,
        step_builder: IStepBuilder,
        join_planner: IJoinPlanner,
        aggregation_planner: IAggregationPlanner,
        filter_planner: IFilterPlanner,
        sort_planner: ISortPlanner,
        limit_planner: ILimitPlanner,
        dependency_resolver: IDependencyResolver,
        optimizer: IPlanOptimizer
    ):
        self.step_builder = step_builder
        self.join_planner = join_planner
        self.aggregation_planner = aggregation_planner
        self.filter_planner = filter_planner
        self.sort_planner = sort_planner
        self.limit_planner = limit_planner
        self.dependency_resolver = dependency_resolver
        self.optimizer = optimizer

    def create_plan(
        self, 
        query_hash: str, 
        qu: QueryUnderstanding, 
        intelligence: SchemaIntelligence, 
        profile: DatabaseProfile
    ) -> ExecutionPlan:
        
        logger.info("Creating execution plan", query_hash=query_hash)
        
        steps = []
        
        # 1. Base Scan & Project Steps
        steps.extend(self.step_builder.build(qu))
        
        # 2. Joins
        steps.extend(self.join_planner.plan_joins(qu, intelligence))
        
        # 3. Filters
        steps.extend(self.filter_planner.plan_filters(qu))
        
        # 4. Aggregations
        steps.extend(self.aggregation_planner.plan_aggregations(qu))
        
        # 5. Sorts
        steps.extend(self.sort_planner.plan_sorts(qu))
        
        # 6. Limits
        steps.extend(self.limit_planner.plan_limits(qu))
        
        # 7. Resolve Dependencies (Build Graph)
        graph = self.dependency_resolver.resolve(steps)
        
        # 8. Optimize
        optimized_graph = self.optimizer.optimize(graph)
        
        # 9. Statistics Estimation
        complexity = estimate_complexity(len(optimized_graph.steps))
        stats = PlanStatistics(
            estimated_complexity=complexity,
            estimated_cost=len(optimized_graph.steps) * 10.5,
            estimated_rows=1000, # Dummy heuristic
            estimated_memory=1024 * 1024 * 50, # 50 MB placeholder
            estimated_duration=0.5 # 500 ms placeholder
        )
        
        # In the future, hash should come reliably from schema metadata
        schema_hash = "no_schema"
        if intelligence and hasattr(intelligence, "schema_hash") and intelligence.schema_hash:
            schema_hash = intelligence.schema_hash
        
        return ExecutionPlan(
            query_hash=query_hash,
            schema_hash=schema_hash,
            planner_version="1.0.0",
            graph=optimized_graph,
            statistics=stats,
            confidence=0.9
        )
