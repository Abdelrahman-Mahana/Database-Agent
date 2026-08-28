"""Tests for Grain Validation and Join Fan-Out / Duplicate Aggregation Prevention."""
import pytest
from app.agent.semantic.contract import (
    SemanticContract, GrainType, FormulaType, MetricSpec, DimensionSpec
)
from app.services.sql.semantic_validator import SQLMeaningValidator, sql_meaning_validator


@pytest.fixture
def ecommerce_schema():
    return {
        "customers": {
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "name", "type": "VARCHAR"},
                {"name": "country", "type": "VARCHAR"},
            ],
            "foreign_keys": [],
        },
        "orders": {
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "customer_id", "type": "INTEGER"},
                {"name": "total", "type": "FLOAT"},
            ],
            "foreign_keys": [
                {"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["id"]}
            ],
        },
        "order_items": {
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "order_id", "type": "INTEGER"},
                {"name": "quantity", "type": "INTEGER"},
                {"name": "price", "type": "FLOAT"},
            ],
            "foreign_keys": [
                {"constrained_columns": ["order_id"], "referred_table": "orders", "referred_columns": ["id"]}
            ],
        },
        "payments": {
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "customer_id", "type": "INTEGER"},
                {"name": "amount", "type": "FLOAT"},
            ],
            "foreign_keys": [
                {"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["id"]}
            ],
        },
    }


def test_fanout_defect_detected_when_parent_sum_joined_with_child(ecommerce_schema):
    """Verify that SUM(orders.total) joined directly to 1:N order_items is flagged as a Grain Fan-Out defect."""
    validator = SQLMeaningValidator()
    contract = SemanticContract(
        contract_id="c1",
        raw_question="What is our total revenue?",
        measures=[
            MetricSpec(
                metric_id="revenue",
                display_name="Total Revenue",
                formula_type=FormulaType.SUM,
                source_table="orders",
                source_column="total",
                expression="SUM(orders.total)",
            )
        ],
    )

    # Bad query: joins 1:N order_items, multiplying orders.total by the number of line items in each order!
    bad_sql = "SELECT SUM(orders.total) FROM orders JOIN order_items ON orders.id = order_items.order_id"

    passed, warnings = validator.validate_sql_meaning(
        sql=bad_sql,
        contract=contract,
        raw_schema=ecommerce_schema,
    )

    assert not passed
    assert any("Grain Fan-Out defect" in w for w in warnings)
    assert any("orders" in w and "order_items" in w for w in warnings)


def test_fanout_defect_detected_for_parent_avg_and_non_distinct_count(ecommerce_schema):
    """Verify that AVG(orders.total) and COUNT(orders.id) are also flagged when 1:N joined."""
    validator = SQLMeaningValidator()

    # 1. AVG fanout
    avg_sql = "SELECT AVG(orders.total) FROM orders JOIN order_items ON orders.id = order_items.order_id"
    passed_avg, warns_avg = validator.validate_sql_meaning(
        sql=avg_sql,
        contract=SemanticContract(contract_id="c_avg", raw_question="Average order total"),
        raw_schema=ecommerce_schema,
    )
    assert not passed_avg
    assert any("Grain Fan-Out defect" in w for w in warns_avg)

    # 2. Non-distinct COUNT fanout
    count_sql = "SELECT COUNT(orders.id) FROM orders JOIN order_items ON orders.id = order_items.order_id"
    passed_cnt, warns_cnt = validator.validate_sql_meaning(
        sql=count_sql,
        contract=SemanticContract(contract_id="c_cnt", raw_question="Count orders"),
        raw_schema=ecommerce_schema,
    )
    assert not passed_cnt
    assert any("Grain Fan-Out defect" in w for w in warns_cnt)


def test_chasm_trap_detected_when_parent_joined_to_multiple_1_to_n_children(ecommerce_schema):
    """Verify that joining parent customers with BOTH orders AND payments in the same query block is flagged as Chasm Trap."""
    validator = SQLMeaningValidator()

    chasm_sql = """
    SELECT customers.name, SUM(orders.total), SUM(payments.amount)
    FROM customers
    JOIN orders ON customers.id = orders.customer_id
    JOIN payments ON customers.id = payments.customer_id
    GROUP BY customers.name
    """

    passed, warnings = validator.validate_sql_meaning(
        sql=chasm_sql,
        contract=SemanticContract(contract_id="c_chasm", raw_question="Customer orders and payments"),
        raw_schema=ecommerce_schema,
    )

    assert not passed
    assert any("Chasm Trap defect" in w for w in warnings)
    assert any("Cartesian product" in w for w in warnings)


def test_safe_queries_pass_grain_and_fanout_validation(ecommerce_schema):
    """Verify that safe queries (e.g. single-table, COUNT DISTINCT, or pre-aggregated CTEs) pass validation cleanly."""
    validator = SQLMeaningValidator()

    contract = SemanticContract(
        contract_id="c_safe",
        raw_question="Total revenue",
        measures=[
            MetricSpec(
                metric_id="revenue",
                display_name="Total Revenue",
                formula_type=FormulaType.SUM,
                source_table="orders",
                source_column="total",
                expression="SUM(orders.total)",
            )
        ],
    )

    # 1. Single table query (no join)
    safe_single = "SELECT SUM(total) FROM orders"
    ok1, w1 = validator.validate_sql_meaning(safe_single, contract=contract, raw_schema=ecommerce_schema)
    assert ok1
    assert len(w1) == 0

    # 2. COUNT DISTINCT on parent ID
    safe_distinct_cnt = "SELECT COUNT(DISTINCT orders.id) FROM orders JOIN order_items ON orders.id = order_items.order_id"
    ok2, w2 = validator.validate_sql_meaning(
        safe_distinct_cnt,
        contract=SemanticContract(contract_id="c_cnt", raw_question="Count unique orders"),
        raw_schema=ecommerce_schema,
    )
    assert ok2

    # 3. CTE pre-aggregated child table (1:1 join with parent)
    safe_cte = """
    WITH item_summary AS (
        SELECT order_id, SUM(quantity * price) AS line_total
        FROM order_items
        GROUP BY order_id
    )
    SELECT SUM(orders.total), SUM(item_summary.line_total)
    FROM orders
    JOIN item_summary ON orders.id = item_summary.order_id
    """
    ok3, w3 = validator.validate_sql_meaning(safe_cte, contract=contract, raw_schema=ecommerce_schema)
    assert ok3
    assert len(w3) == 0


def test_scalar_grain_invariance_rejects_unaggregated_group_by(ecommerce_schema):
    """Verify that a scalar query (single total) rejects unrequested GROUP BY."""
    from app.agent.semantic.contract import SemanticGrain
    validator = SQLMeaningValidator()
    contract = SemanticContract(
        contract_id="c_scalar",
        raw_question="What is total revenue globally?",
        grain=SemanticGrain(grain_type=GrainType.SCALAR),
        measures=[
            MetricSpec(
                metric_id="revenue",
                display_name="Total Revenue",
                formula_type=FormulaType.SUM,
                source_table="orders",
                source_column="total",
                expression="SUM(orders.total)",
            )
        ],
    )

    # Bad query for scalar grain: has GROUP BY country returning multiple rows instead of single scalar
    bad_scalar_sql = "SELECT country, SUM(total) FROM orders JOIN customers ON orders.customer_id = customers.id GROUP BY country"

    passed, warnings = validator.validate_sql_meaning(
        sql=bad_scalar_sql,
        contract=contract,
        raw_schema=ecommerce_schema,
    )

    assert not passed
    assert any("Semantic Grain is SCALAR" in w for w in warnings)
