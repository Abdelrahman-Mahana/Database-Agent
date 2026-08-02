from abc import ABC, abstractmethod
from typing import List
from app.planning.models import ExecutionStep, ExecutionPlan, ExecutionGraph
from app.query_understanding.models import QueryUnderstanding
from app.database.intelligence.models import SchemaIntelligence
from app.database.profiling.models import DatabaseProfile

class IStepBuilder(ABC):
    @abstractmethod
    def build(self, qu: QueryUnderstanding) -> List[ExecutionStep]:
        pass

class IJoinPlanner(ABC):
    @abstractmethod
    def plan_joins(self, qu: QueryUnderstanding, intelligence: SchemaIntelligence) -> List[ExecutionStep]:
        pass

class IAggregationPlanner(ABC):
    @abstractmethod
    def plan_aggregations(self, qu: QueryUnderstanding) -> List[ExecutionStep]:
        pass

class IFilterPlanner(ABC):
    @abstractmethod
    def plan_filters(self, qu: QueryUnderstanding) -> List[ExecutionStep]:
        pass

class ISortPlanner(ABC):
    @abstractmethod
    def plan_sorts(self, qu: QueryUnderstanding) -> List[ExecutionStep]:
        pass

class ILimitPlanner(ABC):
    @abstractmethod
    def plan_limits(self, qu: QueryUnderstanding) -> List[ExecutionStep]:
        pass

class IDependencyResolver(ABC):
    @abstractmethod
    def resolve(self, steps: List[ExecutionStep]) -> ExecutionGraph:
        pass

class IPlanOptimizer(ABC):
    @abstractmethod
    def optimize(self, graph: ExecutionGraph) -> ExecutionGraph:
        pass

class IExecutionPlanner(ABC):
    @abstractmethod
    def create_plan(self, query_hash: str, qu: QueryUnderstanding, intelligence: SchemaIntelligence, profile: DatabaseProfile) -> ExecutionPlan:
        pass
