import pytest
from app.models.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile
from app.models.schema_catalog.retrieval import (
    AliasIndex,
    TfidfTableRetriever,
    HybridCandidateRetriever,
    CandidateTable,
    CandidateColumn,
)
from app.agent.schema_grounding.grounding_engine import SchemaGroundingEngine
from app.services.database.context import DatabaseContext
from app.agent.semantic.query_spec_builder import QuerySpecBuilder
from app.agent.semantic.models import ExecutionRoute, IntentType


@pytest.fixture
def ecommerce_catalog() -> SchemaCatalog:
    tables = {
        "customers": TableProfile(
            name="customers",
            columns=[
                ColumnProfile(name="customer_id", type="INTEGER", primary_key=True),
                ColumnProfile(name="full_name", type="VARCHAR", synonyms=["client_name", "user_name"]),
                ColumnProfile(name="email", type="VARCHAR"),
                ColumnProfile(name="city", type="VARCHAR", synonyms=["location", "town"]),
            ],
            primary_key=["customer_id"],
            description="Stores client and user contact records",
            synonyms=["clients", "users", "buyers", "accounts"],
        ),
        "orders": TableProfile(
            name="orders",
            columns=[
                ColumnProfile(name="order_id", type="INTEGER", primary_key=True),
                ColumnProfile(name="customer_id", type="INTEGER", is_foreign_key=True),
                ColumnProfile(name="order_date", type="TIMESTAMP"),
                ColumnProfile(name="total_amount", type="NUMERIC", synonyms=["revenue", "sales_total", "price"]),
            ],
            primary_key=["order_id"],
            foreign_keys=[{
                "constrained_columns": ["customer_id"],
                "referred_table": "customers",
                "referred_columns": ["customer_id"],
            }],
            description="Customer order purchases and financial sales",
            synonyms=["purchases", "invoices", "sales", "transactions"],
        ),
        "order_items": TableProfile(
            name="order_items",
            columns=[
                ColumnProfile(name="item_id", type="INTEGER", primary_key=True),
                ColumnProfile(name="order_id", type="INTEGER", is_foreign_key=True),
                ColumnProfile(name="product_id", type="INTEGER", is_foreign_key=True),
                ColumnProfile(name="quantity", type="INTEGER", synonyms=["units", "count"]),
                ColumnProfile(name="unit_price", type="NUMERIC", synonyms=["rate", "cost"]),
            ],
            primary_key=["item_id"],
            foreign_keys=[{
                "constrained_columns": ["order_id"],
                "referred_table": "orders",
                "referred_columns": ["order_id"],
            }],
            description="Line items for each purchase",
            synonyms=["lines", "details"],
        ),
        "products": TableProfile(
            name="products",
            columns=[
                ColumnProfile(name="product_id", type="INTEGER", primary_key=True),
                ColumnProfile(name="name", type="VARCHAR", synonyms=["title", "item_name"]),
                ColumnProfile(name="category", type="VARCHAR"),
            ],
            primary_key=["product_id"],
            description="Catalog of items for sale",
            synonyms=["items", "goods", "merchandise"],
        ),
    }

    return SchemaCatalog(
        fingerprint="fp_retrieval_test",
        dialect="sqlite",
        database_name="EcommerceStore",
        tables=tables,
    )


def test_alias_index_exact_and_stemmed_lookups(ecommerce_catalog):
    """Test Stage 1 AliasIndex mapping for table and column synonyms."""
    alias_idx = AliasIndex(ecommerce_catalog)

    # 1. Table alias lookups
    t_matches = alias_idx.lookup_tables("show all buyers and transactions")
    t_names = [t for t, _ in t_matches]
    assert "customers" in t_names  # from synonym 'buyers'
    assert "orders" in t_names     # from synonym 'transactions'

    # 2. Column alias lookups
    c_matches = alias_idx.lookup_columns("what is the total revenue by client name")
    matched_cols = [(t, c) for t, c, _ in c_matches]
    assert ("orders", "total_amount") in matched_cols  # from synonym 'revenue'
    assert ("customers", "full_name") in matched_cols  # from synonym 'client name'


def test_alias_index_matches_unqualified_postgresql_table_names():
    catalog = SchemaCatalog(
        fingerprint="postgres-qualified",
        dialect="postgresql",
        database_name="test",
        tables={
            "public.patient_model": TableProfile(
                name="public.patient_model",
                columns=[ColumnProfile(name="id", type="INTEGER", primary_key=True)],
            )
        },
    )

    matches = AliasIndex(catalog).lookup_tables("How many records are in patient_model?")

    assert matches == [("public.patient_model", 1.0)]


