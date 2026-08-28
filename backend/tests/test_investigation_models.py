"""Unit tests for Phase 1: Investigation Models and State Foundation.

Validates:
1. QueryTask creation, defaults, dependencies, status, and conversion.
2. InvestigationPlan creation, DAG task scheduling, and AnalysisPlan conversion.
3. QueryExecutionRecord tracking and metrics.
4. EvidenceItem multi-modal support (numeric, categorical, trend, comparison).
5. InvestigationState aggregation, evidence tracking, confidence scoring, and completion rules.
6. Serialization and Deserialization (JSON round-trips).
7. Validation constraints and bounds.
8. Backward compatibility with existing AnalysisPlan, DataRetrievalRequirement, and AgentState.
"""
import json
import pytest
from pydantic import ValidationError

from app.services.analysis.investigation_models import (
    InvestigationMode,
    QueryTaskStatus,
    QueryExecutionStatus,
    EvidenceType,
    InvestigationStatus,
    PlanningValidationError,
    QueryTask,
    QueryExecutionRecord,
    EvidenceItem,
    InvestigationPlan,
    InvestigationState,
    validate_investigation_plan,
)
from app.services.analysis.models import (
    AnalysisPlan,
    AnalysisTask,
    DataRetrievalRequirement,
)
from app.services.analysis.planner import AnalysisPlanner
from app.agent.semantic.query_spec_builder import QuerySpecBuilder
from app.agent.orchestration.graph_orchestrator import AgentState


# ─── 1. QueryTask Tests ───

def test_query_task_creation_and_defaults():
    task = QueryTask(
        query_id="q_1",
        purpose="Retrieve total revenue and invoice counts",
        sub_question="What is the total revenue and count of invoices?",
    )
    assert task.query_id == "q_1"
    assert task.purpose == "Retrieve total revenue and invoice counts"
    assert task.sub_question == "What is the total revenue and count of invoices?"
    assert task.required_metrics == []
    assert task.required_dimensions == []
    assert task.required_filters == []
    assert task.expected_grain is None
    assert task.expected_columns == []
    assert task.depends_on == []
    assert task.priority == 1
    assert task.status == QueryTaskStatus.PENDING
    assert task.can_be_skipped_if_answered is False


def test_query_task_with_full_spec():
    task = QueryTask(
        query_id="q_2",
        purpose="Monthly sales trend for 2024",
        sub_question="What are monthly sales for 2024?",
        required_metrics=["total_amount", "order_count"],
        required_dimensions=["order_month", "country"],
        required_filters=["order_year = 2024"],
        expected_grain="month_country",
        expected_columns=["order_month", "country", "total_amount", "order_count"],
        depends_on=["q_1"],
        priority=2,
        status=QueryTaskStatus.RUNNING,
        can_be_skipped_if_answered=True,
    )
    assert task.depends_on == ["q_1"]
    assert task.priority == 2
    assert task.status == QueryTaskStatus.RUNNING
    assert task.can_be_skipped_if_answered is True


def test_query_task_from_data_requirement_interoperability():
    req = DataRetrievalRequirement(
        requirement_id="req_1",
        description="Fetch customer spending breakdown",
        sub_question="What is each customer's total spending?",
        metrics=["total_spent"],
        dimensions=["customer_id", "country"],
        filters=["status = 'active'"],
    )
    task = QueryTask.from_data_requirement(req, priority=2, depends_on=["q_0"], can_be_skipped=True)
    assert task.query_id == "req_1"
    assert task.purpose == "Fetch customer spending breakdown"
    assert task.sub_question == "What is each customer's total spending?"
    assert task.required_metrics == ["total_spent"]
    assert task.required_dimensions == ["customer_id", "country"]
    assert task.required_filters == ["status = 'active'"]
    assert task.priority == 2
    assert task.depends_on == ["q_0"]
    assert task.can_be_skipped_if_answered is True

    # Test reverse conversion
    converted_req = task.to_data_requirement()
    assert converted_req.requirement_id == "req_1"
    assert converted_req.sub_question == "What is each customer's total spending?"
    assert converted_req.metrics == ["total_spent"]
    assert converted_req.dimensions == ["customer_id", "country"]


# ─── 2. InvestigationPlan Tests ───

