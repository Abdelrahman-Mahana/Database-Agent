"""Unit and Integration Tests for Phase 4: Evidence Management + Investigation Progress Evaluation.

Tests:
Test A — Aggregate evidence extraction (single-row metrics).
Test B — Comparison evidence extraction (deltas, percentage differences).
Test C — Empty result handling (0 rows produces observation without failure).
Test D — Multiple evidence items from the same query.
Test E — Grounded evidence provenance tracking (source_query_id).
Test F — Evidence coverage metric calculation.
Test G — Completed investigation evaluation.
Test H — Partial investigation evaluation (some tasks failed/blocked).
Test I — Pending / Running investigation evaluation.
Test J — Robust handling of nulls, missing columns, and numeric strings.
Test K — Strict grounding (no hallucinated evidence).
Test L — Graph-level integration of evidence and progress in AnalystAgent output.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.analysis.evidence_manager import (
    EvidenceManager,
    InvestigationProgress,
    InvestigationProgressEvaluator,
)
from app.services.analysis.investigation_engine import InvestigationEngine
from app.services.analysis.investigation_models import (
    EvidenceItem,
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
from app.services.analysis.models import AnalysisPlan, AnalysisTask
from app.agent.orchestration.analyst_agent import AnalystAgent
from app.core.config.settings import settings
from app.agent.semantic.models import ExecutionRoute, IntentType, QueryUnderstanding
from app.utils.text_processor import AnalysisType


# ─── Test A: Aggregate Evidence Extraction ───

def test_a_aggregate_evidence_extraction():
    """Test A: Extract deterministic aggregate evidence from single-row query result."""
    task = QueryTask(
        query_id="q_agg",
        purpose="Compute total sales and average order value",
        sub_question="What is total revenue and average?",
    )
    record = QueryExecutionRecord(
        query_id="q_agg",
        purpose=task.purpose,
        sub_question=task.sub_question,
        sql="SELECT SUM(revenue) AS total_revenue, AVG(revenue) AS avg_order_val FROM sales",
        status=QueryExecutionStatus.SUCCESS,
        row_count=1,
        rows=[{"total_revenue": 1250000.0, "avg_order_val": 250.0}],
    )

    evidence = EvidenceManager.extract_evidence(record, task)
    assert len(evidence) == 2

    rev_ev = next(e for e in evidence if e.metric == "total_revenue")
    assert rev_ev.evidence_type == EvidenceType.NUMERIC
    assert rev_ev.value == 1250000.0
    assert "1,250,000" in rev_ev.statement
    assert rev_ev.source_query_id == "q_agg"
    assert rev_ev.verified is True

    avg_ev = next(e for e in evidence if e.metric == "avg_order_val")
    assert avg_ev.evidence_type == EvidenceType.NUMERIC
    assert avg_ev.value == 250.0
    assert "250" in avg_ev.statement
    assert avg_ev.source_query_id == "q_agg"


# ─── Test B: Comparison Evidence Extraction ───

def test_b_comparison_evidence_extraction():
    """Test B: Extract comparison evidence with delta and percentage change from two-period rows."""
    task = QueryTask(
        query_id="q_comp",
        purpose="Compare 2024 and 2025 revenue",
        sub_question="How does 2025 compare to 2024?",
    )
    record = QueryExecutionRecord(
        query_id="q_comp",
        purpose=task.purpose,
        sub_question=task.sub_question,
        sql="SELECT year, SUM(revenue) AS revenue FROM sales GROUP BY year ORDER BY year",
        status=QueryExecutionStatus.SUCCESS,
        row_count=2,
        rows=[
            {"year": "2024", "revenue": 1000.0},
            {"year": "2025", "revenue": 800.0},
        ],
    )

    evidence = EvidenceManager.extract_evidence(record, task)
    assert len(evidence) >= 1

    comp_ev = next(e for e in evidence if e.evidence_type == EvidenceType.COMPARISON)
    assert comp_ev.metric == "revenue"
    assert comp_ev.source_query_id == "q_comp"
    assert comp_ev.value["base"] == 1000.0
    assert comp_ev.value["target"] == 800.0
    assert comp_ev.value["delta"] == -200.0
    assert comp_ev.value["pct_change"] == -20.0
    assert "20.0% lower than" in comp_ev.statement
    assert "2025" in comp_ev.statement and "2024" in comp_ev.statement


# ─── Test C: Empty Result Handling ───

def test_c_empty_result_handling():
    """Test C: Empty query execution produces observation evidence without failure."""
    task = QueryTask(
        query_id="q_empty",
        purpose="Find returned items with defect code X",
        sub_question="How many defects with code X?",
    )
    record = QueryExecutionRecord(
        query_id="q_empty",
        purpose=task.purpose,
        sub_question=task.sub_question,
        sql="SELECT * FROM returns WHERE defect_code = 'X'",
        status=QueryExecutionStatus.EMPTY,
        row_count=0,
        rows=[],
    )

    evidence = EvidenceManager.extract_evidence(record, task)
    assert len(evidence) == 1

    empty_ev = evidence[0]
    assert empty_ev.evidence_type == EvidenceType.OBSERVATION
    assert empty_ev.source_query_id == "q_empty"
    assert empty_ev.value == 0
    assert "No matching records were found" in empty_ev.statement


# ─── Test D: Multiple Evidence from Same Query ───

def test_d_multiple_evidence_from_same_query():
    """Test D: Multi-metric result extracts distinct evidence for each column."""
    task = QueryTask(query_id="q_multi", purpose="Metrics summary", sub_question="Summary")
    record = QueryExecutionRecord(
        query_id="q_multi",
        sql="SELECT total_sales, total_margin, customer_count FROM summary",
        status=QueryExecutionStatus.SUCCESS,
        row_count=1,
        rows=[{"total_sales": 50000.0, "total_margin": 15000.0, "customer_count": 300}],
    )

    evidence = EvidenceManager.extract_evidence(record, task)
    assert len(evidence) == 3

    metrics_extracted = {e.metric: e.value for e in evidence}
    assert metrics_extracted == {
        "total_sales": 50000.0,
        "total_margin": 15000.0,
        "customer_count": 300.0,
    }
    for e in evidence:
        assert e.source_query_id == "q_multi"


# ─── Test E: Evidence Provenance ───

def test_e_evidence_provenance_tracking():
    """Test E: Every evidence item maintains verifiable link to its originating query_id."""
    plan = InvestigationPlan(
        question="Analyze metrics",
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Q1", sub_question="Q1"),
            QueryTask(query_id="q_2", purpose="Q2", sub_question="Q2"),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)

    t1 = InvestigationEngine.select_next_task(state)
    InvestigationEngine.record_execution_result(state, t1, sql="SELECT 100 AS m1", rows=[{"m1": 100.0}])

    t2 = InvestigationEngine.select_next_task(state)
    InvestigationEngine.record_execution_result(state, t2, sql="SELECT 200 AS m2", rows=[{"m2": 200.0}])

    assert len(state.evidence) >= 2
    q1_evidence = [e for e in state.evidence if e.source_query_id == "q_1"]
    q2_evidence = [e for e in state.evidence if e.source_query_id == "q_2"]

    assert len(q1_evidence) >= 1
    assert q1_evidence[0].value == 100.0
    assert len(q2_evidence) >= 1
    assert q2_evidence[0].value == 200.0


# ─── Test F: Evidence Coverage ───

def test_f_evidence_coverage_calculation():
    """Test F: Evidence coverage is correctly calculated as ratio of completed tasks to total tasks."""
    plan = InvestigationPlan(
        question="4-step analysis",
        query_tasks=[
            QueryTask(query_id=f"q_{i}", purpose=f"Task {i}", sub_question=f"Question {i}")
            for i in range(1, 5)
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)

    # Initial state: 0/4 completed
    prog_init = InvestigationProgressEvaluator.evaluate_progress(state)
    assert prog_init.evidence_coverage == 0.0
    assert len(prog_init.pending_tasks) == 4

    # Execute 3 tasks
    for i in range(1, 4):
        t = InvestigationEngine.select_next_task(state)
        InvestigationEngine.record_execution_result(state, t, sql=f"SELECT {i}", rows=[{"val": i}])

    prog_3 = InvestigationProgressEvaluator.evaluate_progress(state)
    assert prog_3.evidence_coverage == 0.75
    assert len(prog_3.completed_tasks) == 3
    assert len(prog_3.pending_tasks) == 1
    assert prog_3.pending_tasks == ["q_4"]


# ─── Test G: Completed Investigation Progress ───

def test_g_completed_investigation_progress():
    """Test G: All tasks completed yields status COMPLETED, coverage 1.0, and 0 unresolved questions."""
    plan = InvestigationPlan(
        question="Complete check",
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Q1", sub_question="Q1 question"),
            QueryTask(query_id="q_2", purpose="Q2", sub_question="Q2 question"),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)

    for _ in range(2):
        t = InvestigationEngine.select_next_task(state)
        InvestigationEngine.record_execution_result(state, t, sql="SELECT 1", rows=[{"col": 10}])

    prog = InvestigationProgressEvaluator.evaluate_progress(state)
    assert prog.completion_status == InvestigationStatus.COMPLETED
    assert prog.evidence_coverage == 1.0
    assert len(prog.completed_tasks) == 2
    assert len(prog.unresolved_questions) == 0
    assert len(state.known_facts) >= 2


# ─── Test H: Partial Investigation Progress ───

def test_h_partial_investigation_progress():
    """Test H: When a task fails and no runnable tasks remain, progress is PARTIAL."""
    plan = InvestigationPlan(
        question="Partial test",
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Q1", sub_question="Q1"),
            QueryTask(query_id="q_2", purpose="Q2", sub_question="Q2"),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)

    t1 = InvestigationEngine.select_next_task(state)
    InvestigationEngine.record_execution_result(state, t1, sql="SELECT 1", rows=[{"v": 10}])

    t2 = InvestigationEngine.select_next_task(state)
    InvestigationEngine.record_execution_result(state, t2, sql="SELECT 2", exec_error="Database table missing")

    prog = InvestigationProgressEvaluator.evaluate_progress(state)
    assert prog.completion_status == InvestigationStatus.PARTIAL
    assert prog.evidence_coverage == 0.5
    assert len(prog.completed_tasks) == 1
    assert len(prog.failed_tasks) == 1
    assert "q_2" in prog.failed_tasks


# ─── Test I: Pending / Running Investigation Progress ───

def test_i_pending_investigation_progress():
    """Test I: While eligible tasks remain, progress evaluates to RUNNING with unresolved questions."""
    plan = InvestigationPlan(
        question="Pending check",
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Q1", sub_question="How much revenue?"),
            QueryTask(query_id="q_2", purpose="Q2", sub_question="What is the regional breakdown?"),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)

    # Run only Q1
    t1 = InvestigationEngine.select_next_task(state)
    InvestigationEngine.record_execution_result(state, t1, sql="SELECT 100", rows=[{"revenue": 100}])

    prog = InvestigationProgressEvaluator.evaluate_progress(state)
    assert prog.completion_status == InvestigationStatus.RUNNING
    assert prog.evidence_coverage == 0.5
    assert "What is the regional breakdown?" in prog.unresolved_questions
    assert "How much revenue?" not in prog.unresolved_questions


# ─── Test J: Null, Missing, and Dirty Values Handling ───

def test_j_null_missing_and_dirty_values_handling():
    """Test J: EvidenceManager safely extracts evidence from numeric strings, nulls, and mixed types."""
    task = QueryTask(query_id="q_dirty", purpose="Dirty data check", sub_question="Dirty")
    record = QueryExecutionRecord(
        query_id="q_dirty",
        status=QueryExecutionStatus.SUCCESS,
        row_count=1,
        rows=[{
            "formatted_revenue": "1,250,000.50",
            "growth_pct": "15.5%",
            "null_column": None,
            "bool_column": True,
            "text_desc": "Active Status",
            "integer_count": 42,
        }],
    )

    evidence = EvidenceManager.extract_evidence(record, task)
    assert len(evidence) >= 3

    metrics_extracted = {e.metric: e.value for e in evidence}
    assert metrics_extracted["formatted_revenue"] == 1250000.50
    assert metrics_extracted["growth_pct"] == 15.5
    assert metrics_extracted["integer_count"] == 42.0

    # Ensure null and boolean were safely ignored from numeric extraction
    assert "null_column" not in metrics_extracted
    assert "bool_column" not in metrics_extracted


# ─── Test K: Strict Grounding (No Hallucinated Evidence) ───

def test_k_no_hallucinated_evidence():
    """Test K: Evidence statements and values are strictly derived from actual row data."""
    task = QueryTask(
        query_id="q_ground",
        purpose="Rank category sales",
        sub_question="What are top category sales by revenue?",
    )
    rows_data = [
        {"category": "Electronics", "revenue": 95000.0},
        {"category": "Furniture", "revenue": 45000.0},
        {"category": "Apparel", "revenue": 20000.0},
    ]
    record = QueryExecutionRecord(
        query_id="q_ground",
        status=QueryExecutionStatus.SUCCESS,
        row_count=3,
        rows=rows_data,
    )

    evidence = EvidenceManager.extract_evidence(record, task)
    assert len(evidence) >= 1

    # Check top-ranking evidence
    top_ev = next(e for e in evidence if e.evidence_type == EvidenceType.RANKING)
    assert top_ev.dimensions["category"] == "Electronics"
    assert top_ev.value == 95000.0
    assert "Electronics is the top category by revenue with 95,000" in top_ev.statement

    # All values in evidence items must exist in returned rows
    for ev in evidence:
        if ev.evidence_type == EvidenceType.RANKING:
            assert ev.value in [95000.0, 45000.0, 20000.0]


# ─── Test L: Graph-Level End-to-End Evidence and Progress Verification ───

@pytest.mark.asyncio
async def test_l_graph_evidence_and_progress_integration():
    """Test L: LangGraph Orchestrator propagates evidence, known_facts, unresolved_questions, and coverage."""
    agent = AnalystAgent()
    mock_db = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.schema = {"sales": {"columns": [{"name": "revenue", "type": "float"}, {"name": "region", "type": "varchar"}]}}
    mock_ctx.catalog = None
    mock_ctx.total_tables = 1
    mock_ctx.total_columns = 2

    grounded = MagicMock()
    grounded.schema_text = "sales(revenue, region)"
    grounded.selected_tables = ["sales"]
    grounded.selected_columns = {"sales": ["revenue", "region"]}
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
        dimensions=["sales.region"],
        aggregations=["SUM"],
        confidence=0.95,
        source="deterministic",
    )

    custom_plan = AnalysisPlan(
        question="Analyze sales",
        analysis_goal="Analyze sales",
        tasks=[
            AnalysisTask(task_id="t1", name="Overall", required_query_tasks=["q_1"]),
            AnalysisTask(task_id="t2", name="Regional", required_query_tasks=["q_2"]),
        ],
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Total sales", sub_question="Total sales", priority=1),
            QueryTask(query_id="q_2", purpose="Regional sales", sub_question="Regional sales", priority=2),
        ],
    )

    async def fake_generate_sql(question, *args, **kwargs):
        return f"SELECT '{question}' AS q"

    async def fake_execute_with_repair(question, *args, **kwargs):
        if "Total" in question:
            return ([{"total_revenue": 100000.0}], "SELECT 100000", None, None, [])
        return ([{"region": "North", "revenue": 60000.0}, {"region": "South", "revenue": 40000.0}], "SELECT regional", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock, return_value=("Evidence report", {})):

        res = await agent.ask("Analyze sales", db=mock_db)

    assert res["success"] is True
    assert "evidence" in res
    assert len(res["evidence"]) >= 2
    assert "known_facts" in res
    assert len(res["known_facts"]) >= 2
    assert "evidence_coverage" in res
    assert res["evidence_coverage"] == 1.0
    assert "unresolved_questions" in res
    assert len(res["unresolved_questions"]) == 0
