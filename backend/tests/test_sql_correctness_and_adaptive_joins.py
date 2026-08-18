import pytest
from app.sql.validator import SQLValidator
from app.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile
from app.semantic.models import QuerySpec, FilterCondition, SortCondition, IntentType, ExecutionRoute
from app.schema_grounding.relationship_graph import SchemaRelationshipGraph
from app.services.sql_service import SQLExecutor


@pytest.fixture
def test_catalog() -> SchemaCatalog:
    tables = {
        "customers": TableProfile(
            name="customers",
            columns=[
                ColumnProfile(name="customer_id", type="INTEGER", primary_key=True),
                ColumnProfile(name="name", type="VARCHAR"),
                ColumnProfile(name="city", type="VARCHAR"),
            ],
            primary_key=["customer_id"],
        ),
        "orders": TableProfile(
            name="orders",
            columns=[
                ColumnProfile(name="order_id", type="INTEGER", primary_key=True),
                ColumnProfile(name="customer_id", type="INTEGER", is_foreign_key=True),
                ColumnProfile(name="amount", type="NUMERIC"),
            ],
            primary_key=["order_id"],
            foreign_keys=[{"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["customer_id"]}],
        ),
        "order_items": TableProfile(
            name="order_items",
            columns=[
                ColumnProfile(name="item_id", type="INTEGER", primary_key=True),
                ColumnProfile(name="order_id", type="INTEGER", is_foreign_key=True),
                ColumnProfile(name="product_id", type="INTEGER", is_foreign_key=True),
                ColumnProfile(name="quantity", type="INTEGER"),
            ],
            primary_key=["item_id"],
            foreign_keys=[
                {"constrained_columns": ["order_id"], "referred_table": "orders", "referred_columns": ["order_id"]},
                {"constrained_columns": ["product_id"], "referred_table": "products", "referred_columns": ["product_id"]},
            ],
        ),
        "products": TableProfile(
            name="products",
            columns=[
                ColumnProfile(name="product_id", type="INTEGER", primary_key=True),
                ColumnProfile(name="name", type="VARCHAR"),
                ColumnProfile(name="price", type="NUMERIC"),
            ],
            primary_key=["product_id"],
        ),
    }
    return SchemaCatalog(
        fingerprint="fp_correctness",
        dialect="sqlite",
        database_name="TestDB",
        tables=tables,
    )


def test_identifier_grounding_valid_and_hallucinated(test_catalog):
    """Test AST identifier grounding for valid and hallucinated schema objects."""
    validator = SQLValidator()

    # 1. Valid query
    valid_sql = "SELECT c.name, o.amount FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE c.city = 'New York'"
    passed, warnings = validator.verify_sql_identifiers(valid_sql, catalog=test_catalog)
    assert passed is True
    assert len(warnings) == 0

    # 2. Hallucinated table
    bad_table_sql = "SELECT name, amount FROM non_existent_table"
    passed, warnings = validator.verify_sql_identifiers(bad_table_sql, catalog=test_catalog)
    assert passed is False
    assert any("Unrecognized table" in w for w in warnings)

    # 3. Hallucinated column
    bad_col_sql = "SELECT fake_column FROM customers"
    passed, warnings = validator.verify_sql_identifiers(bad_col_sql, catalog=test_catalog)
    assert passed is False
    assert any("fake_column" in w for w in warnings)


def test_identifier_grounding_with_ctes_and_derived_aliases(test_catalog):
    """Test that CTEs (WITH clause) and derived subquery aliases are properly grounded without false positives."""
    validator = SQLValidator()

    cte_sql = """
    WITH customer_totals AS (
        SELECT customer_id, SUM(amount) AS total_spent
        FROM orders
        GROUP BY customer_id
    )
    SELECT c.name, ct.total_spent
    FROM customers c
    JOIN customer_totals ct ON c.customer_id = ct.customer_id
    WHERE ct.total_spent > 100
    """
    passed, warnings = validator.verify_sql_identifiers(cte_sql, catalog=test_catalog)
    assert passed is True
    assert len(warnings) == 0


def test_query_spec_to_ast_semantic_alignment():
    """Test QuerySpec-to-AST semantic alignment for metrics, group by, filters, and limits."""
    validator = SQLValidator()

    # Spec requesting count and grouping by city with limit
    spec = QuerySpec(
        raw_question="How many customers by city top 5?",
        intent=IntentType.DATABASE,
        route=ExecutionRoute.DATA_QUERY,
        aggregations=["COUNT"],
        dimensions=["city"],
        limit=5,
        sorting=[SortCondition(direction="DESC")],
    )

    # 1. Matching valid SQL AST
    valid_sql = "SELECT city, COUNT(*) AS count FROM customers GROUP BY city ORDER BY count DESC LIMIT 5"
    passed, warnings = validator.verify_query_spec_alignment(valid_sql, query_spec=spec)
    assert passed is True
    assert len(warnings) == 0

    # 2. Missing GROUP BY when dimensions are requested
    no_group_sql = "SELECT city, COUNT(*) FROM customers LIMIT 5"
    passed, warnings = validator.verify_query_spec_alignment(no_group_sql, query_spec=spec)
    assert passed is False
    assert any("GROUP BY" in w for w in warnings)

    # 3. Missing LIMIT when limit is specified
    no_limit_sql = "SELECT city, COUNT(*) FROM customers GROUP BY city ORDER BY COUNT(*) DESC"
    passed, warnings = validator.verify_query_spec_alignment(no_limit_sql, query_spec=spec)
    assert passed is False
    assert any("LIMIT" in w for w in warnings)


def test_explain_plan_validation_without_live_execution():
    """Test SQLExecutor.explain plan checking on valid and invalid queries."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    executor = SQLExecutor()

    # 1. Valid query returns True with no error
    is_valid, err = executor.explain("SELECT id, username FROM users WHERE id = 1", db)
    assert is_valid is True
    assert err is None

    # 2. Query with syntax error fails plan check
    is_valid, err = executor.explain("SELECT FROM users WHERE", db)
    assert is_valid is False
    assert err is not None

    db.close()


def test_adaptive_join_expansion_preserves_bridge_tables():
    """Test that adaptive join expansion preserves all bridge/junction tables in multi-hop paths."""
    schema = {
        "customers": {
            "columns": [{"name": "customer_id", "type": "INT"}],
            "foreign_keys": [],
        },
        "orders": {
            "columns": [{"name": "order_id", "type": "INT"}, {"name": "customer_id", "type": "INT"}],
            "foreign_keys": [{"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["customer_id"]}],
        },
        "order_items": {
            "columns": [{"name": "item_id", "type": "INT"}, {"name": "order_id", "type": "INT"}, {"name": "product_id", "type": "INT"}],
            "foreign_keys": [
                {"constrained_columns": ["order_id"], "referred_table": "orders", "referred_columns": ["order_id"]},
                {"constrained_columns": ["product_id"], "referred_table": "products", "referred_columns": ["product_id"]},
            ],
        },
        "products": {
            "columns": [{"name": "product_id", "type": "INT"}],
            "foreign_keys": [],
        },
        # Unrelated distractor tables
        "logs": {"columns": [{"name": "log_id", "type": "INT"}], "foreign_keys": []},
        "settings": {"columns": [{"name": "k", "type": "TEXT"}], "foreign_keys": []},
    }

    graph = SchemaRelationshipGraph(schema)

    # Seed tables: customers and products (3-hop join: customers -> orders -> order_items -> products)
    seeds = {"customers", "products"}

    # Adaptive expansion must retain orders and order_items even with a tight budget
    connected = graph.get_adaptive_connecting_tables(seeds, max_budget=4, preserve_bridges=True)

    assert "customers" in connected
    assert "products" in connected
    assert "orders" in connected
    assert "order_items" in connected
    assert "logs" not in connected
    assert "settings" not in connected
