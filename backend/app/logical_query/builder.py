import structlog
from typing import List
from app.logical_query.interfaces import (
    ILogicalQueryBuilder, IJoinGraph, IProjectionBuilder, IAggregationBuilder, 
    IFilterBuilder, ISortBuilder, ILimitBuilder
)
from app.logical_query.models import LogicalQuery, LogicalRelation
from app.planning.models import ExecutionPlan, StepType

logger = structlog.get_logger(__name__)

class DeterministicLogicalQueryBuilder(ILogicalQueryBuilder):
    def __init__(
        self,
        join_graph: IJoinGraph,
        projection_builder: IProjectionBuilder,
        aggregation_builder: IAggregationBuilder,
        filter_builder: IFilterBuilder,
        sort_builder: ISortBuilder,
        limit_builder: ILimitBuilder
    ):
        self.join_graph = join_graph
        self.projection_builder = projection_builder
        self.aggregation_builder = aggregation_builder
        self.filter_builder = filter_builder
        self.sort_builder = sort_builder
        self.limit_builder = limit_builder

    def build(self, plan: ExecutionPlan) -> LogicalQuery:
        logger.info("Building logical query", plan_id=plan.plan_id)
        
        lq = LogicalQuery(query_hash=plan.query_hash)
        
        # Base relations
        for step in plan.graph.steps:
            if step.step_type == StepType.SCAN_TABLE:
                table_name = step.parameters.get("table_name")
                if table_name:
                    lq.relations.append(LogicalRelation(table_name=table_name))
                    
        # Apply builders
        lq.joins = self.join_graph.build_joins(plan)
        lq.projections = self.projection_builder.build_projections(plan)
        lq.filters = self.filter_builder.build_filters(plan)
        lq.groupings = self.aggregation_builder.build_aggregations(plan)
        lq.sorts = self.sort_builder.build_sorts(plan)
        lq.limit = self.limit_builder.build_limits(plan)
        
        # Some basic stats/confidence copying
        lq.confidence = plan.confidence
        lq.estimated_complexity = plan.statistics.estimated_complexity
        
        return lq
