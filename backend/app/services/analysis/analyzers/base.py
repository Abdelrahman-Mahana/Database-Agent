"""Base class for modular and extensible analysis analyzers."""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from app.services.analysis.models import (
    AnalysisTask,
    AnalysisTaskResult,
    ComputationType,
    DataRetrievalRequirement,
)
from app.agent.semantic.models import AnalysisOperation, QuerySpec


class BaseAnalysisAnalyzer(ABC):
    """Abstract Base Class for all analytical domain analyzers.

    Each analyzer defines how to:
    1. Plan analytical tasks and data retrieval requirements for its operation (`plan_tasks`).
    2. Compute metrics, detect anomalies/trends, and generate verified findings (`execute`).
    """

    operation: AnalysisOperation
    name: str

    @abstractmethod
    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        """Generate tasks, data retrieval requirements, and expected insights for this operation."""
        pass

    @abstractmethod
    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        """Execute the analytical computation on retrieved SQL data."""
        pass