def test_investigation_plan_creation():
    tasks = [
        QueryTask(query_id="q_1", purpose="Baseline sales", sub_question="What is total sales?", priority=1),
        QueryTask(query_id="q_2", purpose="Monthly trend", sub_question="What is monthly sales trend?", depends_on=["q_1"], priority=2),
    ]
    plan = InvestigationPlan(
        question="Why did Q4 sales drop?",
        goal="Investigate root causes for Q4 sales decline",
        investigation_mode=InvestigationMode.ROOT_CAUSE,
        hypotheses=["Regional shipping delays caused drop", "Key product churn in enterprise segment"],
        query_tasks=tasks,
        expected_insights=["Baseline volume", "Cohort breakdown"],
        max_queries=6,
        max_reasoning_steps=12,
        stop_conditions=["sufficient_evidence"],
    )

    assert plan.question == "Why did Q4 sales drop?"
    assert plan.investigation_mode == InvestigationMode.ROOT_CAUSE
    assert len(plan.hypotheses) == 2
    assert len(plan.query_tasks) == 2
    assert plan.get_sub_questions() == ["What is total sales?", "What is monthly sales trend?"]
    assert len(plan.get_pending_tasks()) == 2


def test_investigation_plan_dag_task_scheduling():
    t1 = QueryTask(query_id="q_1", sub_question="Sub 1", priority=1, status=QueryTaskStatus.COMPLETED)
    t2 = QueryTask(query_id="q_2", sub_question="Sub 2", priority=2, depends_on=["q_1"], status=QueryTaskStatus.PENDING)
    t3 = QueryTask(query_id="q_3", sub_question="Sub 3", priority=3, depends_on=["q_2"], status=QueryTaskStatus.PENDING)

    plan = InvestigationPlan(
        question="Test DAG",
        query_tasks=[t3, t2, t1],
    )

    # Next runnable task should be q_2 since q_1 is completed and q_2 has priority 2
    next_task = plan.get_next_runnable_task(completed_ids={"q_1"})
    assert next_task is not None
    assert next_task.query_id == "q_2"

    # When q_2 is not completed, q_3 cannot run
    next_for_empty = plan.get_next_runnable_task(completed_ids=set())
    # q_1 is already completed, so with completed_ids=set(), q_1 is filtered out because status==COMPLETED
    assert next_for_empty is None


def test_investigation_plan_and_analysis_plan_conversion():
    req1 = DataRetrievalRequirement(
        requirement_id="req_1",
        description="Overall revenue",
        sub_question="What is total revenue?",
    )
    req2 = DataRetrievalRequirement(
        requirement_id="req_2",
        description="Revenue by region",
        sub_question="What is revenue grouped by country?",
    )
    analysis_plan = AnalysisPlan(
        question="Analyze global revenue",
        analysis_goal="Evaluate worldwide sales distribution",
        data_requirements=[req1, req2],
        expected_insights=["Global revenue baseline", "Top countries"],
    )

    # Convert AnalysisPlan -> InvestigationPlan
    inv_plan = InvestigationPlan.from_analysis_plan(
        analysis_plan,
        investigation_mode=InvestigationMode.COMPARATIVE,
        max_queries=4,
    )
    assert inv_plan.question == "Analyze global revenue"
    assert inv_plan.goal == "Evaluate worldwide sales distribution"
    assert inv_plan.investigation_mode == InvestigationMode.COMPARATIVE
    assert len(inv_plan.query_tasks) == 2
    assert inv_plan.query_tasks[0].query_id == "req_1"
    # Neither req1 nor req2 has explicit dependencies, so both are independent
    assert inv_plan.query_tasks[0].depends_on == []
    assert inv_plan.query_tasks[1].depends_on == []
    # Priorities reflect ordering without forcing sequential dependencies
    assert inv_plan.query_tasks[0].priority == 1
    assert inv_plan.query_tasks[1].priority == 2

    # Convert via AnalysisPlan.to_investigation_plan helper method
    inv_plan2 = analysis_plan.to_investigation_plan(InvestigationMode.EXPLORATORY)
    assert inv_plan2.investigation_mode == InvestigationMode.EXPLORATORY
    assert len(inv_plan2.query_tasks) == 2

    # Convert back InvestigationPlan -> AnalysisPlan
    conv_analysis_plan = inv_plan.to_analysis_plan()
    assert conv_analysis_plan.question == "Analyze global revenue"
    assert len(conv_analysis_plan.data_requirements) == 2
    assert conv_analysis_plan.data_requirements[0].sub_question == "What is total revenue?"


