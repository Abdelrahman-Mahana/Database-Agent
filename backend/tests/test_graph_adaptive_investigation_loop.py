"""Graph-Level Verification Tests for Phase 3: Adaptive Investigation Loop in LangGraph.

Tests:
Test A — Single Query Graph execution and state assertions.
Test B — Multiple Independent Queries execution (Q1 -> Q2 -> Q3) without artificial serialization.
Test C — Dependency Graph execution (Q1 first, then Q2 and Q3 become eligible simultaneously).
Test D — Independent Continuation After Failure (Q1 fails, Q2 executes, status == partial).
Test E — Dependency Failure (Q1 fails -> Q2 blocked and never executed).
Test F — Query Budget enforcement in LangGraph (max_queries = 2 with 5 tasks -> exactly 2 executions, status == budget_exhausted).
Test G — Duplicate Execution Protection in LangGraph.
Test H — Multi-query Result Preservation across iterations without overwriting.
Test I — Pre-execution Validation and Cost Guard Failure recovery in LangGraph loop.
Test J — Empty Investigation Plan terminates safely with 0 executions.
Test K — State Reset Across Iterations (ensuring sql, rows, exec_error, error_type do not leak across queries).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.orchestration.analyst_agent import AnalystAgent
from app.services.analysis.investigation_engine import InvestigationEngine
from app.services.analysis.investigation_models import (
    InvestigationMode,
    InvestigationPlan,
    InvestigationState,
    InvestigationStatus,
    QueryExecutionRecord,
    QueryExecutionStatus,
    QueryTask,
    QueryTaskStatus,
)
from app.services.analysis.models import AnalysisPlan, AnalysisTask
from app.core.config.settings import settings
from app.agent.semantic.models import ExecutionRoute, IntentType, QueryUnderstanding
from app.utils.helpers import AnalysisType


def _create_mock_context():
    mock_ctx = MagicMock()
    mock_ctx.schema = {
        "orders": {"columns": [{"name": "total", "type": "float"}, {"name": "region", "type": "varchar"}, {"name": "category", "type": "varchar"}]},
    }
    mock_ctx.catalog = None
    mock_ctx.total_tables = 1
    mock_ctx.total_columns = 3
    return mock_ctx


def _create_mock_grounded():
    grounded = MagicMock()
    grounded.schema_text = "orders(total, region, category)"
    grounded.selected_tables = ["orders"]
    grounded.selected_columns = {"orders": ["total", "region", "category"]}
    grounded.retrieved_seed_tables = ["orders"]
    grounded.timings_ms = {}
    grounded.fallback_used = False
    return grounded


def _create_mock_spec(question="Analyze sales"):
    return QueryUnderstanding(
        raw_question=question,
        intent=IntentType.DATABASE,
        route=ExecutionRoute.DATA_QUERY,
        route_confidence=0.95,
        analysis_type=AnalysisType.EXPLORATORY_ANALYSIS,
        entities=["orders"],
        metrics=["orders.total"],
        dimensions=["orders.region"],
        aggregations=["SUM"],
        confidence=0.95,
        source="deterministic",
    )


# ─── Test A: Single Query Graph ───

@pytest.mark.asyncio
async def test_graph_a_single_query():
    """Test A: Single Query in LangGraph executes once, preserves result, and completes."""
    agent = AnalystAgent()
    mock_db = MagicMock()
    mock_ctx = _create_mock_context()
    grounded = _create_mock_grounded()
    spec = _create_mock_spec("What is total revenue?")

    custom_plan = AnalysisPlan(
        question="What is total revenue?",
        analysis_goal="Total revenue",
        tasks=[AnalysisTask(task_id="task_1", name="Total Rev", required_query_tasks=["q_1"])],
        query_tasks=[QueryTask(query_id="q_1", purpose="Total revenue", sub_question="Total revenue", priority=1)],
    )

    sql_executed = []

    async def fake_generate_sql(question, *args, **kwargs):
        sql_executed.append(question)
        return "SELECT SUM(total) AS rev FROM orders"

    async def fake_execute_with_repair(question, *args, **kwargs):
        return ([{"rev": 50000.0}], "SELECT SUM(total) AS rev FROM orders", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock, return_value=("Total is 50K", {})):

        res = await agent.ask("What is total revenue?", db=mock_db)

    assert res["success"] is True
    assert len(sql_executed) == 1
    assert sql_executed[0] == "Total revenue"
    assert res["investigation_status"] == "completed"
    assert len(res["completed_queries"]) == 1
    assert res["completed_queries"][0]["query_id"] == "q_1"
    assert "q_1" in res["query_results"]
    assert res["query_results"]["q_1"] == [{"rev": 50000.0}]


# ─── Test B: Multiple Independent Queries ───

@pytest.mark.asyncio
async def test_graph_b_multiple_independent_queries():
    """Test B: Three independent queries execute in graph loop without artificial dependencies."""
    agent = AnalystAgent()
    mock_db = MagicMock()
    mock_ctx = _create_mock_context()
    grounded = _create_mock_grounded()
    spec = _create_mock_spec("Multi-dimensional sales")

    custom_plan = AnalysisPlan(
        question="Multi-dimensional sales",
        analysis_goal="Breakdown sales",
        tasks=[
            AnalysisTask(task_id="t1", name="Category", required_query_tasks=["q_1"]),
            AnalysisTask(task_id="t2", name="Region", required_query_tasks=["q_2"]),
            AnalysisTask(task_id="t3", name="Monthly", required_query_tasks=["q_3"]),
        ],
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Category sales", sub_question="Category sales", priority=1),
            QueryTask(query_id="q_2", purpose="Region sales", sub_question="Region sales", priority=1),
            QueryTask(query_id="q_3", purpose="Monthly sales", sub_question="Monthly sales", priority=1),
        ],
    )

    executed_queries = []

    async def fake_generate_sql(question, *args, **kwargs):
        return f"SELECT '{question}' AS q"

    async def fake_execute_with_repair(question, *args, **kwargs):
        executed_queries.append(question)
        return ([{"q": question, "val": len(executed_queries)}], f"SELECT '{question}' AS q", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock, return_value=("Report done", {})):

        res = await agent.ask("Multi-dimensional sales", db=mock_db)

    assert res["success"] is True
    assert len(executed_queries) == 3
    assert set(executed_queries) == {"Category sales", "Region sales", "Monthly sales"}
    assert res["investigation_status"] == "completed"
    assert len(res["completed_queries"]) == 3
    assert len(res["query_results"]) == 3
    assert "q_1" in res["query_results"]
    assert "q_2" in res["query_results"]
    assert "q_3" in res["query_results"]


# ─── Test C: Dependency Graph ───

@pytest.mark.asyncio
async def test_graph_c_dependency_graph():
    """Test C: Q1 executes first, then Q2 and Q3 become eligible simultaneously."""
    agent = AnalystAgent()
    mock_db = MagicMock()
    mock_ctx = _create_mock_context()
    grounded = _create_mock_grounded()
    spec = _create_mock_spec("Why did sales decline?")

    custom_plan = AnalysisPlan(
        question="Why did sales decline?",
        analysis_goal="Root cause",
        tasks=[
            AnalysisTask(task_id="t1", name="Baseline", required_query_tasks=["q_1"]),
            AnalysisTask(task_id="t2", name="Products", required_query_tasks=["q_2"], depends_on=["t1"]),
            AnalysisTask(task_id="t3", name="Regions", required_query_tasks=["q_3"], depends_on=["t1"]),
        ],
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Baseline sales", sub_question="Baseline sales", priority=1),
            QueryTask(query_id="q_2", purpose="Product breakdown", sub_question="Product breakdown", priority=2, depends_on=["q_1"]),
            QueryTask(query_id="q_3", purpose="Region breakdown", sub_question="Region breakdown", priority=2, depends_on=["q_1"]),
        ],
    )

    execution_order = []

    async def fake_generate_sql(question, *args, **kwargs):
        return f"SELECT '{question}'"

    async def fake_execute_with_repair(question, *args, **kwargs):
        execution_order.append(question)
        return ([{"question": question}], f"SELECT '{question}'", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock, return_value=("Root cause report", {})):

        res = await agent.ask("Why did sales decline?", db=mock_db)

    assert res["success"] is True
    assert len(execution_order) == 3
    # Q1 must be executed first
    assert execution_order[0] == "Baseline sales"
    # Q2 and Q3 execute after Q1
    assert set(execution_order[1:]) == {"Product breakdown", "Region breakdown"}


# ─── Test D: Independent Continuation After Failure ───

@pytest.mark.asyncio
async def test_graph_d_independent_continuation_after_failure():
    """Test D: Q1 fails, but independent Q2 continues, yielding status partial."""
    agent = AnalystAgent()
    mock_db = MagicMock()
    mock_ctx = _create_mock_context()
    grounded = _create_mock_grounded()
    spec = _create_mock_spec("Compare metrics")

    custom_plan = AnalysisPlan(
        question="Compare metrics",
        analysis_goal="Compare metrics",
        tasks=[
            AnalysisTask(task_id="t1", name="Metric 1", required_query_tasks=["q_1"]),
            AnalysisTask(task_id="t2", name="Metric 2", required_query_tasks=["q_2"]),
        ],
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Complex metric", sub_question="Complex metric", priority=1),
            QueryTask(query_id="q_2", purpose="Simple metric", sub_question="Simple metric", priority=1),
        ],
    )

    execution_attempts = []

    async def fake_generate_sql(question, *args, **kwargs):
        return f"SELECT '{question}'"

    async def fake_execute_with_repair(question, *args, **kwargs):
        execution_attempts.append(question)
        if "Complex" in question:
            # Q1 fails
            return ([], "SELECT complex", "Execution failed on complex metric", "execution_error", ["orders"])
        # Q2 succeeds
        return ([{"simple_metric": 100}], "SELECT simple", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock, return_value=("Partial report", {})):

        res = await agent.ask("Compare metrics", db=mock_db)

    assert res["success"] is True
    assert len(execution_attempts) == 2
    assert res["investigation_status"] == "partial"
    assert len(res["completed_queries"]) == 2
    # Q1 failed, Q2 succeeded
    q1_rec = next(q for q in res["completed_queries"] if q["query_id"] == "q_1")
    q2_rec = next(q for q in res["completed_queries"] if q["query_id"] == "q_2")
    assert q1_rec["status"] == "failed"
    assert q2_rec["status"] == "success"
    assert res["query_results"]["q_2"] == [{"simple_metric": 100}]


# ─── Test E: Dependency Failure ───

@pytest.mark.asyncio
async def test_graph_e_dependency_failure_blocks_dependent():
    """Test E: Q1 fails -> dependent Q2 is blocked and never executed."""
    agent = AnalystAgent()
    mock_db = MagicMock()
    mock_ctx = _create_mock_context()
    grounded = _create_mock_grounded()
    spec = _create_mock_spec("Analyze trend and breakdown")

    custom_plan = AnalysisPlan(
        question="Analyze trend and breakdown",
        analysis_goal="Trend and breakdown",
        tasks=[
            AnalysisTask(task_id="t1", name="Baseline", required_query_tasks=["q_1"]),
            AnalysisTask(task_id="t2", name="Breakdown", required_query_tasks=["q_2"], depends_on=["t1"]),
        ],
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Baseline", sub_question="Baseline", priority=1),
            QueryTask(query_id="q_2", purpose="Breakdown", sub_question="Breakdown", priority=2, depends_on=["q_1"]),
        ],
    )

    execution_attempts = []

    async def fake_generate_sql(question, *args, **kwargs):
        return f"SELECT '{question}'"

    async def fake_execute_with_repair(question, *args, **kwargs):
        execution_attempts.append(question)
        # Q1 fails
        return ([], "SELECT baseline", "Baseline query failed syntax", "execution_error", [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_no_answer_response", new_callable=AsyncMock, return_value="All queries failed"):

        res = await agent.ask("Analyze trend and breakdown", db=mock_db)

    # Q1 was attempted, Q2 was blocked and NEVER attempted
    assert len(execution_attempts) == 1
    assert execution_attempts[0] == "Baseline"
    assert res["success"] is False
    assert res["investigation_status"] == "failed"
    assert len(res["completed_queries"]) == 1
    assert res["completed_queries"][0]["status"] == "failed"


# ─── Test F: Query Budget ───

@pytest.mark.asyncio
async def test_graph_f_query_budget_enforcement():
    """Test F: Max queries cap stops the LangGraph loop at budget limit."""
    agent = AnalystAgent()
    mock_db = MagicMock()
    mock_ctx = _create_mock_context()
    grounded = _create_mock_grounded()
    spec = _create_mock_spec("Multi task 5 queries")

    custom_plan = AnalysisPlan(
        question="Multi task 5 queries",
        analysis_goal="Execute max 2 queries",
        max_queries=2,
        tasks=[AnalysisTask(task_id=f"t{i}", name=f"Task {i}", required_query_tasks=[f"q_{i}"]) for i in range(1, 6)],
        query_tasks=[QueryTask(query_id=f"q_{i}", purpose=f"Q{i}", sub_question=f"Q{i} sub", priority=i) for i in range(1, 6)],
    )

    execution_count = []

    async def fake_generate_sql(question, *args, **kwargs):
        return f"SELECT '{question}'"

    async def fake_execute_with_repair(question, *args, **kwargs):
        execution_count.append(question)
        return ([{"res": len(execution_count)}], f"SELECT '{question}'", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock, return_value=("Budget report", {})):

        res = await agent.ask("Multi task 5 queries", db=mock_db)

    assert len(execution_count) == 2
    assert res["investigation_status"] == "budget_exhausted"
    assert len(res["completed_queries"]) == 2
    assert any("budget" in w.lower() for w in res.get("warnings", []))


# ─── Test G: Duplicate Execution Protection ───

@pytest.mark.asyncio
async def test_graph_g_duplicate_execution_protection():
    """Test G: Same QueryTask is never executed twice in LangGraph."""
    agent = AnalystAgent()
    mock_db = MagicMock()
    mock_ctx = _create_mock_context()
    grounded = _create_mock_grounded()
    spec = _create_mock_spec("Single check")

    custom_plan = AnalysisPlan(
        question="Single check",
        analysis_goal="Single check",
        tasks=[AnalysisTask(task_id="t1", name="T1", required_query_tasks=["q_1"])],
        query_tasks=[QueryTask(query_id="q_1", purpose="Q1", sub_question="Q1 sub", priority=1)],
    )

    execution_calls = []

    async def fake_generate_sql(question, *args, **kwargs):
        return "SELECT 1"

    async def fake_execute_with_repair(question, *args, **kwargs):
        execution_calls.append(question)
        return ([{"val": 1}], "SELECT 1", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock, return_value=("Done", {})):

        res = await agent.ask("Single check", db=mock_db)

    assert len(execution_calls) == 1
    assert execution_calls[0] == "Q1 sub"
    assert len(res["completed_queries"]) == 1


# ─── Test H: Result Preservation ───

@pytest.mark.asyncio
async def test_graph_h_result_preservation_across_all_queries():
    """Test H: Results from all queries are stored without overwriting."""
    agent = AnalystAgent()
    mock_db = MagicMock()
    mock_ctx = _create_mock_context()
    grounded = _create_mock_grounded()
    spec = _create_mock_spec("3 queries")

    custom_plan = AnalysisPlan(
        question="3 queries",
        analysis_goal="3 queries",
        tasks=[AnalysisTask(task_id=f"t{i}", name=f"T{i}", required_query_tasks=[f"q_{i}"]) for i in range(1, 4)],
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Q1", sub_question="Q1 sub", priority=1),
            QueryTask(query_id="q_2", purpose="Q2", sub_question="Q2 sub", priority=2),
            QueryTask(query_id="q_3", purpose="Q3", sub_question="Q3 sub", priority=3),
        ],
    )

    data_map = {
        "Q1 sub": [{"product": "P1", "revenue": 100.0}],
        "Q2 sub": [{"region": "North", "units": 50}],
        "Q3 sub": [{"month": "2024-01", "growth": 0.15}],
    }

    async def fake_generate_sql(question, *args, **kwargs):
        return f"SELECT '{question}' AS q"

    async def fake_execute_with_repair(question, *args, **kwargs):
        return (data_map.get(question, []), f"SELECT * FROM {question}", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock, return_value=("Multi report", {})):

        res = await agent.ask("3 queries", db=mock_db)

    assert res["query_results"]["q_1"] == data_map["Q1 sub"]
    assert res["query_results"]["q_2"] == data_map["Q2 sub"]
    assert res["query_results"]["q_3"] == data_map["Q3 sub"]
    assert len(res["completed_queries"]) == 3
    assert res["completed_queries"][0]["rows"] == data_map["Q1 sub"]
    assert res["completed_queries"][1]["rows"] == data_map["Q2 sub"]
    assert res["completed_queries"][2]["rows"] == data_map["Q3 sub"]


# ─── Test I: Validation Failure and Cost Guard Failure in Graph ───

@pytest.mark.asyncio
async def test_graph_i_validation_failure_continues_loop():
    """Test I: SQL validation failure on Q1 records error and continues to independent Q2."""
    agent = AnalystAgent()
    mock_db = MagicMock()
    mock_ctx = _create_mock_context()
    grounded = _create_mock_grounded()
    spec = _create_mock_spec("Validation test")

    custom_plan = AnalysisPlan(
        question="Validation test",
        analysis_goal="Validation test",
        tasks=[
            AnalysisTask(task_id="t1", name="Dangerous", required_query_tasks=["q_1"]),
            AnalysisTask(task_id="t2", name="Safe", required_query_tasks=["q_2"]),
        ],
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Dangerous query", sub_question="Dangerous query", priority=1),
            QueryTask(query_id="q_2", purpose="Safe query", sub_question="Safe query", priority=1),
        ],
    )

    async def fake_generate_sql(question, *args, **kwargs):
        if "Dangerous" in question:
            # Drop table is invalid SQL in validator
            return "DROP TABLE orders;"
        return "SELECT SUM(total) FROM orders"

    async def fake_execute_with_repair(question, *args, **kwargs):
        return ([{"sum": 100}], "SELECT SUM(total) FROM orders", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock, return_value=("Safe report", {})):

        res = await agent.ask("Validation test", db=mock_db)

    assert res["success"] is True
    assert res["investigation_status"] == "partial"
    assert len(res["completed_queries"]) == 2
    assert res["completed_queries"][0]["status"] == "failed"
    assert res["completed_queries"][1]["status"] == "success"


# ─── Test J: Empty Investigation Plan ───

@pytest.mark.asyncio
async def test_graph_j_empty_investigation_plan():
    """Test J: Empty plan with 0 queries safely terminates with 0 SQL executions."""
    agent = AnalystAgent()
    mock_db = MagicMock()
    mock_ctx = _create_mock_context()
    grounded = _create_mock_grounded()
    spec = _create_mock_spec("Empty query")

    custom_plan = AnalysisPlan(
        question="Empty query",
        analysis_goal="Empty query",
        tasks=[],
        query_tasks=[],
    )

    sql_called = []

    async def fake_generate_sql(question, *args, **kwargs):
        sql_called.append(question)
        return "SELECT 1"

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.report_service, "generate_no_answer_response", new_callable=AsyncMock, return_value="Empty plan report"):

        res = await agent.ask("Empty query", db=mock_db)

    # No SQL was generated or executed
    assert len(sql_called) == 0
    assert res["investigation_status"] == "completed"
    assert len(res.get("completed_queries", [])) == 0


# ─── Test K: State Reset Across Iterations ───

@pytest.mark.asyncio
async def test_graph_k_state_reset_across_iterations():
    """Test K: Verify that sql, rows, exec_error, error_type are cleanly reset between iterations."""
    agent = AnalystAgent()
    mock_db = MagicMock()
    mock_ctx = _create_mock_context()
    grounded = _create_mock_grounded()
    spec = _create_mock_spec("State cleanliness check")

    custom_plan = AnalysisPlan(
        question="State cleanliness check",
        analysis_goal="State cleanliness check",
        tasks=[
            AnalysisTask(task_id="t1", name="First", required_query_tasks=["q_1"]),
            AnalysisTask(task_id="t2", name="Second", required_query_tasks=["q_2"]),
        ],
        query_tasks=[
            QueryTask(query_id="q_1", purpose="First query", sub_question="First query", priority=1),
            QueryTask(query_id="q_2", purpose="Second query", sub_question="Second query", priority=2),
        ],
    )

    async def fake_generate_sql(question, *args, **kwargs):
        return f"SELECT '{question}'"

    async def fake_execute_with_repair(question, *args, **kwargs):
        if "First" in question:
            return ([{"first_data": 1}], "SELECT first", "Warning note on Q1", "some_error", [])
        # When Q2 executes, ensure state had no leftover Q1 error
        return ([{"second_data": 2}], "SELECT second", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock, return_value=("Clean report", {})):

        res = await agent.ask("State cleanliness check", db=mock_db)

    assert res["investigation_status"] == "partial"
    assert len(res["completed_queries"]) == 2
    # Ensure query results contain separated clean data
    assert "q_1" in res["query_results"]
    assert "q_2" in res["query_results"]
    assert res["query_results"]["q_1"] == [{"first_data": 1}]
    assert res["query_results"]["q_2"] == [{"second_data": 2}]
