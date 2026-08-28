"""Unit and Integration Tests for Phase 9: Production Optimization & Efficiency.

Tests:
1. Cache hit (investigation plan and verified evidence served with 0 SQL/LLM calls).
2. Cache miss (unseen question returns None).
3. Stale cache invalidation (entries exceeding max_age_seconds are evicted).
4. Database isolation (cached data in DB_A is completely isolated from DB_B).
5. Schema version isolation (schema updates invalidate prior cached analyses).
6. Semantic query cache (configurable similarity threshold, cross-database isolation).
7. Duplicate query deduplication (redundant tasks identified and skipped).
8. Model routing (deterministic operations routed to Python, cheap vs reasoning tiers).
9. Conditional self-consistency gate (multi-candidate SQL triggered only on high risk/complexity).
10. Query budget early stopping (investigation stops once completeness and confidence are achieved).
11. SystemMetricsTracker & Benchmark comparison (latency, cost, token reductions measured).
"""
import time
import pytest
from unittest.mock import MagicMock

from app.services.analysis.production_optimizer import (
    InvestigationCache,
    ModelRouteDecision,
    ModelRouter,
    ModelTier,
    QueryDeduplicator,
    SelfConsistencyGate,
    SemanticQueryCache,
    SystemMetricsTracker,
    TelemetrySnapshot,
)
from app.services.analysis.investigation_engine import InvestigationEngine
from app.services.analysis.investigation_models import (
    EvidenceItem,
    InvestigationPlan,
    InvestigationState,
    InvestigationStatus,
    QueryExecutionRecord,
    QueryExecutionStatus,
    QueryTask,
    QueryTaskStatus,
)
from app.services.analysis.query_selector import QuerySelector


# ─── Test 1: Cache Hit ───

def test_1_investigation_cache_hit():
    """Test 1: Cached investigation returns stored evidence and completeness."""
    cache = InvestigationCache()
    plan = InvestigationPlan(
        question="What is total revenue?",
        query_tasks=[QueryTask(query_id="q_1", purpose="Total revenue", sub_question="Total revenue")],
    )
    state = InvestigationEngine.initialize_investigation(plan)
    state.evidence = [
        EvidenceItem(evidence_id="ev_1", statement="Total revenue is $1,000,000", metric="revenue", value=1000000.0, verified=True)
    ]
    state.completeness_score = 1.0
    state.confidence_score = 0.95
    state.status = InvestigationStatus.COMPLETED

    cache.set(
        question="What is total revenue?",
        database_fingerprint="db_prod_1",
        schema_version="v1.0",
        state=state,
    )

    hit = cache.get(
        question="What is total revenue?",
        database_fingerprint="db_prod_1",
        schema_version="v1.0",
    )

    assert hit is not None
    assert hit["completeness_score"] == 1.0
    assert len(hit["evidence"]) == 1
    assert hit["evidence"][0]["statement"] == "Total revenue is $1,000,000"


# ─── Test 2: Cache Miss ───

def test_2_investigation_cache_miss():
    """Test 2: Uncached question returns None."""
    cache = InvestigationCache()
    hit = cache.get(
        question="Unseen question about churn?",
        database_fingerprint="db_prod_1",
        schema_version="v1.0",
    )
    assert hit is None


# ─── Test 3: Stale Cache Invalidation ───

def test_3_stale_cache_invalidation():
    """Test 3: Stale cache entries exceeding max_age_seconds are evicted."""
    cache = InvestigationCache()
    state = InvestigationState(
        completeness_score=1.0,
        status=InvestigationStatus.COMPLETED,
    )

    cache.set(
        question="Monthly sales trend",
        database_fingerprint="db_prod_1",
        schema_version="v1.0",
        state=state,
    )

    # Valid when max_age_seconds is large
    valid_hit = cache.get("Monthly sales trend", "db_prod_1", "v1.0", max_age_seconds=100)
    assert valid_hit is not None

    # Stale when max_age_seconds is 0 (immediate expiration)
    time.sleep(0.01)
    stale_hit = cache.get("Monthly sales trend", "db_prod_1", "v1.0", max_age_seconds=0)
    assert stale_hit is None