def test_investigation_plan_preserves_explicit_and_independent_dependencies():
    """Verify Q1 is independent, Q2 is independent, Q3 depends on Q1 -> no artificial dependency between Q1 and Q2."""
    class CustomReq(DataRetrievalRequirement):
        depends_on: list = []

    req1 = CustomReq(
        requirement_id="Q1",
        description="Total sales",
        sub_question="What is total sales?",
    )
    req2 = CustomReq(
        requirement_id="Q2",
        description="Active customer count",
        sub_question="How many active customers exist?",
    )
    req3 = CustomReq(
        requirement_id="Q3",
        description="Sales drilldown for top segment",
        sub_question="What is sales breakdown for top segment?",
        depends_on=["Q1"],
    )

    analysis_plan = AnalysisPlan(
        question="Analyze sales and customers",
        analysis_goal="Customer and sales overview",
        data_requirements=[req1, req2, req3],
    )

    inv_plan = InvestigationPlan.from_analysis_plan(analysis_plan)
    assert len(inv_plan.query_tasks) == 3

    t1, t2, t3 = inv_plan.query_tasks[0], inv_plan.query_tasks[1], inv_plan.query_tasks[2]
    
    # Q1 is independent
    assert t1.query_id == "Q1"
    assert t1.depends_on == []
    assert t1.priority == 1

    # Q2 is independent (no artificial dependency on Q1)
    assert t2.query_id == "Q2"
    assert t2.depends_on == []
    assert t2.priority == 2

    # Q3 explicitly depends on Q1
    assert t3.query_id == "Q3"
    assert t3.depends_on == ["Q1"]
    assert t3.priority == 3



# ─── 3. QueryExecutionRecord Tests ───

def test_query_execution_record():
    record = QueryExecutionRecord(
        query_id="q_1",
        purpose="Retrieve 2024 totals",
        sub_question="What is the 2024 total sales?",
        sql="SELECT SUM(total) as revenue FROM invoices WHERE strftime('%Y', InvoiceDate) = '2024'",
        status=QueryExecutionStatus.SUCCESS,
        row_count=1,
        rows=[{"revenue": 150000.0}],
        findings=["Total 2024 revenue is $150,000"],
        metrics={"revenue": 150000.0},
        execution_time_ms=18.4,
        cache_hit=False,
    )
    assert record.query_id == "q_1"
    assert record.status == QueryExecutionStatus.SUCCESS
    assert record.row_count == 1
    assert record.rows[0]["revenue"] == 150000.0
    assert record.metrics["revenue"] == 150000.0
    assert record.execution_time_ms == 18.4
    assert record.cache_hit is False
    assert record.error is None


# ─── 4. EvidenceItem Multi-Modal Tests ───

def test_evidence_item_numeric():
    ev = EvidenceItem(
        evidence_id="ev_num_1",
        source_query_id="q_1",
        statement="Total annual revenue reached $2,450,000",
        value=2450000.0,
        metric="annual_revenue",
        dimensions={"year": 2024},
        confidence=0.98,
        verified=True,
        evidence_type=EvidenceType.NUMERIC,
    )
    assert ev.evidence_id == "ev_num_1"
    assert ev.value == 2450000.0
    assert ev.metric == "annual_revenue"
    assert ev.evidence_type == EvidenceType.NUMERIC
    assert ev.confidence == 0.98


def test_evidence_item_categorical():
    ev = EvidenceItem(
        evidence_id="ev_cat_1",
        source_query_id="q_2",
        statement="USA is the highest contributing country with 38% market share",
        value="USA",
        metric="top_market",
        dimensions={"country": "USA", "share_pct": 38.0},
        confidence=0.95,
        verified=True,
        evidence_type=EvidenceType.CATEGORICAL,
    )
    assert ev.value == "USA"
    assert ev.evidence_type == EvidenceType.CATEGORICAL


def test_evidence_item_trend():
    ev = EvidenceItem(
        evidence_id="ev_trend_1",
        source_query_id="q_3",
        statement="Sales grew at +14.2% compound monthly growth rate across Q1-Q3",
        value=14.2,
        metric="cmgr",
        dimensions={"period": "Q1-Q3", "direction": "upward"},
        confidence=0.92,
        verified=True,
        evidence_type=EvidenceType.TREND,
    )
    assert ev.evidence_type == EvidenceType.TREND
    assert ev.value == 14.2


