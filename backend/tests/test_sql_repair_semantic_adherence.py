"""Unit tests for SQL Repair Semantic Adherence.

Verifies that the self-healing SQL Repair pipeline strictly adheres to the
original business question, semantic contract (grain, measures, dimensions,
temporal scope, filters), domain knowledge, and semantic gate feedback.
"""
from unittest.mock import AsyncMock, MagicMock
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.orchestration.sql_generator import SQLGenerator
from app.agent.semantic.contract import (
    SemanticContract,
    SemanticGrain,
    GrainType,
    FormulaType,
    MetricSpec,
    DimensionSpec,
    TimeSpec,
    FilterSpec,
    FilterOperator,
    SortSpec,
)
from app.agent.semantic.models import QueryUnderstanding
from app.services.sql.control_gate import SQLControlGateResult
from app.services.sql.prompt_builder import SQLPromptBuilder
from app.services.sql.repair_engine import SQLRepairEngine


@pytest.fixture
def prompt_builder():
    return SQLPromptBuilder()


@pytest.fixture
def sample_semantic_contract():
    return SemanticContract(
        contract_id="contract_sales_q1",
        raw_question="What are the total sales by product category in Q1 2024 for completed orders?",
        grain=SemanticGrain(grain_type=GrainType.ENTITY_GRAIN, description="Total sales per product category"),
        measures=[
            MetricSpec(
                metric_id="total_sales",
                display_name="Total Sales",
                formula_type=FormulaType.SUM,
                source_table="order_items",
                source_column="subtotal",
            )
        ],
        dimensions=[
            DimensionSpec(
                dimension_id="category_name",
                display_name="Product Category",
                source_table="categories",
                source_column="name",
            )
        ],
        filters=[
            FilterSpec(
                concept="status",
                target_table="orders",
                target_column="status",
                operator=FilterOperator.EQ,
                raw_value="completed",
            )
        ],
        time_spec=TimeSpec(
            time_column="order_date",
            source_table="orders",
            start_date="2024-01-01",
            end_date="2024-03-31",
            raw_expression="Q1 2024",
        ),
        sorting=[
            SortSpec(target="total_sales", direction="DESC")
        ],
        limit=10,
    )


def test_repair_prompt_injects_semantic_contract_constraints(prompt_builder, sample_semantic_contract):
    """Verify that build_fix_input includes all semantic contract constraints in the payload."""
    query_understanding = QueryUnderstanding(
        raw_question="What are the total sales by product category in Q1 2024 for completed orders?",
        route="data_query",
        analysis_required=True,
        analysis_level="metric",
        analysis_type="aggregation",
        analysis_goal="Calculate total sales by product category in Q1 2024",
        entities=["orders", "order_items", "categories"],
        metrics=["order_items.subtotal"],
        dimensions=["categories.name"],
        aggregations=["SUM"],
        limit=10,
        sort_direction="DESC",
        semantic_contract=sample_semantic_contract,
    )

    fix_payload = prompt_builder.build_fix_input(
        schema_text="categories(id INT PK, name VARCHAR)\norders(id INT PK, order_date DATE, status VARCHAR)\norder_items(id INT PK, order_id INT, subtotal REAL)",
        question="What are the total sales by product category in Q1 2024 for completed orders?",
        failed_sql="SELECT name, SUM(subtotal) FROM order_items GROUP BY name",
        error="no such column: name",
        dialect="sqlite",
        query_understanding=query_understanding,
    )

    formatted_prompt = prompt_builder.fix_template.format(**fix_payload)

    # 1. Output Grain check
    assert "Output Grain:" in formatted_prompt
    # 2. Required Measures & Formulas check
    assert "Total Sales -> SUM(order_items.subtotal)" in formatted_prompt
    # 3. Required Dimensions / Group By check
    assert "categories.name" in formatted_prompt
    # 4. Temporal Scope & bounds check
    assert "orders.order_date >= '2024-01-01'" in formatted_prompt
    assert "orders.order_date <= '2024-03-31'" in formatted_prompt
    # 5. Mandatory Filters check
    assert "status = 'completed'" in formatted_prompt
    # 6. Anti-drift rules in prompt
    assert "STRICT INTENT & SEMANTIC ADHERENCE" in formatted_prompt
    assert "NEVER DROP FILTERS OR SCOPES" in formatted_prompt
    assert "PRESERVE AGGREGATIONS & GRAIN" in formatted_prompt


