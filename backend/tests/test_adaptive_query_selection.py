"""Unit and Integration Tests for Phase 5: Adaptive Query Selection.

Tests:
1. Priority-based selection (higher priority task wins when all else equal).
2. Evidence-coverage boost (task providing fresh metrics/dimensions wins).
3. Unresolved questions boost (task targeting active unresolved question wins).
4. Redundancy penalty (task with already satisfied expected evidence is deprioritized).
5. Dependency satisfaction & cascading blocks (ineligible tasks filtered out).
6. Cost penalty (higher estimated_cost receives penalty).
7. Budget urgency (remaining_budget == 1 boosts essential tasks).
8. Deterministic tie-breaking (preserves plan order on exact score ties).
9. No candidates available (returns None with clean explanation).
10. All candidates blocked (all remaining tasks blocked by failed dependency).
11. Transparent explanation provenance (score breakdown and reasoning present).
12. Graph-level end-to-end selection integration (query_selections in agent output).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.analysis.investigation_engine import InvestigationEngine
from app.services.analysis.investigation_models import (
    EvidenceItem,
    EvidenceType,
    InvestigationPlan,
    InvestigationState,
    InvestigationStatus,
    QueryExecutionRecord,
    QueryExecutionStatus,
    QueryTask,
    QueryTaskStatus,
)
from app.services.analysis.query_selector import (
    CandidateEvaluation,
    QuerySelectionResult,
    QuerySelector,
    QuerySelectorConfig,
)
from app.services.analysis.models import AnalysisPlan, AnalysisTask
from app.agent.orchestration.analyst_agent import AnalystAgent
from app.core.config.settings import settings
from app.agent.semantic.models import ExecutionRoute, IntentType, QueryUnderstanding
from app.utils.helpers import AnalysisType


# ─── Test 1: Priority-based Selection ───

def test_1_priority_based_selection():
    """Test 1: Higher priority task (priority 1) is selected over lower priority (priority 3) when all else equal."""
    plan = InvestigationPlan(
        question="Compare metrics",
        query_tasks=[
            QueryTask(query_id="q_low", purpose="Low priority task", sub_question="Low priority", priority=3),
            QueryTask(query_id="q_high", purpose="High priority task", sub_question="High priority", priority=1),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)

    selector = QuerySelector()
    res = selector.select_next_query(state)

    assert res.selected_task is not None
    assert res.selected_query_id == "q_high"
    assert res.score > 0
    assert "priority" in res.reason.lower()


# ─── Test 2: Evidence-Coverage Boost ───

def test_2_evidence_coverage_boost():
    """Test 2: Candidate offering new dimensions/metrics gets higher score than one with already covered metrics."""
    plan = InvestigationPlan(
        question="Analyze drivers",
        query_tasks=[
            QueryTask(
                query_id="q_repeat_metric",
                purpose="Re-check revenue",
                sub_question="Check revenue again",
                required_metrics=["revenue"],
                priority=2,
            ),
            QueryTask(
                query_id="q_new_dimension",
                purpose="Breakdown by product category and channel",
                sub_question="Category and channel distribution",
                required_dimensions=["category", "channel"],
                required_metrics=["order_count"],
                priority=2,
            ),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)
    # Existing evidence already covers 'revenue'
    state.add_evidence(
        EvidenceItem(
            evidence_id="ev_base",
            source_query_id="q_base",
            statement="Total revenue = 1,000,000",
            metric="revenue",
            value=1000000.0,
        )
    )

    selector = QuerySelector()
    res = selector.select_next_query(state)

    assert res.selected_query_id == "q_new_dimension"
    candidate_scores = {c.query_id: c.total_score for c in res.eligible_candidates}
    assert candidate_scores["q_new_dimension"] > candidate_scores["q_repeat_metric"]


# ─── Test 3: Unresolved Questions Boost ───

def test_3_unresolved_questions_boost():
    """Test 3: Task that directly matches an unresolved question receives a score bonus."""
    plan = InvestigationPlan(
        question="Why did revenue drop?",
        query_tasks=[
            QueryTask(
                query_id="q_general",
                purpose="General overview",
                sub_question="What is the total discount?",
                priority=2,
            ),
            QueryTask(
                query_id="q_target",
                purpose="Investigate regional breakdown",
                sub_question="What is the regional revenue drop?",
                priority=2,
            ),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)
    state.unresolved_questions = ["What is the regional revenue drop?"]

    selector = QuerySelector()
    res = selector.select_next_query(state)

    assert res.selected_query_id == "q_target"
    target_eval = next(c for c in res.eligible_candidates if c.query_id == "q_target")
    assert target_eval.unresolved_score > 0
    assert "addresses unresolved" in target_eval.reason.lower()


# ─── Test 4: Redundancy Penalty ───

def test_4_redundancy_penalty():
    """Test 4: Task whose expected evidence is already present in known facts receives a heavy redundancy penalty."""
    plan = InvestigationPlan(
        question="Product investigation",
        query_tasks=[
            QueryTask(
                query_id="q_redundant",
                purpose="Identify top category",
                sub_question="Which category is top?",
                expected_evidence="Electronics is top category",
                can_be_skipped_if_answered=True,
                priority=1,
            ),
            QueryTask(
                query_id="q_fresh",
                purpose="Identify regional decline",
                sub_question="Which region declined most?",
                expected_evidence="Regional decline rates",
                priority=2,
            ),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)
    # Known facts already contain the exact evidence
    state.known_facts = ["Electronics is top category by revenue with 50,000"]

    selector = QuerySelector()
    res = selector.select_next_query(state)

    # Even though q_redundant has higher priority (1 vs 2), q_fresh should win due to redundancy penalty
    assert res.selected_query_id == "q_fresh"
    red_eval = next(c for c in res.eligible_candidates if c.query_id == "q_redundant")
    assert red_eval.is_redundant is True
    assert red_eval.redundancy_penalty > 0


# ─── Test 5: Dependency Satisfaction & Cascading Blocks ───

def test_5_dependency_satisfaction_and_cascading():
    """Test 5: Dependent task is ineligible until dependency succeeds; failure of dependency blocks dependent."""
    plan = InvestigationPlan(
        question="Dependent flow",
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Step 1", sub_question="Step 1", priority=1),
            QueryTask(query_id="q_2", purpose="Step 2", sub_question="Step 2", depends_on=["q_1"], priority=1),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)

    selector = QuerySelector()

    # Initially only Q1 is eligible
    res1 = selector.select_next_query(state)
    assert res1.selected_query_id == "q_1"
    assert len(res1.eligible_candidates) == 1

    # Simulate Q1 failing
    InvestigationEngine.record_execution_result(state, plan.query_tasks[0], sql="SELECT 1", exec_error="Table missing")

    # Q2 should now be BLOCKED and no candidates available
    res2 = selector.select_next_query(state)
    assert res2.selected_task is None
    assert plan.query_tasks[1].status == QueryTaskStatus.BLOCKED


# ─── Test 6: Cost Penalty ───

def test_6_cost_penalty_tie_breaking():
    """Test 6: Between two otherwise equivalent tasks, the one with lower estimated_cost wins."""
    plan = InvestigationPlan(
        question="Cost check",
        query_tasks=[
            QueryTask(
                query_id="q_expensive",
                purpose="Heavy multi-join aggregation",
                sub_question="Heavy query",
                priority=1,
                estimated_cost=4.5,
            ),
            QueryTask(
                query_id="q_cheap",
                purpose="Indexed single-table lookup",
                sub_question="Light query",
                priority=1,
                estimated_cost=1.0,
            ),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)

    selector = QuerySelector()
    res = selector.select_next_query(state)

    assert res.selected_query_id == "q_cheap"
    exp_eval = next(c for c in res.eligible_candidates if c.query_id == "q_expensive")
    assert exp_eval.cost_penalty > 0


# ─── Test 7: Budget Urgency ───

def test_7_budget_urgency_bonus():
    """Test 7: When remaining budget is 1, essential high-priority tasks receive budget urgency bonus."""
    plan = InvestigationPlan(
        question="Budget urgency check",
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Q1", sub_question="Q1", priority=1),
            QueryTask(query_id="q_2", purpose="Q2", sub_question="Q2", priority=1),
        ],
        max_queries=2,
    )
    state = InvestigationEngine.initialize_investigation(plan)
    # 1 query already executed, remaining = 1
    state.queries_executed = 1

    selector = QuerySelector()
    res = selector.select_next_query(state)

    assert res.selected_task is not None
    eval_item = res.eligible_candidates[0]
    assert eval_item.budget_urgency_bonus > 0


# ─── Test 8: Deterministic Tie-Breaking ───

def test_8_deterministic_tie_breaking():
    """Test 8: Exact score and priority ties are broken deterministically by original plan order."""
    plan = InvestigationPlan(
        question="Tie breaking",
        query_tasks=[
            QueryTask(query_id="q_alpha", purpose="Equal task A", sub_question="Same A", priority=1),
            QueryTask(query_id="q_beta", purpose="Equal task B", sub_question="Same B", priority=1),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)

    selector = QuerySelector()
    res = selector.select_next_query(state)

    # First task in plan order (q_alpha) must be selected
    assert res.selected_query_id == "q_alpha"


# ─── Test 9: No Candidates Available ───

def test_9_no_candidates_available():
    """Test 9: Returns None with clear reason when all tasks are completed."""
    plan = InvestigationPlan(
        question="Completed plan",
        query_tasks=[
            QueryTask(query_id="q_done", purpose="Done", sub_question="Done", status=QueryTaskStatus.COMPLETED)
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)
    state.completed_queries.append(
        QueryExecutionRecord(query_id="q_done", status=QueryExecutionStatus.SUCCESS)
    )

    selector = QuerySelector()
    res = selector.select_next_query(state)

    assert res.selected_task is None
    assert "no eligible" in res.reason.lower()


# ─── Test 10: All Candidates Blocked ───

def test_10_all_candidates_blocked():
    """Test 10: When all pending tasks depend on a failed task, selector returns None and reasons clearly."""
    plan = InvestigationPlan(
        question="Blocked plan",
        query_tasks=[
            QueryTask(query_id="q_root", purpose="Root", sub_question="Root", status=QueryTaskStatus.FAILED),
            QueryTask(query_id="q_child1", purpose="Child 1", sub_question="Child 1", depends_on=["q_root"]),
            QueryTask(query_id="q_child2", purpose="Child 2", sub_question="Child 2", depends_on=["q_root"]),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)

    selector = QuerySelector()
    res = selector.select_next_query(state)

    assert res.selected_task is None
    assert plan.query_tasks[1].status == QueryTaskStatus.BLOCKED
    assert plan.query_tasks[2].status == QueryTaskStatus.BLOCKED


# ─── Test 11: Transparent Selection Explanation ───

def test_11_selection_explanation_provenance():
    """Test 11: Full explanation breakdown is available in QuerySelectionResult."""
    plan = InvestigationPlan(
        question="Explanation check",
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Driver check", sub_question="Driver check", priority=1),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)

    res = InvestigationEngine.select_next_task_with_explanation(state)
    assert isinstance(res, QuerySelectionResult)
    assert res.selected_query_id == "q_1"
    assert len(res.eligible_candidates) == 1
    cand = res.eligible_candidates[0]
    assert cand.priority_score > 0
    assert cand.total_score == res.score
    assert len(cand.reason) > 0


# ─── Test 12: Graph-Level End-to-End Selection Integration ───

@pytest.mark.asyncio
async def test_12_graph_query_selection_provenance():
    """Test 12: LangGraph Orchestrator records adaptive query selection metadata in result."""
    agent = AnalystAgent()
    mock_db = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.schema = {"sales": {"columns": [{"name": "revenue", "type": "float"}]}}
    mock_ctx.catalog = None
    mock_ctx.total_tables = 1
    mock_ctx.total_columns = 1

    grounded = MagicMock()
    grounded.schema_text = "sales(revenue)"
    grounded.selected_tables = ["sales"]
    grounded.selected_columns = {"sales": ["revenue"]}
    grounded.retrieved_seed_tables = ["sales"]
    grounded.timings_ms = {}
    grounded.fallback_used = False

    spec = QueryUnderstanding(
        raw_question="Analyze sales",
        intent=IntentType.DATABASE,
        route=ExecutionRoute.DATA_QUERY,
        route_confidence=0.95,
        analysis_type=AnalysisType.EXPLORATORY_ANALYSIS,
        entities=["sales"],
        metrics=["sales.revenue"],
        dimensions=[],
        aggregations=["SUM"],
        confidence=0.95,
        source="deterministic",
    )

    custom_plan = AnalysisPlan(
        question="Analyze sales",
        analysis_goal="Analyze sales",
        tasks=[AnalysisTask(task_id="t1", name="Overall", required_query_tasks=["q_1"])],
        query_tasks=[QueryTask(query_id="q_1", purpose="Total sales", sub_question="Total sales", priority=1)],
    )

    async def fake_generate_sql(question, *args, **kwargs):
        return "SELECT SUM(revenue) FROM sales"

    async def fake_execute_with_repair(question, *args, **kwargs):
        return ([{"total_revenue": 500000.0}], "SELECT SUM(revenue) FROM sales", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock, return_value=("Report", {})):

        res = await agent.ask("Analyze sales", db=mock_db)

    assert res["success"] is True
    assert "query_selections" in res
    assert len(res["query_selections"]) == 1
    sel = res["query_selections"][0]
    assert sel["query_id"] == "q_1"
    assert sel["score"] > 0
    assert len(sel["reason"]) > 0