def test_evidence_item_comparison():
    ev = EvidenceItem(
        evidence_id="ev_comp_1",
        source_query_id="q_4",
        statement="Q4 revenue ($820K) decreased by 18% compared to Q3 ($1.0M)",
        value={"q3_sales": 1000000.0, "q4_sales": 820000.0, "pct_change": -18.0},
        metric="quarterly_change_pct",
        dimensions={"base_quarter": "Q3", "target_quarter": "Q4"},
        confidence=0.96,
        verified=True,
        evidence_type=EvidenceType.COMPARISON,
    )
    assert ev.evidence_type == EvidenceType.COMPARISON
    assert isinstance(ev.value, dict)
    assert ev.value["pct_change"] == -18.0


# ─── 5. InvestigationState Tests ───

def test_investigation_state_defaults_and_updates():
    state = InvestigationState()
    assert state.plan is None
    assert state.completed_queries == []
    assert state.evidence == []
    assert state.known_facts == []
    assert state.unresolved_questions == []
    assert state.hypotheses == []
    assert state.tested_hypotheses == {}
    assert state.findings == []
    assert state.completeness_score == 0.0
    assert state.confidence_score == 0.0
    assert state.queries_executed == 0
    assert state.max_queries == 5
    assert state.reasoning_steps == 0
    assert state.max_reasoning_steps == 10
    assert state.status == InvestigationStatus.NOT_STARTED
    assert state.is_complete() is False

    # Add execution record
    rec = QueryExecutionRecord(
        query_id="q_1",
        sql="SELECT 1",
        row_count=1,
        findings=["Found 1 active store"],
    )
    state.status = InvestigationStatus.IN_PROGRESS
    state.add_execution_record(rec)
    assert state.queries_executed == 1
    assert "Found 1 active store" in state.findings
    assert "Found 1 active store" in state.known_facts

    # Add first evidence (confidence = 0.90)
    ev1 = EvidenceItem(
        evidence_id="ev_1",
        statement="Store 1 is located in NY",
        confidence=0.90,
    )
    state.add_evidence(ev1)
    assert len(state.evidence) == 1
    assert "Store 1 is located in NY" in state.known_facts
    assert state.confidence_score == 0.90

    # Add second evidence (confidence = 0.80) -> rolling average (0.90 + 0.80) / 2 = 0.85
    ev2 = EvidenceItem(
        evidence_id="ev_2",
        statement="Store 1 annual revenue is $500K",
        confidence=0.80,
    )
    state.add_evidence(ev2)
    assert len(state.evidence) == 2
    assert state.confidence_score == 0.85


def test_investigation_state_completion_triggers():
    state = InvestigationState(max_queries=2, max_reasoning_steps=3)
    state.status = InvestigationStatus.IN_PROGRESS

    # 1. Not complete yet
    assert state.is_complete() is False

    # 2. Add first record
    state.add_execution_record(QueryExecutionRecord(query_id="q_1", sql="SELECT 1"))
    assert state.is_complete() is False

    # 3. Add second record -> hits max_queries budget
    state.add_execution_record(QueryExecutionRecord(query_id="q_2", sql="SELECT 2"))
    assert state.status == InvestigationStatus.MAX_QUERIES_REACHED
    assert state.is_complete() is True

    # 4. Explicit status complete
    state2 = InvestigationState(status=InvestigationStatus.SUFFICIENT_EVIDENCE)
    assert state2.is_complete() is True


# ─── 6. Serialization & Validation Tests ───

def test_investigation_models_json_serialization_roundtrip():
    plan = InvestigationPlan(
        question="What are top 5 products by margin?",
        goal="Determine highest profitability items",
        investigation_mode=InvestigationMode.DIRECT,
        query_tasks=[
            QueryTask(
                query_id="q_1",
                purpose="Rank products by margin",
                sub_question="Which products have the highest margin?",
                required_metrics=["margin_pct"],
                required_dimensions=["product_name"],
            )
        ],
    )
    
    state = InvestigationState(
        plan=plan,
        hypotheses=["Accessories have higher margin than electronics"],
        completeness_score=0.85,
        status=InvestigationStatus.IN_PROGRESS,
    )
    state.add_evidence(
        EvidenceItem(
            evidence_id="ev_1",
            source_query_id="q_1",
            statement="Product A has 62% margin",
            value=62.0,
            metric="margin_pct",
            confidence=0.95,
        )
    )

    # Dump to JSON and reload
    json_str = state.model_dump_json()
    assert isinstance(json_str, str)
    
    loaded_data = json.loads(json_str)
    assert loaded_data["plan"]["question"] == "What are top 5 products by margin?"
    assert loaded_data["evidence"][0]["value"] == 62.0

    # Validate back to InvestigationState
    reconstructed_state = InvestigationState.model_validate_json(json_str)
    assert reconstructed_state.plan.question == "What are top 5 products by margin?"
    assert len(reconstructed_state.evidence) == 1
    assert reconstructed_state.evidence[0].value == 62.0
    assert reconstructed_state.confidence_score == 0.95


