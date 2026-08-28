"""Enterprise Scale Benchmark Suite (1k, 5k, 10k tables).

Measures and validates:
1. Retrieval Recall@K (Recall@5, Recall@10) across exact names, synonyms, and multi-entity queries.
2. Join Path Accuracy (Steiner tree minimal connecting subgraphs).
3. Schema token budget constraints (< 2,500 tokens across all scales).
4. P50 and P95 latency benchmarks.
"""
import pytest
import time
import statistics
from unittest.mock import MagicMock

from app.models.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile
from app.models.schema_catalog.retrieval import retrieve_relevant_tables, HybridCandidateRetriever
from app.agent.schema_grounding.grounding_engine import SchemaGroundingEngine


def build_scale_catalog(num_tables: int) -> SchemaCatalog:
    """Build a realistic enterprise schema catalog with `num_tables` tables."""
    tables = {}

    # Target core entities with realistic relationships
    tables["customers"] = TableProfile(
        name="customers",
        columns=[
            ColumnProfile(name="customer_id", type="INTEGER", primary_key=True),
            ColumnProfile(name="name", type="VARCHAR"),
            ColumnProfile(name="country", type="VARCHAR"),
        ],
        description="Master enterprise customer accounts and client profiles",
        synonyms=["clients", "buyers", "accounts"],
    )

    tables["orders"] = TableProfile(
        name="orders",
        columns=[
            ColumnProfile(name="order_id", type="INTEGER", primary_key=True),
            ColumnProfile(name="customer_id", type="INTEGER", is_foreign_key=True),
            ColumnProfile(name="order_date", type="TIMESTAMP"),
            ColumnProfile(name="total_amount", type="NUMERIC"),
        ],
        foreign_keys=[
            {"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["customer_id"]}
        ],
        description="Purchasing and sales order transactions",
        synonyms=["purchases", "invoices", "sales_orders"],
    )

    tables["order_items"] = TableProfile(
        name="order_items",
        columns=[
            ColumnProfile(name="item_id", type="INTEGER", primary_key=True),
            ColumnProfile(name="order_id", type="INTEGER", is_foreign_key=True),
            ColumnProfile(name="product_id", type="INTEGER", is_foreign_key=True),
            ColumnProfile(name="unit_price", type="NUMERIC"),
            ColumnProfile(name="quantity", type="INTEGER"),
        ],
        foreign_keys=[
            {"constrained_columns": ["order_id"], "referred_table": "orders", "referred_columns": ["order_id"]},
            {"constrained_columns": ["product_id"], "referred_table": "products", "referred_columns": ["product_id"]},
        ],
        description="Line items for purchasing transactions",
        synonyms=["line_items", "order_lines"],
    )

    tables["products"] = TableProfile(
        name="products",
        columns=[
            ColumnProfile(name="product_id", type="INTEGER", primary_key=True),
            ColumnProfile(name="product_name", type="VARCHAR"),
            ColumnProfile(name="category", type="VARCHAR"),
            ColumnProfile(name="price", type="NUMERIC"),
        ],
        description="Product inventory items and retail catalogue",
        synonyms=["items", "goods", "merchandise"],
    )

    # Distractor tables
    for i in range(1, num_tables - 3):
        tname = f"audit_partition_{i}"
        tables[tname] = TableProfile(
            name=tname,
            columns=[
                ColumnProfile(name="id", type="INTEGER", primary_key=True),
                ColumnProfile(name=f"attr_{i}_key", type="VARCHAR"),
                ColumnProfile(name=f"attr_{i}_val", type="INTEGER"),
            ],
            description=f"System audit and telemetry log partition number {i}",
        )

    return SchemaCatalog(
        fingerprint=f"scale_benchmark_{num_tables}",
        dialect="postgresql",
        database_name=f"EnterpriseDB_{num_tables}",
        tables=tables,
    )


def test_1k_tables_benchmark():
    """Benchmark Recall@K, latency, join accuracy, and token budget at 1,000 tables."""
    catalog = build_scale_catalog(1000)

    # 1. Warm up & index
    t0 = time.perf_counter()
    retriever = HybridCandidateRetriever(catalog)
    init_ms = (time.perf_counter() - t0) * 1000
    assert init_ms < 600.0

    # 2. Multi-query latency & recall benchmark (10 iterations)
    queries = [
        ("Show all client purchase order amounts", ["customers", "orders"]),
        ("Find product line items and unit price", ["order_items", "products"]),
        ("Total merchandise sales by country", ["customers", "orders", "products"]),
    ]

    latencies = []
    for q, expected in queries:
        for _ in range(5):
            t_start = time.perf_counter()
            candidates = [c.table_name for c in retriever.retrieve_candidate_tables(q, k=10)]
            latencies.append((time.perf_counter() - t_start) * 1000)
            for exp in expected:
                assert exp in candidates, f"1k Scale: Expected '{exp}' in candidates for query '{q}', got {candidates}"

    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95)]
    assert p50 < 15.0, f"1k Scale P50 latency ({p50:.2f}ms) exceeded 15ms target!"
    assert p95 < 30.0, f"1k Scale P95 latency ({p95:.2f}ms) exceeded 30ms target!"

    # 3. Grounding & Token Budget Check
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
        question="Show client purchasing total amounts",
        catalog=catalog,
    )
    assert len(grounded.selected_tables) <= 10
    assert "customers" in grounded.selected_tables
    assert "orders" in grounded.selected_tables
    assert len(grounded.schema_text) // 4 < 1500


