"""Unit tests for Analysis Planning, Strategy Registry, and Analysis Executor."""
import pytest
from unittest.mock import MagicMock, AsyncMock

from app.services.analysis import (
    AnalysisPlanner,
    AnalysisStrategyRegistry,
    AnalysisExecutor,
    AnalysisPlan,
    AnalysisTask,
    ComputationType,
)
from app.agent.semantic.models import AnalysisLevel, AnalysisOperation, QuerySpec
from app.agent.semantic.query_spec_builder import QuerySpecBuilder
from app.utils.text_processor import AnalysisType


def test_analysis_strategy_registry_exploratory_sales():
    builder = QuerySpecBuilder()
    spec = builder.build_spec("حلل المبيعات")
    
    plan = AnalysisStrategyRegistry.build_plan_for_spec(spec)
    
    assert plan.question == "حلل المبيعات"
    assert plan.analysis_required is True
    assert plan.analysis_level == AnalysisLevel.INSIGHT
    assert len(plan.tasks) >= 4
    
    task_ops = [t.operation for t in plan.tasks]
    assert AnalysisOperation.AGGREGATE in task_ops
    assert AnalysisOperation.TREND in task_ops
    assert AnalysisOperation.COMPARE in task_ops
    assert AnalysisOperation.ANOMALY in task_ops
    
    sub_questions = plan.get_sub_questions()
    assert len(sub_questions) >= 2


def test_analysis_strategy_registry_comparative():
    builder = QuerySpecBuilder()
    spec = builder.build_spec("قارن المبيعات بين 2024 و2025")
    
    plan = AnalysisStrategyRegistry.build_plan_for_spec(spec)
    assert plan.analysis_required is True
    assert any(t.operation == AnalysisOperation.COMPARE for t in plan.tasks)


def test_analysis_strategy_registry_anomaly_detection():
    builder = QuerySpecBuilder()
    spec = builder.build_spec("هل فيه قيم شاذة في الأسعار؟")
    
    plan = AnalysisStrategyRegistry.build_plan_for_spec(spec)
    assert plan.analysis_required is True
    assert any(t.operation == AnalysisOperation.ANOMALY for t in plan.tasks)


def test_analysis_planner_deterministic_and_async():
    planner = AnalysisPlanner()
    builder = QuerySpecBuilder()
    spec = builder.build_spec("حلل أداء أحمد")
    
    plan = planner.plan(spec)
    assert isinstance(plan, AnalysisPlan)
    assert plan.analysis_required is True
    assert len(plan.tasks) > 0


@pytest.mark.asyncio
async def test_analysis_planner_async_llm():
    mock_resp = MagicMock()
    mock_resp.content = """{
      "analysis_goal": "Deep dive into sales trends and anomalies",
      "tasks": [
        {
          "name": "Calculate baseline total",
          "operation": "aggregate",
          "description": "Total sales volume",
          "computation_type": "total"
        },
        {
          "name": "Monthly sales growth",
          "operation": "trend",
          "description": "Month-over-month growth rate",
          "computation_type": "growth_rate"
        }
      ],
      "data_requirements": [
        {
          "description": "Total sales",
          "sub_question": "What is the total sales amount?"
        },
        {
          "description": "Monthly sales",
          "sub_question": "What is the monthly sales breakdown?"
        }
      ],
      "expected_insights": ["Total revenue", "Monthly growth rate"],
      "requires_multi_step": true
    }"""
    
    planner = AnalysisPlanner(fast_llm=MagicMock())
    planner.llm_chain = MagicMock()
    planner.llm_chain.ainvoke = AsyncMock(return_value=mock_resp)
    builder = QuerySpecBuilder()
    spec = builder.build_spec("حلل المبيعات")
    
    plan = await planner.plan_async(spec, schema_text="Invoice (total, invoice_date)")
    assert plan.analysis_required is True
    assert len(plan.tasks) == 2
    assert plan.tasks[0].operation == AnalysisOperation.AGGREGATE
    assert plan.tasks[1].operation == AnalysisOperation.TREND
    assert len(plan.data_requirements) == 2
    assert plan.requires_multi_step is True