def test_validation_constraints():
    # Confidence must be between 0.0 and 1.0
    with pytest.raises(ValidationError):
        EvidenceItem(
            evidence_id="ev_invalid",
            statement="Invalid confidence score",
            confidence=1.5,  # > 1.0 should fail validation
        )

    with pytest.raises(ValidationError):
        EvidenceItem(
            evidence_id="ev_invalid_neg",
            statement="Invalid negative confidence",
            confidence=-0.1,  # < 0.0 should fail validation
        )

    # max_queries must be >= 1
    with pytest.raises(ValidationError):
        InvestigationPlan(
            question="Test",
            max_queries=0,  # < 1 should fail validation
        )


# ─── 7. AgentState Backward Compatibility Test ───

def test_agent_state_with_investigation():
    # Verify AgentState accepts investigation field without breaking
    state: AgentState = {
        "question": "Show total sales",
        "sql": "SELECT SUM(total) FROM invoices",
        "rows": [{"sum": 1000}],
        "investigation": InvestigationState(
            completeness_score=1.0,
            status=InvestigationStatus.COMPLETED,
        ),
    }

    assert state["question"] == "Show total sales"
    assert state["investigation"].status == InvestigationStatus.COMPLETED
    assert state["investigation"].completeness_score == 1.0


# ─── 8. Phase 2: AnalyticalTask & QueryTask Planning Hierarchy Tests ───

def test_phase2_analytical_and_query_task_hierarchy():
    """Verify AnalyticalTask -> QueryTask[] separation and mapping."""
    task1 = AnalysisTask(
        task_id="task_baseline",
        name="Quantify Revenue Drop",
        objective="Determine if decline is statistically present",
        description="Calculate baseline vs current revenue",
        required_query_tasks=["q_baseline"],
        priority=1,
    )
    task2 = AnalysisTask(
        task_id="task_drivers",
        name="Identify Driver Segments",
        objective="Find primary segment contributors to drop",
        description="Decompose drop across product categories and regions",
        required_query_tasks=["q_prod_drivers", "q_region_drivers"],
        depends_on=["task_baseline"],
        priority=2,
    )

    q1 = QueryTask(
        query_id="q_baseline",
        analytical_task_id="task_baseline",
        purpose="Retrieve monthly revenue for baseline and drop period",
        sub_question="What is the monthly revenue for the last 12 months?",
        expected_evidence="Monthly revenue trend and exact drop percentage",
        priority=1,
    )
    q2 = QueryTask(
        query_id="q_prod_drivers",
        analytical_task_id="task_drivers",
        purpose="Compare revenue by product category",
        sub_question="What is the revenue breakdown by product category?",
        expected_evidence="Category-level contribution to total decline",
        depends_on=["q_baseline"],
        priority=2,
    )
    q3 = QueryTask(
        query_id="q_region_drivers",
        analytical_task_id="task_drivers",
        purpose="Compare revenue by geographic region",
        sub_question="What is the revenue breakdown by country?",
        expected_evidence="Regional contribution to total decline",
        priority=2,
    )

    plan = InvestigationPlan(
        question="Why did sales drop last quarter?",
        goal="Investigate drivers for quarterly sales decline",
        investigation_mode=InvestigationMode.ROOT_CAUSE,
        analysis_tasks=[task1, task2],
        query_tasks=[q1, q2, q3],
    )

    # 1. Validate structure
    assert plan.is_valid
    errors = plan.validate_plan()
    assert len(errors) == 0

    # 2. Check Analytical Task -> QueryTask linkage
    t1_queries = plan.get_query_tasks_for_analysis_task("task_baseline")
    assert len(t1_queries) == 1
    assert t1_queries[0].query_id == "q_baseline"

    t2_queries = plan.get_query_tasks_for_analysis_task("task_drivers")
    assert len(t2_queries) == 2
    assert {q.query_id for q in t2_queries} == {"q_prod_drivers", "q_region_drivers"}

    # 3. Check expected evidence
    assert q2.expected_evidence == "Category-level contribution to total decline"
    assert q3.expected_evidence == "Regional contribution to total decline"