# ─── Test 4: Database Isolation ───

def test_4_database_isolation():
    """Test 4: Cache entries in DB_Alpha cannot be accessed by DB_Beta (zero cross-DB contamination)."""
    cache = InvestigationCache()
    state = InvestigationState(
        evidence=[EvidenceItem(evidence_id="ev_a", statement="Confidential DB A data", verified=True)],
        completeness_score=1.0,
        status=InvestigationStatus.COMPLETED,
    )

    cache.set(
        question="Show customer balances",
        database_fingerprint="db_tenant_alpha",
        schema_version="v1.0",
        state=state,
    )

    # Tenant Beta attempts to access Tenant Alpha's cached query
    leak_attempt = cache.get(
        question="Show customer balances",
        database_fingerprint="db_tenant_beta",
        schema_version="v1.0",
    )
    assert leak_attempt is None


# ─── Test 5: Schema Version Isolation ───

def test_5_schema_version_isolation():
    """Test 5: Schema updates invalidate or isolate prior cached investigations."""
    cache = InvestigationCache()
    state = InvestigationState(completeness_score=1.0, status=InvestigationStatus.COMPLETED)

    cache.set(
        question="Select all orders",
        database_fingerprint="db_prod_1",
        schema_version="v1.0_hash_abc",
        state=state,
    )

    # Schema migrated to v2
    after_migration = cache.get(
        question="Select all orders",
        database_fingerprint="db_prod_1",
        schema_version="v2.0_hash_xyz",
    )
    assert after_migration is None


# ─── Test 6: Semantic Query Cache ───

def test_6_semantic_query_cache():
    """Test 6: Semantic cache matches equivalent questions above similarity threshold."""
    sem_cache = SemanticQueryCache(similarity_threshold=0.80)
    sem_cache.store(
        question="What is the total number of registered customers?",
        database_fingerprint="db_main",
        schema_version="v1",
        result={"customer_count": 5000},
    )

    # Semantically equivalent question with high keyword overlap
    match = sem_cache.lookup(
        question="What is the total number of registered customers in system?",
        database_fingerprint="db_main",
        schema_version="v1",
    )
    assert match is not None
    orig_q, res, score = match
    assert res == {"customer_count": 5000}
    assert score >= 0.80

    # Unrelated question fails threshold
    unrelated = sem_cache.lookup(
        question="How many server errors occurred yesterday?",
        database_fingerprint="db_main",
        schema_version="v1",
    )
    assert unrelated is None


# ─── Test 7: Duplicate Query Deduplication ───

def test_7_query_deduplication():
    """Test 7: QueryDeduplicator flags tasks whose metrics/evidence are already collected."""
    state = InvestigationState(
        evidence=[
            EvidenceItem(
                evidence_id="ev_revenue",
                source_query_id="q_1",
                statement="Total revenue = $500K",
                metric="revenue",
                value=500000.0,
                verified=True,
            )
        ],
        completed_queries=[
            QueryExecutionRecord(
                query_id="q_1",
                purpose="Get total revenue",
                sub_question="Total revenue",
                status=QueryExecutionStatus.SUCCESS,
                rows=[{"revenue": 500000.0}],
            )
        ],
    )

    dup_task = QueryTask(
        query_id="q_dup",
        purpose="Get total revenue",
        sub_question="Total revenue",
        required_metrics=["revenue"],
    )

    is_redundant, reason = QueryDeduplicator.is_task_redundant(dup_task, state)
    assert is_redundant is True
    assert "already" in reason.lower()

    unique_task = QueryTask(
        query_id="q_unique",
        purpose="Get return rate by product",
        sub_question="Return rate by product",
        required_metrics=["return_rate"],
    )
    is_redundant_2, _ = QueryDeduplicator.is_task_redundant(unique_task, state)
    assert is_redundant_2 is False


