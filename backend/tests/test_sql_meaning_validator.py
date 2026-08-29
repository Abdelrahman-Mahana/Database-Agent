"""Unit tests for SQL Meaning & Semantic Validator (SQLMeaningValidator).

Verifies deep AST semantic correctness rules:
1. Grain & Projection Invariance
2. Join Fan-Out & Aggregation Duplication Guard
3. Filter Value & Temporal Boundary Match
4. Sorting Direction & Superlative Alignment
5. Ratio & Formula Calculation Safety
"""
import pytest
from app.services.sql.semantic_validator import SQLMeaningValidator
from app.services.sql.validator import SQLValidator
from app.agent.semantic.models import (
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
from app.models.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile


@pytest.fixture
def meaning_validator():
    return SQLMeaningValidator()


@pytest.fixture
def mock_catalog():
    return SchemaCatalog(
        fingerprint="test_fp",
        dialect="sqlite",
        database_name="TestDB",
        tables={
            "customers": TableProfile(
                name="customers",
                columns=[
                    ColumnProfile(name="customer_id", type="INTEGER", primary_key=True),
                    ColumnProfile(name="customer_name", type="VARCHAR"),
                    ColumnProfile(name="country", type="VARCHAR"),
                ],
                foreign_keys=[],
            ),
            "orders": TableProfile(
                name="orders",
                columns=[
                    ColumnProfile(name="order_id", type="INTEGER", primary_key=True),
                    ColumnProfile(name="customer_id", type="INTEGER", is_foreign_key=True),
                    ColumnProfile(name="total_amount", type="REAL"),
                    ColumnProfile(name="freight", type="REAL"),
                    ColumnProfile(name="status", type="VARCHAR"),
                    ColumnProfile(name="order_date", type="DATE"),
                ],
                foreign_keys=[
                    {"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["customer_id"]}
                ],
            ),
            "order_items": TableProfile(
                name="order_items",
                columns=[
                    ColumnProfile(name="item_id", type="INTEGER", primary_key=True),
                    ColumnProfile(name="order_id", type="INTEGER", is_foreign_key=True),
                    ColumnProfile(name="product_id", type="INTEGER"),
                    ColumnProfile(name="quantity", type="INTEGER"),
                    ColumnProfile(name="unit_price", type="REAL"),
                ],
                foreign_keys=[
                    {"constrained_columns": ["order_id"], "referred_table": "orders", "referred_columns": ["order_id"]}
                ],
            ),
        },
    )


# -- Test 1: Grain & Projection Invariance -------------------------------------

def test_scalar_grain_rejects_unwanted_group_by(meaning_validator):
    """A scalar metric (e.g. Total Revenue) must not group by dimensions."""
    contract = SemanticContract(
        contract_id="c1",
        raw_question="What is the total revenue?",
        grain=SemanticGrain(grain_type=GrainType.SCALAR, description="Total Revenue"),
        measures=[
            MetricSpec(metric_id="rev", display_name="Total Revenue", formula_type=FormulaType.SUM, source_table="orders", source_column="total_amount")
        ],
    )

    # Valid scalar query
    ok_valid, warns_valid = meaning_validator.validate_sql_meaning(
        "SELECT SUM(total_amount) AS total_revenue FROM orders",
        contract=contract,
    )
    assert ok_valid is True
    assert len(warns_valid) == 0

    # Invalid: scalar request with unwanted GROUP BY
    ok_bad, warns_bad = meaning_validator.validate_sql_meaning(
        "SELECT customer_id, SUM(total_amount) AS total_revenue FROM orders GROUP BY customer_id",
        contract=contract,
    )
    assert ok_bad is False
    assert any("GROUP BY" in w for w in warns_bad)


def test_distinct_count_enforcement(meaning_validator):
    """When a metric requires unique/distinct count, COUNT(DISTINCT) must be used."""
    contract = SemanticContract(
        contract_id="c2",
        raw_question="How many unique customers made an order?",
        grain=SemanticGrain(grain_type=GrainType.SCALAR),
        measures=[
            MetricSpec(
                metric_id="uniq_cust",
                display_name="Unique Customers",
                formula_type=FormulaType.COUNT_DISTINCT,
                source_table="orders",
                source_column="customer_id",
                requires_distinct=True,
            )
        ],
    )

    # Valid: COUNT(DISTINCT customer_id)
    ok_valid, _ = meaning_validator.validate_sql_meaning(
        "SELECT COUNT(DISTINCT customer_id) FROM orders",
        contract=contract,
    )
    assert ok_valid is True

    # Invalid: COUNT(customer_id) which counts duplicates
    ok_bad, warns_bad = meaning_validator.validate_sql_meaning(
        "SELECT COUNT(customer_id) FROM orders",
        contract=contract,
    )
    assert ok_bad is False
    assert any("COUNT(DISTINCT" in w for w in warns_bad)


# -- Test 2: Join Fan-Out & Aggregation Duplication Guard ----------------------

def test_join_fanout_detects_parent_table_multiplication(meaning_validator, mock_catalog):
    """
    Joining orders (parent 1) to order_items (child N) and computing SUM(orders.total_amount)
    multiplies order totals by line item counts. Must be caught as fan-out risk.
    """
    contract = SemanticContract(
        contract_id="c3",
        raw_question="Total order revenue with item details",
        grain=SemanticGrain(grain_type=GrainType.SCALAR),
        measures=[
            MetricSpec(metric_id="rev", display_name="Revenue", formula_type=FormulaType.SUM, source_table="orders", source_column="total_amount")
        ],
    )

    # Dangerous fan-out query
    fanout_sql = (
        "SELECT SUM(o.total_amount) "
        "FROM orders o "
        "JOIN order_items oi ON o.order_id = oi.order_id"
    )
    ok_fanout, warns_fanout = meaning_validator.validate_sql_meaning(
        fanout_sql,
        contract=contract,
        catalog=mock_catalog,
    )
    assert ok_fanout is False
    assert any("Fan-out risk" in w for w in warns_fanout)

    # Safe query on child table metrics
    safe_sql = (
        "SELECT SUM(oi.unit_price * oi.quantity) "
        "FROM orders o "
        "JOIN order_items oi ON o.order_id = oi.order_id"
    )
    ok_safe, warns_safe = meaning_validator.validate_sql_meaning(
        safe_sql,
        contract=contract,
        catalog=mock_catalog,
    )
    assert ok_safe is True
    assert len(warns_safe) == 0


# -- Test 3: Filter & Temporal Semantics ---------------------------------------

def test_filter_semantics_enforces_mandatory_predicates_and_literals(meaning_validator):
    """Mandatory filters (e.g. status = 'completed') must be in WHERE clause with exact values."""
    contract = SemanticContract(
        contract_id="c4",
        raw_question="Total revenue of completed orders",
        grain=SemanticGrain(grain_type=GrainType.SCALAR),
        measures=[MetricSpec(metric_id="rev", formula_type=FormulaType.SUM, source_table="orders", source_column="total_amount")],
        filters=[
            FilterSpec(
                concept="status",
                target_table="orders",
                target_column="status",
                operator=FilterOperator.EQ,
                normalized_value="completed",
                is_mandatory=True,
            )
        ],
    )

    # Valid: includes WHERE status = 'completed'
    ok_valid, _ = meaning_validator.validate_sql_meaning(
        "SELECT SUM(total_amount) FROM orders WHERE status = 'completed'",
        contract=contract,
    )
    assert ok_valid is True

    # Invalid: missing WHERE clause entirely
    ok_missing_where, warns_no_where = meaning_validator.validate_sql_meaning(
        "SELECT SUM(total_amount) FROM orders",
        contract=contract,
    )
    assert ok_missing_where is False
    assert any("mandatory filter on 'status'" in w for w in warns_no_where)

    # Invalid: wrong status value ('pending' instead of 'completed')
    ok_wrong_val, warns_wrong_val = meaning_validator.validate_sql_meaning(
        "SELECT SUM(total_amount) FROM orders WHERE status = 'pending'",
        contract=contract,
    )
    assert ok_wrong_val is False
    assert any("completed" in w for w in warns_wrong_val)


def test_temporal_boundary_enforcement(meaning_validator):
    """TimeSpec boundaries (e.g. in 2023) must be present in SQL filter clauses."""
    contract = SemanticContract(
        contract_id="c5",
        raw_question="Total sales in 2023",
        grain=SemanticGrain(grain_type=GrainType.SCALAR),
        measures=[MetricSpec(metric_id="rev", formula_type=FormulaType.SUM, source_table="orders", source_column="total_amount")],
        time_spec=TimeSpec(
            time_column="order_date",
            source_table="orders",
            start_date="2023-01-01",
            end_date="2023-12-31",
        ),
    )

    # Valid: filters on 2023
    ok_valid, _ = meaning_validator.validate_sql_meaning(
        "SELECT SUM(total_amount) FROM orders WHERE order_date BETWEEN '2023-01-01' AND '2023-12-31'",
        contract=contract,
    )
    assert ok_valid is True

    # Invalid: no date filter (queries all time)
    ok_no_time, warns_no_time = meaning_validator.validate_sql_meaning(
        "SELECT SUM(total_amount) FROM orders",
        contract=contract,
    )
    assert ok_no_time is False
    assert any("temporal scope" in w for w in warns_no_time)


# -- Test 4: Sorting Direction & Superlatives ----------------------------------

def test_sorting_direction_superlative_alignment(meaning_validator):
    """Top/Highest queries must order DESC; ASC is an inverted meaning defect."""
    contract = SemanticContract(
        contract_id="c6",
        raw_question="Top 5 highest spending customers",
        grain=SemanticGrain(grain_type=GrainType.ENTITY_GRAIN),
        measures=[MetricSpec(metric_id="rev", formula_type=FormulaType.SUM, source_table="orders", source_column="total_amount")],
        dimensions=[DimensionSpec(dimension_id="customer_name", source_table="customers", source_column="customer_name")],
        sorting=[SortSpec(target="rev", direction="DESC", is_metric=True)],
        limit=5,
    )

    # Valid: ORDER BY total DESC LIMIT 5
    ok_valid, _ = meaning_validator.validate_sql_meaning(
        "SELECT customer_name, SUM(total_amount) AS total FROM orders JOIN customers ON orders.customer_id = customers.customer_id GROUP BY customer_name ORDER BY total DESC LIMIT 5",
        contract=contract,
    )
    assert ok_valid is True

    # Invalid: ORDER BY total ASC LIMIT 5 (returns lowest 5 instead of top 5!)
    ok_inverted, warns_inverted = meaning_validator.validate_sql_meaning(
        "SELECT customer_name, SUM(total_amount) AS total FROM orders JOIN customers ON orders.customer_id = customers.customer_id GROUP BY customer_name ORDER BY total ASC LIMIT 5",
        contract=contract,
    )
    assert ok_inverted is False
    assert any("Sorting direction mismatch" in w for w in warns_inverted)


# -- Test 5: Full SQLValidator Correctness Integration -------------------------

def test_full_sql_validator_correctness_suite(mock_catalog):
    """Test SQLValidator.validate_sql_correctness runs safety, identifiers, joins, and meaning."""
    validator = SQLValidator()
    contract = SemanticContract(
        contract_id="c7",
        raw_question="Top 3 countries by total revenue in 2023",
        grain=SemanticGrain(grain_type=GrainType.MULTIDIMENSIONAL),
        measures=[MetricSpec(metric_id="rev", formula_type=FormulaType.SUM, source_table="orders", source_column="total_amount")],
        dimensions=[DimensionSpec(dimension_id="country", source_table="customers", source_column="country")],
        filters=[FilterSpec(concept="status", target_table="orders", target_column="status", operator=FilterOperator.EQ, normalized_value="paid")],
        time_spec=TimeSpec(time_column="order_date", start_date="2023-01-01", end_date="2023-12-31"),
        sorting=[SortSpec(target="rev", direction="DESC")],
        limit=3,
    )


    # Completely correct query
    good_sql = (
        "SELECT c.country, SUM(o.total_amount) AS revenue "
        "FROM orders o "
        "JOIN customers c ON o.customer_id = c.customer_id "
        "WHERE o.status = 'paid' AND o.order_date >= '2023-01-01' AND o.order_date <= '2023-12-31' "
        "GROUP BY c.country "
        "ORDER BY revenue DESC "
        "LIMIT 3"
    )
    res_good = validator.validate_sql_correctness(
        good_sql,
        catalog=mock_catalog,
        query_spec=contract,
    )
    assert res_good["valid"] is True
    assert len(res_good["warnings"]) == 0

    # Query with semantic defect: missing status filter & ordering ASC
    bad_sql = (
        "SELECT c.country, SUM(o.total_amount) AS revenue "
        "FROM orders o "
        "JOIN customers c ON o.customer_id = c.customer_id "
        "WHERE o.order_date >= '2023-01-01' "
        "GROUP BY c.country "
        "ORDER BY revenue ASC "
        "LIMIT 3"
    )
    res_bad = validator.validate_sql_correctness(
        bad_sql,
        catalog=mock_catalog,
        query_spec=contract,
    )
    assert res_bad["valid"] is False
    assert any("status" in w for w in res_bad["warnings"])
    assert any("Sorting direction" in w for w in res_bad["warnings"])


def test_parse_failure_is_fail_closed_across_all_verifiers(mock_catalog):
    """
    When SQL syntax is invalid and cannot be parsed into an AST, all verification stages
    must fail-closed (return valid=False and warnings) rather than silently returning True.
    """
    validator = SQLValidator()
    meaning_validator = SQLMeaningValidator()
    contract = SemanticContract(
        contract_id="c_fail_closed",
        raw_question="Total sales by country",
        grain=SemanticGrain(grain_type=GrainType.SCALAR),
        measures=[MetricSpec(metric_id="rev", formula_type=FormulaType.SUM, source_table="orders", source_column="total_amount")],
    )

    invalid_sql = "SELECT FROM WHERE GROUP BY ORDER BY (((( INVALID SYNTAX $$$%"

    # 1. verify_sql_identifiers must fail-closed
    id_ok, id_warn = validator.verify_sql_identifiers(invalid_sql, catalog=mock_catalog)
    assert id_ok is False
    assert any("parse error" in w.lower() or "syntax" in w.lower() for w in id_warn)

    # 2. verify_sql_joins must fail-closed
    join_ok, join_warn = validator.verify_sql_joins(invalid_sql, catalog=mock_catalog)
    assert join_ok is False
    assert any("parse error" in w.lower() for w in join_warn)

    # 3. verify_semantic_contract_alignment must fail-closed
    align_ok, align_warn = validator.verify_semantic_contract_alignment(invalid_sql, contract=contract)
    assert align_ok is False
    assert any("parse error" in w.lower() for w in align_warn)

    # 4. validate_sql_meaning must fail-closed
    meaning_ok, meaning_warn = meaning_validator.validate_sql_meaning(invalid_sql, contract=contract)
    assert meaning_ok is False
    assert any("parse error" in w.lower() for w in meaning_warn)

    # 5. Full validate_sql_correctness must fail-closed
    res = validator.validate_sql_correctness(invalid_sql, catalog=mock_catalog, query_spec=contract)
    assert res["valid"] is False
    assert res["identifiers_valid"] is False
    assert res["joins_valid"] is False
    assert res["alignment_valid"] is False

