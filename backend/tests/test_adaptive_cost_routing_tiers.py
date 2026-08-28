"""Unit tests for the 4-Tier Adaptive Cost Routing Pipeline."""
import pytest
from app.utils.cost_router import (
    CostExecutionTier,
    resolve_execution_and_cost_path,
    should_use_self_consistency,
    choose_sql_generation_tier,
)
from app.agent.semantic.models import QuerySpec, AnalysisType


def test_tier_1_simple_lookup_fast_path():
    spec = QuerySpec(
        raw_question="بيانات العميل رقم 123",
        analysis_type=AnalysisType.LOOKUP,
        confidence=1.0,
    )

    tier = resolve_execution_and_cost_path(
        query_spec=spec,
        grounded_table_count=1,
        has_grouping=False,
    )

    assert tier == CostExecutionTier.FAST_PATH


def test_tier_2_simple_metric_deterministic_path():
    spec = QuerySpec(
        raw_question="كم إجمالي عدد الفواتير؟",
        analysis_type=AnalysisType.COUNT,
        confidence=1.0,
    )

    tier = resolve_execution_and_cost_path(
        query_spec=spec,
        grounded_table_count=1,
        has_grouping=False,
    )

    assert tier == CostExecutionTier.DETERMINISTIC_PATH


def test_tier_3_complex_analysis_fast_synthesis():
    spec = QuerySpec(
        raw_question="كيف تطورت المبيعات الشهرية؟",
        analysis_type=AnalysisType.TREND,
        confidence=1.0,
    )

    tier = resolve_execution_and_cost_path(
        query_spec=spec,
        grounded_table_count=1,
        has_grouping=True,
    )

    assert tier == CostExecutionTier.LLM_PLANNING_FAST_SYNTHESIS


def test_tier_4_ambiguous_or_deep_root_cause_stronger_model():
    # 1. Root cause analysis
    rca_spec = QuerySpec(
        raw_question="ما سبب انخفاض مبيعات الربع الرابع؟",
        analysis_type=AnalysisType.ROOT_CAUSE,
        confidence=0.95,
    )
    assert resolve_execution_and_cost_path(query_spec=rca_spec) == CostExecutionTier.STRONGER_MODEL

    # 2. Ambiguous phrasing with ambiguity marker (e.g. "أفضل فرع")
    ambig_spec = QuerySpec(
        raw_question="ما هو أفضل فرع لدينا؟",
        analysis_type=AnalysisType.LOOKUP,
        confidence=1.0,
    )
    assert resolve_execution_and_cost_path(query_spec=ambig_spec) == CostExecutionTier.STRONGER_MODEL

    # 3. Multi-table join complex query
    multi_table_spec = QuerySpec(
        raw_question="بيانات المبيعات والعملاء والأطباء والعيادات",
        analysis_type=AnalysisType.LOOKUP,
        confidence=1.0,
    )
    assert resolve_execution_and_cost_path(
        query_spec=multi_table_spec,
        grounded_table_count=4,
    ) == CostExecutionTier.STRONGER_MODEL

    # 4. Low confidence query
    low_conf_spec = QuerySpec(
        raw_question="أرقام غير واضحة",
        analysis_type=AnalysisType.LOOKUP,
        confidence=0.5,
    )
    assert resolve_execution_and_cost_path(
        query_spec=low_conf_spec,
        confidence=0.5,
    ) == CostExecutionTier.STRONGER_MODEL
