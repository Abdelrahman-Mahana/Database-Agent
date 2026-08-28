"""Unit tests for the unified AnalysisResult model."""
import pytest
from app.services.analysis.models import AnalysisResult, AnalysisPlan
from app.services.analytics.models import AnalyticsResult, DatasetSummary, NumericSummary, InsightResult, InsightItem, InsightSeverity
from app.agent.semantic.models import QuerySpec, AnalysisType, AnalysisOperation, AnalysisLevel


def test_analysis_result_initialization():
    result = AnalysisResult(
        analysis_type="root_cause",
        goal="Identify reason for sales drop",
        findings=["Sales decreased 18%"],
        metrics={"drop_amount": -18000.0, "drop_percentage": -18.0},
        evidence=["Q4 sales = 820K", "Q3 sales = 1.0M"],
        warnings=["Low sample size in Region C"],
        limitations=["Marketing campaign data was not available"],
        confidence=0.97,
        recommendations=["Investigate supply chain in Region A"],
    )

    assert result.analysis_type == "root_cause"
    assert result.findings == ["Sales decreased 18%"]
    assert result.evidence == ["Q4 sales = 820K", "Q3 sales = 1.0M"]
    assert result.confidence == 0.97
    assert result.metrics["drop_amount"] == -18000.0


def test_analysis_result_factory_from_analytics_and_insights():
    ds = DatasetSummary(row_count=100, column_count=2, column_names=["region", "sales"], numeric_columns=["sales"], categorical_columns=["region"])
    num_stat = NumericSummary(column_name="sales", count=100, min_value=10.0, max_value=500.0, mean=150.0)
    analytics_res = AnalyticsResult(dataset=ds, numeric_stats={"sales": num_stat}, analytical_findings=["Sales mean is 150.0"])

    insight_item = InsightItem(
        category="numeric",
        severity=InsightSeverity.INFO,
        title="Key Stat",
        message="Sales mean is 150.0 and max is 500.0",
    )
    insight_res = InsightResult(summary="Overview", insights=[insight_item])

    spec = QuerySpec(
        raw_question="حلل المبيعات",
        analysis_type=AnalysisType.EXPLORATORY_ANALYSIS,
        analysis_goal="Explore sales statistics",
    )

    unified = AnalysisResult.from_analytics_and_insights(
        analytics_result=analytics_res,
        insight_result=insight_res,
        query_spec=spec,
        confidence=0.95,
    )

    assert unified.analysis_type == "exploratory_analysis"
    assert unified.goal == "Explore sales statistics"
    assert unified.metrics["sales_mean"] == 150.0
    assert unified.metrics["sales_min"] == 10.0
    assert unified.metrics["sales_max"] == 500.0
    assert len(unified.findings) >= 1
    assert unified.confidence == 0.95
    assert len(unified.evidence) >= 1