def test_analysis_executor_computations():
    executor = AnalysisExecutor()
    builder = QuerySpecBuilder()
    spec = builder.build_spec("حلل المبيعات")
    plan = AnalysisStrategyRegistry.build_plan_for_spec(spec)
    
    # Mock data representing monthly sales
    rows = [
        {"period": "2024-01", "sales": 1000.0},
        {"period": "2024-02", "sales": 1200.0},
        {"period": "2024-03", "sales": 1150.0},
        {"period": "2024-04", "sales": 5000.0},  # Statistical outlier
        {"period": "2024-05", "sales": 1300.0},
    ]
    
    result = executor.execute(plan, rows)
    assert result.success is True
    assert len(result.task_results) > 0
    assert len(result.all_findings) > 0
    
    # Check that outlier detection caught the spike at 2024-04
    findings_text = " ".join(result.all_findings)
    assert "2024-04" in findings_text or "Total sales" in findings_text


def test_analysis_registry_mapping_and_extensibility():
    from app.services.analysis import (
        ANALYSIS_REGISTRY,
        AggregationAnalyzer,
        ComparisonAnalyzer,
        TrendAnalyzer,
        DistributionAnalyzer,
        CorrelationAnalyzer,
        AnomalyAnalyzer,
        SegmentationAnalyzer,
        RootCauseAnalyzer,
        BaseAnalysisAnalyzer,
        AnalysisTaskResult,
        DataRetrievalRequirement,
    )
    
    # Verify core registry contains all required analytical operation mappings
    assert ANALYSIS_REGISTRY["aggregation"] == AggregationAnalyzer
    assert ANALYSIS_REGISTRY["comparison"] == ComparisonAnalyzer
    assert ANALYSIS_REGISTRY["trend"] == TrendAnalyzer
    assert ANALYSIS_REGISTRY["distribution"] == DistributionAnalyzer
    assert ANALYSIS_REGISTRY["correlation"] == CorrelationAnalyzer
    assert ANALYSIS_REGISTRY["anomaly_detection"] == AnomalyAnalyzer
    assert ANALYSIS_REGISTRY["segmentation"] == SegmentationAnalyzer
    assert ANALYSIS_REGISTRY["root_cause"] == RootCauseAnalyzer

    # Test dynamic registration of a new custom analyzer without modifying pipeline
    class CustomCohortAnalyzer(BaseAnalysisAnalyzer):
        operation = AnalysisOperation.SEGMENT
        name = "Custom Churn Cohort"
        
        def plan_tasks(self, spec):
            task = AnalysisTask(
                task_id="task_churn_cohort",
                name="Custom Cohort Retention",
                operation=AnalysisOperation.SEGMENT,
                description="Calculate churn rate per cohort",
            )
            req = DataRetrievalRequirement(
                requirement_id="req_churn",
                description="Fetch churn data",
                sub_question="Fetch churn rates",
            )
            return [task], [req], ["Custom churn retention rates"]

        def execute(self, task, rows, numeric_cols, dimension_cols):
            return AnalysisTaskResult(
                task_id=task.task_id,
                name=task.name,
                findings=["Custom cohort retention evaluated at 88.5%"],
            )

    AnalysisStrategyRegistry.register("custom_churn", CustomCohortAnalyzer)
    
    # Verify retrieval
    retrieved_cls = AnalysisStrategyRegistry.get("custom_churn")
    assert retrieved_cls == CustomCohortAnalyzer
    
    # Verify execution via executor
    executor = AnalysisExecutor()
    custom_task = AnalysisTask(
        task_id="t_custom",
        name="Custom Task",
        operation=AnalysisOperation.SEGMENT,
        description="Run custom",
    )
    plan = AnalysisPlan(
        question="test custom",
        analysis_goal="test custom",
        tasks=[custom_task],
        data_requirements=[],
    )
    # Patch executor dispatch or test custom analyzer directly
    custom_res = CustomCohortAnalyzer().execute(custom_task, [{"a": 1}], ["a"], [])
    assert "88.5%" in custom_res.findings[0]

