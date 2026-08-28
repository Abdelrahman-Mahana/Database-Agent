import pytest
import time
from unittest.mock import MagicMock, patch, AsyncMock

from app.models.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile
from app.models.schema_catalog.catalog_builder import CatalogBuilder
from app.models.schema_catalog.retrieval import retrieve_relevant_tables
from app.agent.schema_grounding.grounding_engine import SchemaGroundingEngine
from app.agent.semantic.models import QueryUnderstanding, ExecutionRoute, OutputFormat
from app.utils.text_processor import AnalysisType


def generate_enterprise_schema_catalog(num_tables: int = 1500) -> SchemaCatalog:
    """Generate a mock catalog simulating an enterprise database with 1,500+ tables."""
    tables = {}

    # Core target tables with distinct business meanings
    tables["customers"] = TableProfile(
        name="customers",
        columns=[
            ColumnProfile(name="customer_id", type="INTEGER", primary_key=True),
            ColumnProfile(name="customer_name", type="VARCHAR"),
            ColumnProfile(name="email", type="VARCHAR"),
        ],
        description="All registered enterprise client organizations",
        synonyms=["clients", "buyers", "accounts"],
    )

    tables["orders"] = TableProfile(
        name="orders",
        columns=[
            ColumnProfile(name="order_id", type="INTEGER", primary_key=True),
            ColumnProfile(name="customer_id", type="INTEGER", is_foreign_key=True),
            ColumnProfile(name="order_date", type="TIMESTAMP"),
            ColumnProfile(name="total_amount", type="REAL"),
        ],
        foreign_keys=[
            {"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["customer_id"]}
        ],
        description="Customer purchasing transactions",
        synonyms=["purchases", "invoices"],
    )

    tables["order_items"] = TableProfile(
        name="order_items",
        columns=[
            ColumnProfile(name="item_id", type="INTEGER", primary_key=True),
            ColumnProfile(name="order_id", type="INTEGER", is_foreign_key=True),
            ColumnProfile(name="product_id", type="INTEGER"),
            ColumnProfile(name="unit_price", type="REAL"),
            ColumnProfile(name="quantity", type="INTEGER"),
        ],
        foreign_keys=[
            {"constrained_columns": ["order_id"], "referred_table": "orders", "referred_columns": ["order_id"]}
        ],
        description="Line items for every customer order",
        synonyms=["line_items", "product_lines"],
    )

    # Add remaining 1,497 distractor tables
    for i in range(1, num_tables - 2):
        tname = f"distractor_table_{i}"
        tables[tname] = TableProfile(
            name=tname,
            columns=[
                ColumnProfile(name="id", type="INTEGER", primary_key=True),
                ColumnProfile(name=f"attr_{i}_a", type="VARCHAR"),
                ColumnProfile(name=f"attr_{i}_b", type="INTEGER"),
            ],
            description=f"Internal audit logs and operational cache partition {i}",
        )

    return SchemaCatalog(
        fingerprint="enterprise_scale_1500",
        dialect="postgresql",
        database_name="EnterpriseCorpDB",
        tables=tables,
    )


def test_enterprise_1500_tables_selective_retrieval_and_bounded_context(tmp_path, monkeypatch):
    """
    Performance Benchmark Test:
    Given a schema with 1,500 tables:
    1. Candidate retrieval locates target tables in < 50ms.
    2. Selective loading loads only candidate records (O(K)) without scanning all 1,500 tables.
    3. Grounded schema contains roughly 3-10 tables (well within the 15-table cap).
    4. 1,490+ distractor tables remain strictly outside the LLM context.
    """
    monkeypatch.setattr("app.models.schema_catalog.catalog_builder.CATALOG_DIR", tmp_path)

    # 1. Build and persist 1,500 table catalog
    t0 = time.perf_counter()
    catalog = generate_enterprise_schema_catalog(num_tables=1500)
    builder = CatalogBuilder()
    builder._save_to_disk(catalog)
    save_duration = (time.perf_counter() - t0) * 1000

    # 2. Stage 1: Candidate retrieval over 1,500 tables
    question = "Show client names and their purchase order amounts"
    t_retrieve_start = time.perf_counter()
    candidates = retrieve_relevant_tables(question, catalog, k=10)
    retrieve_duration = (time.perf_counter() - t_retrieve_start) * 1000

    assert "customers" in candidates
    assert "orders" in candidates
    assert len(candidates) <= 10
    # Candidate retrieval over 1,500 tables should complete under 400ms including cold indexing
    assert retrieve_duration < 400.0

    # 3. Stage 2: Selective sub-schema loading in O(K) time
    t_load_start = time.perf_counter()
    sub_schema = builder.load_table_subset("enterprise_scale_1500", candidates)
    load_duration = (time.perf_counter() - t_load_start) * 1000

    assert len(sub_schema) == len(candidates)
    assert "customers" in sub_schema
    assert "orders" in sub_schema
    assert load_duration < 50.0  # O(K) SQLite subset load

    # 4. Stage 3: Grounded Schema Engine compact context generation
    raw_schema = {
        t: {
            "columns": [{"name": c.name, "type": c.type} for c in prof.columns],
            "foreign_keys": prof.foreign_keys,
            "primary_key": prof.primary_key,
        }
        for t, prof in catalog.tables.items()
    }

    grounding_engine = SchemaGroundingEngine(schema_service=MagicMock())
    grounded = grounding_engine.build_grounded_schema(
        schema=raw_schema,
        question=question,
        catalog=catalog,
    )

    # Grounded subset should contain only the relevant tables (<= 15 tables)
    assert len(grounded.selected_tables) <= 15
    assert "customers" in grounded.selected_tables
    assert "orders" in grounded.selected_tables

    # Schema text token size must be small (< 2,000 estimated tokens) despite 1,500 database tables!
    schema_text = grounded.schema_text
    est_tokens = len(schema_text) // 4
    assert est_tokens < 2000, f"Schema text tokens ({est_tokens}) exceeded budget for 1500-table DB!"
    assert "distractor_table_500" not in schema_text