# ─── 9. Phase 2: Planning Validation Engine Rules Tests ───

def test_validation_rule1_duplicate_query_id():
    """Rule 1: Duplicate query_id must be detected."""
    q1 = QueryTask(query_id="q_dup", purpose="First", sub_question="First question?")
    q2 = QueryTask(query_id="q_dup", purpose="Second", sub_question="Second question?")
    plan = InvestigationPlan(question="Test", query_tasks=[q1, q2])

    errors = plan.validate_plan()
    assert any("Duplicate query_id detected: 'q_dup'" in e for e in errors)
    assert not plan.is_valid

    with pytest.raises(PlanningValidationError):
        validate_investigation_plan(plan, raise_on_error=True)


def test_validation_rule2_invalid_analytical_task_reference():
    """Rule 2: QueryTask pointing to non-existent analytical_task_id must be detected."""
    t1 = AnalysisTask(task_id="task_valid", name="Valid Task")
    q1 = QueryTask(
        query_id="q_1",
        analytical_task_id="task_non_existent",
        purpose="Data query",
        sub_question="What is data?",
    )
    plan = InvestigationPlan(question="Test", analysis_tasks=[t1], query_tasks=[q1])

    errors = plan.validate_plan()
    assert any("references unknown analytical_task_id 'task_non_existent'" in e for e in errors)


def test_validation_rule3_invalid_dependency_reference():
    """Rule 3: Dependency pointing to non-existent query_id must be detected."""
    q1 = QueryTask(
        query_id="q_1",
        purpose="First",
        sub_question="First?",
        depends_on=["q_ghost"],
    )
    plan = InvestigationPlan(question="Test", query_tasks=[q1])

    errors = plan.validate_plan()
    assert any("depends on unknown query_id 'q_ghost'" in e for e in errors)


def test_validation_rule4_cyclic_dependency_detection():
    """Rule 4: Circular dependencies (Q1 -> Q2 -> Q1) must be detected."""
    q1 = QueryTask(query_id="q_1", purpose="A", sub_question="A?", depends_on=["q_2"])
    q2 = QueryTask(query_id="q_2", purpose="B", sub_question="B?", depends_on=["q_1"])
    plan = InvestigationPlan(question="Test", query_tasks=[q1, q2])

    errors = plan.validate_plan()
    assert any("Cyclic dependency detected among query tasks" in e for e in errors)


def test_validation_rule5_empty_purpose_or_sub_question():
    """Rule 5: Empty purpose or sub_question must be detected."""
    q1 = QueryTask(query_id="q_1", purpose="   ", sub_question="Valid sub question?")
    q2 = QueryTask(query_id="q_2", purpose="Valid purpose", sub_question="")
    plan = InvestigationPlan(question="Test", query_tasks=[q1, q2])

    errors = plan.validate_plan()
    assert any("must have a non-empty purpose" in e for e in errors)
    assert any("must have a non-empty sub_question" in e for e in errors)


def test_validation_rule6_duplicate_semantic_queries():
    """Rule 6: Duplicate query tasks with identical purpose and sub_question must be detected."""
    q1 = QueryTask(query_id="q_1", purpose="Fetch sales", sub_question="What is total sales?")
    q2 = QueryTask(query_id="q_2", purpose="Fetch sales", sub_question="What is total sales?")
    plan = InvestigationPlan(question="Test", query_tasks=[q1, q2])

    errors = plan.validate_plan()
    assert any("Duplicate query task detected" in e for e in errors)


# ─── 10. Phase 2: Natural Query Scaling for Query Types (Tests A to E) ───

def test_phase2_test_a_simple_lookup():
    """Test A: Simple lookup generates 1 AnalysisTask and 1 QueryTask (not 5 queries)."""
    builder = QuerySpecBuilder()
    spec = builder.build_spec("كم عدد العملاء؟")

    planner = AnalysisPlanner()
    inv_plan = planner.plan_investigation(spec)

    assert inv_plan.investigation_mode == InvestigationMode.DIRECT
    assert len(inv_plan.query_tasks) == 1
    assert inv_plan.max_queries <= 3
    assert inv_plan.query_tasks[0].depends_on == []
    assert inv_plan.is_valid