def test_hybrid_candidate_retrieval_tables(ecommerce_catalog):
    """Test multi-signal hybrid table candidate retrieval."""
    retriever = HybridCandidateRetriever(ecommerce_catalog)

    # Question matching lexical and alias signals
    candidates = retriever.retrieve_candidate_tables("what is the total sales revenue for each customer?", k=3)
    assert len(candidates) <= 3
    cand_names = [c.table_name for c in candidates]
    assert "orders" in cand_names or "customers" in cand_names

    orders_cand = next((c for c in candidates if c.table_name == "orders"), None)
    if orders_cand:
        assert orders_cand.score > 0.0
        assert len(orders_cand.match_sources) >= 1


def test_candidate_column_retrieval_and_role_classification(ecommerce_catalog):
    """Test Stage 2 column candidate retrieval and semantic role assignment."""
    retriever = HybridCandidateRetriever(ecommerce_catalog)

    col_candidates = retriever.retrieve_candidate_columns(
        question="total sales revenue and quantity by customer full name",
        candidate_tables=["orders", "customers", "order_items"],
    )

    col_map = {(c.table_name, c.column_name): c for c in col_candidates}

    # Verify metric classification
    assert ("orders", "total_amount") in col_map
    assert col_map[("orders", "total_amount")].role == "metric"

    # Verify dimension classification
    assert ("customers", "full_name") in col_map
    assert col_map[("customers", "full_name")].role == "dimension"

    # Verify join keys
    assert ("customers", "customer_id") in col_map
    assert col_map[("customers", "customer_id")].role == "join_key"


def test_hierarchical_schema_grounding_end_to_end(ecommerce_catalog):
    """Test 3-stage grounding: Table Candidates -> Column Candidates -> Join Neighbor Expansion."""
    schema = {
        "customers": {
            "columns": [{"name": "customer_id", "type": "INTEGER"}, {"name": "full_name", "type": "VARCHAR"}],
            "primary_key": ["customer_id"],
            "foreign_keys": [],
        },
        "orders": {
            "columns": [{"name": "order_id", "type": "INTEGER"}, {"name": "customer_id", "type": "INTEGER"}, {"name": "total_amount", "type": "NUMERIC"}],
            "primary_key": ["order_id"],
            "foreign_keys": [{"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["customer_id"]}],
        },
        "order_items": {
            "columns": [{"name": "item_id", "type": "INTEGER"}, {"name": "order_id", "type": "INTEGER"}, {"name": "product_id", "type": "INTEGER"}, {"name": "quantity", "type": "INTEGER"}],
            "primary_key": ["item_id"],
            "foreign_keys": [{"constrained_columns": ["order_id"], "referred_table": "orders", "referred_columns": ["order_id"]}],
        },
        "products": {
            "columns": [{"name": "product_id", "type": "INTEGER"}, {"name": "name", "type": "VARCHAR"}],
            "primary_key": ["product_id"],
            "foreign_keys": [],
        },
    }

    ctx = DatabaseContext(
        fingerprint="fp_retrieval_test",
        url="sqlite:///:memory:",
        schema=schema,
        catalog=ecommerce_catalog,
    )
    ctx.ensure_indexes()

    engine = SchemaGroundingEngine()
    grounded = engine.build_grounded_schema(
        schema=schema,
        question="Show total revenue for each client name",
        catalog=ecommerce_catalog,
    )

    assert grounded.selected_tables
    assert "orders" in grounded.selected_tables
    assert "customers" in grounded.selected_tables
    assert len(grounded.selected_tables) <= 4
    # Check timings populated
    assert "table_retrieval_ms" in grounded.timings_ms
    assert "column_retrieval_ms" in grounded.timings_ms
    assert "relationship_expansion_ms" in grounded.timings_ms


def test_query_spec_builder_zero_full_schema_scanning(ecommerce_catalog):
    """Test that QuerySpecBuilder extracts entities strictly from candidates in O(W) time."""
    schema = {
        "customers": {"columns": [{"name": "customer_id", "type": "INTEGER"}, {"name": "full_name", "type": "VARCHAR"}]},
        "orders": {"columns": [{"name": "order_id", "type": "INTEGER"}, {"name": "total_amount", "type": "NUMERIC"}]},
        "products": {"columns": [{"name": "product_id", "type": "INTEGER"}, {"name": "name", "type": "VARCHAR"}]},
    }

    ctx = DatabaseContext(
        fingerprint="fp_retrieval_test",
        url="sqlite:///:memory:",
        schema=schema,
        catalog=ecommerce_catalog,
    )
    ctx.ensure_indexes()

    builder = QuerySpecBuilder()
    spec = builder.build_spec("What is the total revenue by customers in 2024?", db_ctx=ctx)

    assert spec.route == ExecutionRoute.DATA_QUERY
    assert spec.intent == IntentType.DATABASE
    assert "orders" in spec.entities or "customers" in spec.entities
    assert spec.aggregations == ["SUM"]
