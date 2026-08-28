"""Automated Test Suite for Comprehensive 70-Case Golden Evaluation."""
import pytest
from app.services.evaluation.golden_benchmark import GoldenBenchmarkRunner, GOLDEN_BENCHMARK_CASES


def test_golden_benchmark_70_cases_run():
    runner = GoldenBenchmarkRunner()
    scorecard = runner.run_benchmark(GOLDEN_BENCHMARK_CASES)

    print(f"\n--- GOLDEN BENCHMARK SCORECARD ---")
    print(f"Total Cases: {scorecard.total_cases}")
    print(f"Routing Accuracy: {scorecard.routing_accuracy_pct}%")
    print(f"Analysis Type Accuracy: {scorecard.analysis_type_accuracy_pct}%")
    print(f"SQL Correctness: {scorecard.sql_correctness_pct}%")
    print(f"Analysis Correctness: {scorecard.analysis_correctness_pct}%")
    print(f"Claim Grounding: {scorecard.claim_grounding_pct}%")
    print(f"Final Answer Quality: {scorecard.final_answer_quality_pct}%")
    print(f"OVERALL SCORE: {scorecard.overall_score_pct}%")

    assert scorecard.total_cases == 70
    assert scorecard.routing_accuracy_pct >= 95.0
    assert scorecard.analysis_type_accuracy_pct >= 95.0
    assert scorecard.sql_correctness_pct >= 95.0
    assert scorecard.analysis_correctness_pct >= 95.0
    assert scorecard.claim_grounding_pct == 100.0
    assert scorecard.final_answer_quality_pct >= 95.0
    assert scorecard.overall_score_pct >= 95.0


def test_golden_benchmark_category_breakdown():
    runner = GoldenBenchmarkRunner()
    scorecard = runner.run_benchmark(GOLDEN_BENCHMARK_CASES)

    expected_categories = [
        "retrieval",
        "aggregation",
        "comparison",
        "trend",
        "exploratory",
        "root_cause",
        "anomaly_correlation",
    ]

    for cat in expected_categories:
        assert cat in scorecard.category_scores
        cat_score = scorecard.category_scores[cat]
        assert cat_score["routing_pct"] == 100.0
        assert cat_score["sql_pct"] == 100.0
        assert cat_score["claim_pct"] == 100.0