def test_phase2_test_b_trend():
    """Test B: Trend query generates trend analysis task and time-series query with expected evidence."""
    builder = QuerySpecBuilder()
    spec = builder.build_spec("ما هو اتجاه المبيعات في آخر 12 شهر؟")

    planner = AnalysisPlanner()
    inv_plan = planner.plan_investigation(spec)

    assert len(inv_plan.query_tasks) >= 1
    assert any(q.expected_evidence for q in inv_plan.query_tasks)
    assert inv_plan.is_valid


def test_phase2_test_c_root_cause_multi_query():
    """Test C: Root cause generates multiple AnalysisTasks and multiple QueryTasks."""
    builder = QuerySpecBuilder()
    spec = builder.build_spec("لماذا انخفضت المبيعات في الربع الأخير؟")

    planner = AnalysisPlanner()
    inv_plan = planner.plan_investigation(spec)

    assert inv_plan.investigation_mode == InvestigationMode.ROOT_CAUSE
    assert len(inv_plan.query_tasks) >= 2
    assert len(inv_plan.analysis_tasks) >= 2
    # Verify tasks and queries are linked
    for q in inv_plan.query_tasks:
        assert q.analytical_task_id is not None
    assert inv_plan.is_valid


def test_phase2_test_d_independent_tasks():
    """Test D: Q2 and Q3 can be independent without forced sequential dependencies."""
    builder = QuerySpecBuilder()
    spec = builder.build_spec("حلل المبيعات")

    planner = AnalysisPlanner()
    inv_plan = planner.plan_investigation(spec)

    # In exploratory sales, check that tasks default to independent unless explicitly dependent
    independent_queries = [q for q in inv_plan.query_tasks if not q.depends_on]
    assert len(independent_queries) >= 1
    assert inv_plan.is_valid


# ─── 11. Phase 2: Formal Acceptance Tests (Test 1 to Test 7) ───

def test_phase2_test1_direct_question():
    """Test 1: Direct question produces exactly 1 AnalysisTask and 1 QueryTask."""
    builder = QuerySpecBuilder()
    spec = builder.build_spec("How many customers do we have?")

    planner = AnalysisPlanner()
    inv_plan = planner.plan_investigation(spec)

    assert len(inv_plan.analysis_tasks) == 1
    assert len(inv_plan.query_tasks) == 1
    assert inv_plan.investigation_mode == InvestigationMode.DIRECT
    assert inv_plan.query_tasks[0].depends_on == []
    assert inv_plan.is_valid


def test_phase2_test2_trend():
    """Test 2: Trend question produces Trend AnalysisTask and time-series QueryTask."""
    builder = QuerySpecBuilder()
    spec = builder.build_spec("How did revenue change over the last 12 months?")

    planner = AnalysisPlanner()
    inv_plan = planner.plan_investigation(spec)

    assert any("trend" in str(t.operation).lower() or "growth" in t.name.lower() for t in inv_plan.analysis_tasks)
    assert len(inv_plan.query_tasks) >= 1
    assert inv_plan.query_tasks[0].sub_question != ""
    assert inv_plan.is_valid


def test_phase2_test3_root_cause():
    """Test 3: Root cause question produces multiple AnalysisTasks and multiple QueryTasks."""
    builder = QuerySpecBuilder()
    spec = builder.build_spec("Why did revenue decline last quarter?")

    planner = AnalysisPlanner()
    inv_plan = planner.plan_investigation(spec)

    assert inv_plan.investigation_mode == InvestigationMode.ROOT_CAUSE
    assert len(inv_plan.analysis_tasks) >= 2
    assert len(inv_plan.query_tasks) >= 2
    # Verify each QueryTask belongs to an AnalysisTask
    for q in inv_plan.query_tasks:
        assert q.analytical_task_id is not None
    assert inv_plan.is_valid


def test_phase2_test4_explicit_dependencies():
    """Test 4: Explicit dependencies only (e.g. Q2 and Q3 depend on Q1, but Q2 and Q3 are independent siblings)."""
    q1 = QueryTask(query_id="q_1", purpose="Drop period baseline", sub_question="When did sales drop?")
    q2 = QueryTask(query_id="q_2", purpose="Product drivers", sub_question="Sales by product?", depends_on=["q_1"])
    q3 = QueryTask(query_id="q_3", purpose="Regional drivers", sub_question="Sales by region?", depends_on=["q_1"])

    plan = InvestigationPlan(
        question="Why did sales drop?",
        query_tasks=[q1, q2, q3],
    )

    assert q2.depends_on == ["q_1"]
    assert q3.depends_on == ["q_1"]
    assert "q_3" not in q2.depends_on
    assert "q_2" not in q3.depends_on
    assert plan.is_valid


