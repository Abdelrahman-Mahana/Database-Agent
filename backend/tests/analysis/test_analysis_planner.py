"""Tests for Analysis Planner and Task Decomposition."""
import pytest
from app.services.analysis.planner import AnalysisPlanner
from app.services.analysis.models import AnalysisPlan, AnalysisTask
from app.agent.semantic.models import QuerySpec, AnalysisType, AnalysisOperation, AnalysisLevel


def test_analysis_planner_heuristic_plan():
    spec = QuerySpec(
        raw_question="حلل مبيعات الربع الأخير",
        analysis_type=AnalysisType.ROOT_CAUSE,
        analysis_level=AnalysisLevel.INSIGHT,
        analysis_goal="Explain sales drop in Q4",
        operations=[AnalysisOperation.ROOT_CAUSE, AnalysisOperation.TREND],
        dimensions=["region", "quarter"],
        metrics=["sales"],
    )

    plan = AnalysisPlanner.plan(spec)

    assert isinstance(plan, AnalysisPlan)
    assert plan.analysis_goal == "Explain sales drop in Q4"
    assert len(plan.tasks) >= 1


def test_analysis_planner_comparison_tasks():
    spec = QuerySpec(
        raw_question="قارن بين القاهرة والإسكندرية",
        analysis_type=AnalysisType.COMPARISON,
        analysis_level=AnalysisLevel.METRIC,
        analysis_goal="Compare sales between Cairo and Alexandria",
        operations=[AnalysisOperation.COMPARE],
        comparisons=["Cairo vs Alexandria"],
    )

    plan = AnalysisPlanner.plan(spec)

    assert isinstance(plan, AnalysisPlan)
    assert len(plan.tasks) >= 1
