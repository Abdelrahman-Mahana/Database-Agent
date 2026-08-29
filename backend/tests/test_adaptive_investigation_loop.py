"""Unit tests for Phase 3: Adaptive Investigation Loop.

Validates:
Test 1 — Single Query execution and completion.
Test 2 — Multiple independent Queries execution without artificial serialization.
Test 3 — Dependency graph scheduling (Q1 first, then Q2 and Q3 become eligible simultaneously).
Test 4 — Failed Query with independent query continuing execution.
Test 5 — Dependency Failure cascading (Q1 fails -> Q2 blocked).
Test 6 — Query budget cap enforcement (max_queries exceeded -> status budget_exhausted).
Test 7 — Protection against duplicate task execution.
Test 8 — Multi-query result preservation across all completed queries.
Test 9 — Partial completion status when some queries succeed and others fail.
Test 10 — Empty plan terminates safely without infinite loops.
Test 11 — LangGraph Orchestrator multi-query execution end-to-end.
Test 12 — Basic evidence extraction and recording.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.analysis.investigation_engine import InvestigationEngine
from app.services.analysis.investigation_models import (
    EvidenceType,
    InvestigationMode,
    InvestigationPlan,
    InvestigationState,
    InvestigationStatus,
    QueryExecutionRecord,
    QueryExecutionStatus,
    QueryTask,
    QueryTaskStatus,
)
from app.agent.orchestration.analyst_agent import AnalystAgent
from app.core.config.settings import settings
from app.agent.semantic.models import ExecutionRoute, IntentType, QueryUnderstanding
from app.utils.helpers import AnalysisType


# ─── Test 1: Single Query ───

def test_1_single_query_execution():
    """Test 1: Plan with 1 QueryTask executes once and transitions to completed."""
    task1 = QueryTask(
        query_id="q_1",
        purpose="Retrieve total revenue",
        sub_question="What is the total revenue?",
        priority=1,
    )
    plan = InvestigationPlan(
        question="What is total revenue?",
        goal="Calculate total revenue",
        query_tasks=[task1],
        max_queries=5,
    )

    state = InvestigationEngine.initialize_investigation(plan)
    assert state.status == InvestigationStatus.RUNNING
    assert state.queries_executed == 0

    # 1. Select next task
    selected = InvestigationEngine.select_next_task(state)
    assert selected is not None
    assert selected.query_id == "q_1"

    # 2. Record execution
    record = InvestigationEngine.record_execution_result(
        state=state,
        task=selected,
        sql="SELECT SUM(total) FROM orders",
        rows=[{"total": 50000.0}],
    )

    assert record.status == QueryExecutionStatus.SUCCESS
    assert state.queries_executed == 1
    assert state.status == InvestigationStatus.COMPLETED
    assert InvestigationEngine.should_continue(state) is False
    assert InvestigationEngine.select_next_task(state) is None


# ─── Test 2: Multiple Independent Queries ───

def test_2_multiple_independent_queries():
    """Test 2: All independent queries execute without artificial dependencies."""
    tasks = [
        QueryTask(query_id="q_1", purpose="Sales by category", sub_question="Category sales", priority=1),
        QueryTask(query_id="q_2", purpose="Sales by region", sub_question="Regional sales", priority=1),
        QueryTask(query_id="q_3", purpose="Sales by month", sub_question="Monthly sales", priority=1),
    ]
    plan = InvestigationPlan(
        question="Provide a multi-dimensional breakdown of sales",
        goal="Breakdown sales",
        query_tasks=tasks,
        max_queries=5,
    )

    state = InvestigationEngine.initialize_investigation(plan)
    executed_ids = []

    while InvestigationEngine.should_continue(state):
        task = InvestigationEngine.select_next_task(state)
        assert task is not None
        executed_ids.append(task.query_id)
        InvestigationEngine.record_execution_result(
            state=state,
            task=task,
            sql=f"SELECT * FROM {task.query_id}",
            rows=[{"metric": 100}],
        )

    assert len(executed_ids) == 3
    assert set(executed_ids) == {"q_1", "q_2", "q_3"}
    assert state.status == InvestigationStatus.COMPLETED
    assert state.queries_executed == 3


# ─── Test 3: Dependency Graph ───

def test_3_dependency_graph_scheduling():
    """Test 3: Q1 executes first, then Q2 and Q3 become eligible simultaneously."""
    q1 = QueryTask(query_id="q_1", purpose="Baseline sales", sub_question="Baseline", priority=1)
    q2 = QueryTask(query_id="q_2", purpose="Product breakdown", sub_question="Products", priority=2, depends_on=["q_1"])
    q3 = QueryTask(query_id="q_3", purpose="Region breakdown", sub_question="Regions", priority=2, depends_on=["q_1"])

    plan = InvestigationPlan(
        question="Why did sales drop?",
        goal="Root cause of sales drop",
        query_tasks=[q1, q2, q3],
        max_queries=5,
    )

    state = InvestigationEngine.initialize_investigation(plan)

    # Initial state: only Q1 is eligible (Q2, Q3 depend on Q1)
    first_task = InvestigationEngine.select_next_task(state)
    assert first_task is not None
    assert first_task.query_id == "q_1"

    # Execute Q1
    InvestigationEngine.record_execution_result(
        state=state,
        task=first_task,
        sql="SELECT baseline",
        rows=[{"baseline": 1000}],
    )

    # Now both Q2 and Q3 must be eligible
    second_task = InvestigationEngine.select_next_task(state)
    assert second_task is not None
    assert second_task.query_id in ("q_2", "q_3")

    InvestigationEngine.record_execution_result(
        state=state,
        task=second_task,
        sql="SELECT breakdown",
        rows=[{"breakdown": 500}],
    )

    # Third task must be the remaining one
    third_task = InvestigationEngine.select_next_task(state)
    assert third_task is not None
    remaining_id = "q_3" if second_task.query_id == "q_2" else "q_2"
    assert third_task.query_id == remaining_id

    InvestigationEngine.record_execution_result(
        state=state,
        task=third_task,
        sql="SELECT breakdown 2",
        rows=[{"breakdown2": 500}],
    )

    assert state.status == InvestigationStatus.COMPLETED
    assert state.queries_executed == 3


# ─── Test 4: Failed Query with Independent Continuation ───

def test_4_failed_query_with_independent_continuation():
    """Test 4: Q1 fails, but independent Q2 still executes and completes with partial status."""
    q1 = QueryTask(query_id="q_1", purpose="Complex metric", sub_question="Complex", priority=1)
    q2 = QueryTask(query_id="q_2", purpose="Simple metric", sub_question="Simple", priority=1)

    plan = InvestigationPlan(
        question="Compare metrics",
        query_tasks=[q1, q2],
        max_queries=5,
    )

    state = InvestigationEngine.initialize_investigation(plan)

    # 1. Select Q1
    t1 = InvestigationEngine.select_next_task(state)
    assert t1.query_id == "q_1"

    # 2. Record failure for Q1
    InvestigationEngine.record_execution_result(
        state=state,
        task=t1,
        sql="SELECT invalid",
        exec_error="Table not found: invalid_table",
    )
    assert t1.status == QueryTaskStatus.FAILED

    # 3. Q2 should still be eligible and runnable
    assert InvestigationEngine.should_continue(state) is True
    t2 = InvestigationEngine.select_next_task(state)
    assert t2 is not None
    assert t2.query_id == "q_2"

    # 4. Record success for Q2
    InvestigationEngine.record_execution_result(
        state=state,
        task=t2,
        sql="SELECT 100 AS simple",
        rows=[{"simple": 100}],
    )

    assert state.status == InvestigationStatus.PARTIAL
    assert state.queries_executed == 2
    assert len(state.completed_queries) == 2
    assert state.completed_queries[0].status == QueryExecutionStatus.FAILED
    assert state.completed_queries[1].status == QueryExecutionStatus.SUCCESS


# ─── Test 5: Dependency Failure (Cascading Block) ───

def test_5_dependency_failure_blocks_dependents():
    """Test 5: Q1 fails -> dependent Q2 is blocked and not executed."""
    q1 = QueryTask(query_id="q_1", purpose="Baseline", sub_question="Baseline", priority=1)
    q2 = QueryTask(query_id="q_2", purpose="Detailed breakdown", sub_question="Details", priority=2, depends_on=["q_1"])

    plan = InvestigationPlan(
        question="Analyze drop",
        query_tasks=[q1, q2],
        max_queries=5,
    )

    state = InvestigationEngine.initialize_investigation(plan)
    t1 = InvestigationEngine.select_next_task(state)
    assert t1.query_id == "q_1"

    # Fail Q1
    InvestigationEngine.record_execution_result(
        state=state,
        task=t1,
        sql="SELECT syntax error",
        exec_error="Syntax error in SQL",
    )

    # Q2 should now be blocked
    assert q2.status == QueryTaskStatus.BLOCKED
    assert InvestigationEngine.select_next_task(state) is None
    assert InvestigationEngine.should_continue(state) is False
    assert state.status == InvestigationStatus.FAILED


# ─── Test 6: Query Budget ───

def test_6_query_budget_enforcement():
    """Test 6: max_queries cap terminates loop with budget_exhausted status."""
    tasks = [
        QueryTask(query_id=f"q_{i}", purpose=f"Task {i}", sub_question=f"Question {i}", priority=i)
        for i in range(1, 6)
    ]
    plan = InvestigationPlan(
        question="Large multi-step query",
        query_tasks=tasks,
        max_queries=2,
    )

    state = InvestigationEngine.initialize_investigation(plan, max_queries=2)

    executed_count = 0
    while InvestigationEngine.should_continue(state):
        task = InvestigationEngine.select_next_task(state)
        assert task is not None
        executed_count += 1
        InvestigationEngine.record_execution_result(
            state=state,
            task=task,
            sql=f"SELECT {task.query_id}",
            rows=[{"res": 1}],
        )

    assert executed_count == 2
    assert state.queries_executed == 2
    assert state.status == InvestigationStatus.BUDGET_EXHAUSTED
    assert InvestigationEngine.should_continue(state) is False


# ─── Test 7: No Duplicate Execution ───

def test_7_no_duplicate_execution():
    """Test 7: Same task is never selected or executed twice."""
    q1 = QueryTask(query_id="q_1", purpose="Unique query", sub_question="Unique", priority=1)
    plan = InvestigationPlan(question="Test question", query_tasks=[q1], max_queries=5)

    state = InvestigationEngine.initialize_investigation(plan)

    t1 = InvestigationEngine.select_next_task(state)
    assert t1 is not None
    assert t1.query_id == "q_1"

    InvestigationEngine.record_execution_result(
        state=state,
        task=t1,
        sql="SELECT 1",
        rows=[{"a": 1}],
    )

    # Next selection must return None
    t2 = InvestigationEngine.select_next_task(state)
    assert t2 is None


# ─── Test 8: Result Preservation ───

def test_8_multi_query_result_preservation():
    """Test 8: Distinct results from all queries are stored without overwriting."""
    q1 = QueryTask(query_id="q_1", purpose="Q1", sub_question="Q1", priority=1)
    q2 = QueryTask(query_id="q_2", purpose="Q2", sub_question="Q2", priority=2)
    q3 = QueryTask(query_id="q_3", purpose="Q3", sub_question="Q3", priority=3)

    plan = InvestigationPlan(
        question="Multi query",
        query_tasks=[q1, q2, q3],
        max_queries=5,
    )

    state = InvestigationEngine.initialize_investigation(plan)

    rows1 = [{"category": "Electronics", "sales": 5000}]
    rows2 = [{"region": "North", "sales": 3000}]
    rows3 = [{"month": "2024-01", "sales": 8000}]

    for task_obj, rows_data in [(q1, rows1), (q2, rows2), (q3, rows3)]:
        t = InvestigationEngine.select_next_task(state)
        assert t.query_id == task_obj.query_id
        InvestigationEngine.record_execution_result(
            state=state,
            task=t,
            sql=f"SELECT * FROM {t.query_id}",
            rows=rows_data,
        )

    # Verify query_results dictionary preserves all 3
    assert len(state.query_results) == 3
    assert state.query_results["q_1"] == rows1
    assert state.query_results["q_2"] == rows2
    assert state.query_results["q_3"] == rows3

    # Verify completed_queries history records
    assert len(state.completed_queries) == 3
    assert state.completed_queries[0].query_id == "q_1"
    assert state.completed_queries[0].rows == rows1
    assert state.completed_queries[1].query_id == "q_2"
    assert state.completed_queries[1].rows == rows2
    assert state.completed_queries[2].query_id == "q_3"
    assert state.completed_queries[2].rows == rows3


# ─── Test 9: Partial Completion Status ───

def test_9_partial_completion_status():
    """Test 9: Q1 completed, Q2 failed, Q3 completed -> final status is partial."""
    q1 = QueryTask(query_id="q_1", purpose="Q1", sub_question="Q1", priority=1)
    q2 = QueryTask(query_id="q_2", purpose="Q2", sub_question="Q2", priority=1)
    q3 = QueryTask(query_id="q_3", purpose="Q3", sub_question="Q3", priority=1)

    plan = InvestigationPlan(
        question="Three-step query",
        query_tasks=[q1, q2, q3],
        max_queries=5,
    )

    state = InvestigationEngine.initialize_investigation(plan)

    # Q1 succeeds
    t1 = InvestigationEngine.select_next_task(state)
    InvestigationEngine.record_execution_result(state, t1, sql="SELECT 1", rows=[{"v": 1}])

    # Q2 fails
    t2 = InvestigationEngine.select_next_task(state)
    InvestigationEngine.record_execution_result(state, t2, sql="SELECT 2", exec_error="Failed query 2")

    # Q3 succeeds
    t3 = InvestigationEngine.select_next_task(state)
    InvestigationEngine.record_execution_result(state, t3, sql="SELECT 3", rows=[{"v": 3}])

    assert state.status == InvestigationStatus.PARTIAL
    assert state.queries_executed == 3
    assert InvestigationEngine.should_continue(state) is False


# ─── Test 10: Empty Plan ───

def test_10_empty_plan_terminates_safely():
    """Test 10: Investigation plan with 0 tasks stops immediately without looping."""
    plan = InvestigationPlan(
        question="Empty question",
        query_tasks=[],
        max_queries=5,
    )

    state = InvestigationEngine.initialize_investigation(plan)
    assert state.status == InvestigationStatus.COMPLETED
    assert InvestigationEngine.select_next_task(state) is None
    assert InvestigationEngine.should_continue(state) is False


# ─── Test 11: LangGraph Multi-Query Orchestration End-to-End ───

@pytest.mark.asyncio
async def test_11_langgraph_multi_query_loop_orchestration():
    """Test 11: LangGraph orchestrator executes a multi-query investigation plan end-to-end."""
    agent = AnalystAgent()
    mock_db = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.schema = {
        "orders": {"columns": [{"name": "total", "type": "float"}, {"name": "region", "type": "varchar"}]},
        "categories": {"columns": [{"name": "cat_name", "type": "varchar"}]},
    }
    mock_ctx.catalog = None
    mock_ctx.total_tables = 2
    mock_ctx.total_columns = 3

    grounded = MagicMock()
    grounded.schema_text = "orders(total, region), categories(cat_name)"
    grounded.selected_tables = ["orders", "categories"]
    grounded.selected_columns = {"orders": ["total", "region"], "categories": ["cat_name"]}
    grounded.retrieved_seed_tables = ["orders", "categories"]
    grounded.timings_ms = {}
    grounded.fallback_used = False

    spec = QueryUnderstanding(
        raw_question="حلل المبيعات عبر المناطق والفئات",
        intent=IntentType.DATABASE,
        route=ExecutionRoute.DATA_QUERY,
        route_confidence=0.95,
        analysis_type=AnalysisType.EXPLORATORY_ANALYSIS,
        entities=["orders", "categories"],
        metrics=["orders.total"],
        dimensions=["orders.region", "categories.cat_name"],
        aggregations=["SUM"],
        confidence=0.95,
        source="deterministic",
    )

    # Multi-query SQL generation responses
    sql_calls = []

    async def fake_generate_sql(question, *args, **kwargs):
        sql_calls.append(question)
        if "منطقة" in question or "region" in question.lower() or len(sql_calls) == 1:
            return "SELECT region, SUM(total) AS rev FROM orders GROUP BY region"
        return "SELECT cat_name, SUM(total) AS rev FROM orders JOIN categories ON 1=1 GROUP BY cat_name"

    async def fake_execute_with_repair(question, *args, **kwargs):
        if "region" in str(kwargs.get("sql", "")).lower():
            return ([{"region": "North", "rev": 5000.0}, {"region": "South", "rev": 4000.0}], "SELECT region...", None, None, [])
        return ([{"cat_name": "Electronics", "rev": 9000.0}], "SELECT cat_name...", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock) as mock_spec_builder, \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock) as mock_ground, \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock) as mock_report:

        mock_spec_builder.return_value = spec
        mock_ground.return_value = grounded
        mock_report.return_value = ("تقرير تحليلي شامل للمبيعات عبر المناطق والفئات.", {"type": "bar"})

        res = await agent.ask("حلل المبيعات عبر المناطق والفئات", db=mock_db)

    assert res["success"] is True
    assert "investigation_status" in res
    assert res["investigation_status"] in ("completed", "partial")
    assert "completed_queries" in res
    assert len(res["completed_queries"]) >= 1
    assert "query_results" in res
    assert len(res["results"]) > 0


# ─── Test 12: Basic Evidence Extraction ───

def test_12_basic_evidence_extraction():
    """Test 12: Basic evidence items (numeric metrics, row counts) are extracted upon execution."""
    task = QueryTask(
        query_id="q_1",
        purpose="Retrieve monthly average",
        sub_question="What is the average?",
        priority=1,
    )
    plan = InvestigationPlan(
        question="Average check",
        query_tasks=[task],
        max_queries=5,
    )

    state = InvestigationEngine.initialize_investigation(plan)
    t = InvestigationEngine.select_next_task(state)

    InvestigationEngine.record_execution_result(
        state=state,
        task=t,
        sql="SELECT AVG(amount) AS avg_amount, COUNT(*) AS cnt FROM orders",
        rows=[{"avg_amount": 250.5, "cnt": 100}],
    )

    assert len(state.evidence) >= 1
    ev_types = [e.evidence_type for e in state.evidence]
    assert EvidenceType.NUMERIC in ev_types

    numeric_ev = [e for e in state.evidence if e.evidence_type == EvidenceType.NUMERIC]
    metrics_found = {e.metric: e.value for e in numeric_ev}
    assert metrics_found.get("avg_amount") == 250.5
    assert metrics_found.get("cnt") == 100