def test_phase2_test5_no_positional_parent_mapping():
    """Test 5: No positional parent mapping. Multiple queries can link to Task B without forcing 1:1 index mapping."""
    task_a = AnalysisTask(task_id="task_a", name="Task A")
    task_b = AnalysisTask(task_id="task_b", name="Task B")

    # Q1 -> Task A, Q2 -> Task B, Q3 -> Task B
    req1 = DataRetrievalRequirement(
        requirement_id="req_1",
        analytical_task_id="task_a",
        description="Query for Task A",
        sub_question="Q1 sub question?",
    )
    req2 = DataRetrievalRequirement(
        requirement_id="req_2",
        analytical_task_id="task_b",
        description="Query 1 for Task B",
        sub_question="Q2 sub question?",
    )
    req3 = DataRetrievalRequirement(
        requirement_id="req_3",
        analytical_task_id="task_b",
        description="Query 2 for Task B",
        sub_question="Q3 sub question?",
    )

    analysis_plan = AnalysisPlan(
        question="Test Question",
        analysis_goal="Test Goal",
        tasks=[task_a, task_b],
        data_requirements=[req1, req2, req3],
    )

    inv_plan = analysis_plan.to_investigation_plan()
    assert len(inv_plan.query_tasks) == 3

    # Q3 must be linked to task_b (NOT a non-existent task_c or positional index)
    assert inv_plan.query_tasks[0].analytical_task_id == "task_a"
    assert inv_plan.query_tasks[1].analytical_task_id == "task_b"
    assert inv_plan.query_tasks[2].analytical_task_id == "task_b"
    assert inv_plan.is_valid


def test_phase2_test6_expected_evidence():
    """Test 6: expected_evidence is explicit, and remains None if not determinable (no fake fallback to description)."""
    q_explicit = QueryTask(
        query_id="q_1",
        purpose="Identify category drop",
        sub_question="What is category revenue?",
        expected_evidence="Category-level revenue change and contribution to total decline",
    )
    q_none = QueryTask(
        query_id="q_2",
        purpose="Simple lookup",
        sub_question="How many users?",
        expected_evidence=None,
    )

    assert q_explicit.expected_evidence == "Category-level revenue change and contribution to total decline"
    assert q_none.expected_evidence is None

    # Verify DataRetrievalRequirement -> QueryTask does not fake evidence
    req_no_ev = DataRetrievalRequirement(
        requirement_id="req_clean",
        description="Just a description",
        sub_question="Just a question?",
        expected_evidence=None,
    )
    q_converted = QueryTask.from_data_requirement(req_no_ev)
    assert q_converted.expected_evidence is None


def test_phase2_test7_backward_compatibility():
    """Test 7: Backward compatibility with DataRetrievalRequirement and legacy AnalysisPlan workflows."""
    req = DataRetrievalRequirement(
        requirement_id="req_legacy",
        description="Legacy requirement",
        sub_question="What is the legacy query?",
        metrics=["m1"],
        dimensions=["d1"],
    )
    legacy_plan = AnalysisPlan(
        question="Legacy question",
        analysis_goal="Legacy goal",
        tasks=[AnalysisTask(task_id="t1", name="Legacy Task", description="Desc")],
        data_requirements=[req],
    )

    # 1. get_sub_questions works
    assert legacy_plan.get_sub_questions() == ["What is the legacy query?"]

    # 2. Canonical query_tasks was populated automatically
    assert len(legacy_plan.query_tasks) == 1
    assert legacy_plan.query_tasks[0].query_id == "req_legacy"

    # 3. InvestigationPlan conversion works
    inv_plan = legacy_plan.to_investigation_plan()
    assert len(inv_plan.query_tasks) == 1
    assert inv_plan.query_tasks[0].sub_question == "What is the legacy query?"

    # 4. InvestigationPlan back to AnalysisPlan works
    reverted_plan = inv_plan.to_analysis_plan()
    assert len(reverted_plan.data_requirements) == 1
    assert reverted_plan.data_requirements[0].requirement_id == "req_legacy"