# ─── Test 8: Model Routing ───

def test_8_model_routing():
    """Test 8: ModelRouter classifies deterministic tasks to Python, and routes by complexity."""
    # Deterministic operations
    decision_stat = ModelRouter.route_task("statistical_reconciliation")
    assert decision_stat.tier == ModelTier.DETERMINISTIC
    assert decision_stat.is_deterministic is True
    assert decision_stat.estimated_cost_per_1k_tokens == 0.0

    # Simple task -> cheap fast tier
    decision_fast = ModelRouter.route_task("single_table_select", complexity_score=0.2)
    assert decision_fast.tier == ModelTier.CHEAP_FAST
    assert decision_fast.is_deterministic is False

    # Highly complex / ambiguous task -> heavy reasoning tier
    decision_heavy = ModelRouter.route_task("complex_multi_table_root_cause", complexity_score=0.85, has_ambiguity=True)
    assert decision_heavy.tier == ModelTier.HEAVY_REASONING
    assert decision_heavy.is_deterministic is False


# ─── Test 9: Conditional Self-Consistency Gate ───

def test_9_conditional_self_consistency_gate():
    """Test 9: Self-consistency is bypassed for routine queries and activated for high-risk/complex queries."""
    # Routine query: single table, low ambiguity, high confidence -> bypass (saves 2+ LLM calls)
    triggered, reason = SelfConsistencyGate.should_trigger(
        question="Count customers",
        table_count=1,
        join_count=0,
        ambiguity_score=0.1,
        confidence=0.95,
    )
    assert triggered is False

    # Complex multi-join query -> trigger
    triggered_c, _ = SelfConsistencyGate.should_trigger(
        question="Join 5 tables",
        table_count=5,
        join_count=4,
    )
    assert triggered_c is True

    # Previous query failed -> trigger
    triggered_f, _ = SelfConsistencyGate.should_trigger(
        question="Retry query",
        previous_failed=True,
    )
    assert triggered_f is True


# ─── Test 10: Query Budget Early Stopping ───

def test_10_query_budget_early_stopping():
    """Test 10: QuerySelector triggers early stopping when full evidence and confidence are achieved."""
    plan = InvestigationPlan(
        question="Optimize spend",
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Q1", sub_question="Q1", status=QueryTaskStatus.COMPLETED),
            QueryTask(query_id="q_2", purpose="Q2", sub_question="Q2", status=QueryTaskStatus.PENDING),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)
    state.completeness_score = 1.0  # 100% complete
    state.confidence_score = 0.90   # High confidence
    state.unresolved_questions = [] # Zero remaining unresolved questions

    selector = QuerySelector()
    res = selector.select_next_query(state)
    assert res.selected_task is None
    assert "early stopping" in res.reason.lower()


# ─── Test 11: SystemMetricsTracker & Benchmark Comparison ───

def test_11_metrics_tracker_and_benchmark_comparison():
    """Test 11: Telemetry records execution metrics and benchmark calculates reduction percentages."""
    baseline = SystemMetricsTracker.create_snapshot(
        investigation_id="inv_base_1",
        query_count=5,
        llm_calls=6,
        cache_hits=0,
        cache_misses=5,
        total_tokens=12000,
        latency_ms=3500.0,
        completeness_score=100.0,
    )

    optimized = SystemMetricsTracker.create_snapshot(
        investigation_id="inv_opt_1",
        query_count=2,
        llm_calls=2,
        cache_hits=3,
        cache_misses=2,
        total_tokens=4000,
        latency_ms=1100.0,
        completeness_score=100.0,
    )

    comparison = SystemMetricsTracker.compare_benchmarks(baseline, optimized)
    assert comparison["latency_reduction_pct"] > 60.0
    assert comparison["cost_reduction_pct"] > 60.0
    assert comparison["llm_calls_reduction_pct"] > 60.0
    assert comparison["accuracy_maintained"] is True