def test_repair_prompt_backward_compatible_without_contract(prompt_builder):
    """Verify that build_fix_input works without error when query_understanding is None."""
    fix_payload = prompt_builder.build_fix_input(
        schema_text="users(id INT PK, name VARCHAR)",
        question="Show all users",
        failed_sql="SELECT id, full_name FROM users",
        error="no such column: full_name",
        dialect="sqlite",
    )
    formatted = prompt_builder.fix_template.format(**fix_payload)
    assert "Failed Query: SELECT id, full_name FROM users" in formatted
    assert "Original Question: Show all users" in formatted


@pytest.mark.asyncio
async def test_repair_engine_forwards_semantic_context():
    """Verify that SQLRepairEngine.fix_sql forwards semantic understanding to prompt builder."""
    mock_llm = MagicMock()
    repair_engine = SQLRepairEngine(mock_llm)

    mock_resp = AIMessage(content="SELECT c.name, SUM(oi.subtotal) AS total_sales FROM categories c JOIN order_items oi ON c.id = oi.id GROUP BY c.name")
    repair_engine.sql_fix_chain = MagicMock()
    repair_engine.sql_fix_chain.ainvoke = AsyncMock(return_value=mock_resp)

    understanding = QueryUnderstanding(
        raw_question="Total sales by category",
        route="data_query",
        analysis_required=True,
        analysis_level="metric",
        analysis_type="aggregation",
        analysis_goal="Calculate total sales by category",
        entities=["categories", "order_items"],
        metrics=["order_items.subtotal"],
        dimensions=["categories.name"],
        aggregations=["SUM"],
    )

    fixed = await repair_engine.fix_sql(
        question="Total sales by category",
        schema_text="categories(id INT, name VARCHAR)\norder_items(id INT, subtotal REAL)",
        failed_sql="SELECT name, SUM(subtotal) FROM order_items GROUP BY name",
        error="no such column: name",
        dialect="sqlite",
        query_understanding=understanding,
        conversation_history="User: previous question",
    )

    assert "SELECT" in fixed
    assert repair_engine.sql_fix_chain.ainvoke.called
    called_payload = repair_engine.sql_fix_chain.ainvoke.call_args[0][0]
    assert "semantic_constraints" in called_payload
    constraints_str = called_payload["semantic_constraints"]
    assert "categories.name" in constraints_str
    assert "categories, order_items" in constraints_str


@pytest.mark.asyncio
async def test_execute_with_repair_semantic_gate_feedback_loop():
    """Verify that execute_with_repair feeds semantic gate rejection errors back to fix_sql."""
    mock_primary_llm = MagicMock()
    mock_self_consistency_llm = MagicMock()

    sql_generator = SQLGenerator(mock_primary_llm, mock_self_consistency_llm)

    # Mock DB session
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        from sqlalchemy import text
        conn.execute(text("CREATE TABLE orders (id INT, status VARCHAR, amount REAL, order_date DATE);"))
        conn.execute(text("INSERT INTO orders VALUES (1, 'completed', 100.0, '2024-02-01');"))
        conn.commit()
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Sequence of repair responses:
    # 1. First repair fixes syntax but forgets the filter (will fail pre_execution_gate)
    # 2. Second repair receives gate error and produces fully aligned SQL
    resp1 = AIMessage(content="SELECT SUM(amount) FROM orders;")
    resp2 = AIMessage(content="SELECT SUM(amount) FROM orders WHERE status = 'completed';")

    sql_generator.repair_engine.sql_fix_chain = MagicMock()
    sql_generator.repair_engine.sql_fix_chain.ainvoke = AsyncMock(side_effect=[resp1, resp2])

    gate_eval_count = 0
    def mock_gate(sql: str) -> SQLControlGateResult:
        nonlocal gate_eval_count
        gate_eval_count += 1
        if "status" not in sql.lower():
            return SQLControlGateResult(
                allowed=False,
                error_type="semantic_alignment",
                reason="Semantic Contract requires filter on orders.status = 'completed'",
            )
        return SQLControlGateResult(allowed=True)

    # Initial failed SQL has a syntax error
    initial_sql = "SELECT SUM(amount) FRM orders"

    rows, final_sql, err, err_type, _ = await sql_generator.execute_with_repair(
        question="What is total sales for completed orders?",
        schema_text="orders(id INT, status VARCHAR, amount REAL, order_date DATE)",
        sql=initial_sql,
        db=session,
        max_fix_attempts=2,
        pre_execution_gate=mock_gate,
    )

    assert err is None
    assert "status = 'completed'" in final_sql
    assert len(rows) == 1
    assert rows[0]["SUM(amount)"] == 100.0

    session.close()
