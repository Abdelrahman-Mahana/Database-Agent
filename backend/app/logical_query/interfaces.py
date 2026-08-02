from abc import ABC, abstractmethod
from typing import List, Optional
from app.logical_query.models import (
    LogicalQuery, LogicalExpression, LogicalRelation, LogicalJoin,
    LogicalProjection, LogicalFilter, LogicalGroup, LogicalSort, LogicalLimit
)
from app.planning.models import ExecutionPlan

class IExpressionBuilder(ABC):
    @abstractmethod
    def build(self, metadata: dict) -> LogicalExpression:
        pass

class IJoinGraph(ABC):
    @abstractmethod
    def build_joins(self, plan: ExecutionPlan) -> List[LogicalJoin]:
        pass

class IProjectionBuilder(ABC):
    @abstractmethod
    def build_projections(self, plan: ExecutionPlan) -> LogicalProjection:
        pass

class IAggregationBuilder(ABC):
    @abstractmethod
    def build_aggregations(self, plan: ExecutionPlan) -> Optional[LogicalGroup]:
        pass

class IFilterBuilder(ABC):
    @abstractmethod
    def build_filters(self, plan: ExecutionPlan) -> Optional[LogicalFilter]:
        pass

class ISortBuilder(ABC):
    @abstractmethod
    def build_sorts(self, plan: ExecutionPlan) -> Optional[LogicalSort]:
        pass

class ILimitBuilder(ABC):
    @abstractmethod
    def build_limits(self, plan: ExecutionPlan) -> Optional[LogicalLimit]:
        pass

class ILogicalOptimizer(ABC):
    @abstractmethod
    def optimize(self, query: LogicalQuery) -> LogicalQuery:
        pass

class ILogicalQueryBuilder(ABC):
    @abstractmethod
    def build(self, plan: ExecutionPlan) -> LogicalQuery:
        pass