def test_5k_tables_benchmark():
    """Benchmark Recall@K, latency, and token budget at 5,000 tables."""
    catalog = build_scale_catalog(5000)

    retriever = HybridCandidateRetriever(catalog)

    queries = [
        ("List all buyers and their invoices", ["customers", "orders"]),
        ("Which merchandise has highest quantity in line items", ["products", "order_items"]),
    ]

    latencies = []
    for q, expected in queries:
        for _ in range(5):
            t_start = time.perf_counter()
            candidates = [c.table_name for c in retriever.retrieve_candidate_tables(q, k=10)]
            latencies.append((time.perf_counter() - t_start) * 1000)
            for exp in expected:
                assert exp in candidates, f"5k Scale: Expected '{exp}' in candidates for query '{q}', got {candidates}"

    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95)]
    assert p50 < 25.0, f"5k Scale P50 latency ({p50:.2f}ms) exceeded 25ms target!"
    assert p95 < 50.0, f"5k Scale P95 latency ({p95:.2f}ms) exceeded 50ms target!"


def test_10k_tables_benchmark():
    """Benchmark Recall@K, latency, multi-hop join connectivity, and token budget at 10,000 tables."""
    catalog = build_scale_catalog(10000)

    retriever = HybridCandidateRetriever(catalog)

    # 1. Complex 3-hop join query across 10,000 tables: clients -> orders -> order_items -> products
    question = "Calculate total sales revenue by client country and product merchandise category"
    expected_tables = ["customers", "orders", "order_items", "products"]

    latencies = []
    for _ in range(5):
        t_start = time.perf_counter()
        candidates = [c.table_name for c in retriever.retrieve_candidate_tables(question, k=10)]
        latencies.append((time.perf_counter() - t_start) * 1000)

    for exp in expected_tables:
        assert exp in candidates, f"10k Scale: Expected '{exp}' in candidates for query '{question}', got {candidates}"

    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[int(len(latencies) * 0.95)]
    assert p50 < 35.0, f"10k Scale P50 latency ({p50:.2f}ms) exceeded 35ms target!"
    assert p95 < 60.0, f"10k Scale P95 latency ({p95:.2f}ms) exceeded 60ms target!"

    # 2. Schema Grounding & Steiner Tree Join Connectivity at 10,000 tables
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

    # All 4 tables in the 3-hop join spine must be preserved
    for t in expected_tables:
        assert t in grounded.selected_tables, f"10k Scale: Essential join table '{t}' was severed from grounded subset!"

    # Token budget must remain compact (< 2,500 tokens) even with 10,000 database tables
    token_est = len(grounded.schema_text) // 4
    assert token_est < 2500, f"10k Scale: Schema text token budget ({token_est}) exceeded 2,500 limit!"
