import pytest
import sqlite3
from pathlib import Path
from app.schema_catalog.models import (
    SchemaCatalog,
    TableProfile,
    ColumnProfile,
    DatabaseConnectionRecord,
    SchemaObjectRecord,
    ColumnRecord,
    RelationshipRecord,
    IndexStatsRecord,
    AliasTermRecord,
    CatalogVersionRecord,
)
from app.schema_catalog.catalog_builder import CatalogBuilder
from app.schema_grounding.grounding_engine import SchemaGroundingEngine


def create_sample_catalog(fp="test_norm_fp") -> SchemaCatalog:
    """Create a sample SchemaCatalog with customer, orders, and order_items tables."""
    cols_cust = [
        ColumnProfile(name="customer_id", type="INTEGER", primary_key=True),
        ColumnProfile(name="name", type="TEXT", synonyms=["client_name"]),
        ColumnProfile(name="country", type="TEXT"),
    ]
    cols_orders = [
        ColumnProfile(name="order_id", type="INTEGER", primary_key=True),
        ColumnProfile(name="customer_id", type="INTEGER", is_foreign_key=True),
        ColumnProfile(name="total_amount", type="NUMERIC", synonyms=["grand_total"]),
    ]
    cols_items = [
        ColumnProfile(name="item_id", type="INTEGER", primary_key=True),
        ColumnProfile(name="order_id", type="INTEGER", is_foreign_key=True),
        ColumnProfile(name="product_name", type="TEXT"),
    ]

    tables = {
        "customers": TableProfile(
            name="customers",
            columns=cols_cust,
            primary_key=["customer_id"],
            description="All registered business clients",
            synonyms=["clients", "buyers"],
        ),
        "orders": TableProfile(
            name="orders",
            columns=cols_orders,
            primary_key=["order_id"],
            foreign_keys=[{
                "constrained_columns": ["customer_id"],
                "referred_table": "customers",
                "referred_columns": ["customer_id"],
            }],
            description="Purchases made by customers",
            synonyms=["sales", "invoices"],
        ),
        "order_items": TableProfile(
            name="order_items",
            columns=cols_items,
            primary_key=["item_id"],
            foreign_keys=[{
                "constrained_columns": ["order_id"],
                "referred_table": "orders",
                "referred_columns": ["order_id"],
            }],
            description="Individual line items in an order",
        ),
    }

    return SchemaCatalog(
        fingerprint=fp,
        dialect="sqlite",
        database_name="ecom_db",
        tables=tables,
        built_at=1234567.0,
        glossary_enriched=True,
        glossary_version=1,
    )


def test_schema_catalog_to_normalized_records():
    """Verify deconstruction of SchemaCatalog into 7 normalized entity types."""
    catalog = create_sample_catalog()
    records = catalog.to_normalized_records()

    assert "connection" in records
    assert "objects" in records
    assert "columns" in records
    assert "relationships" in records
    assert "indexes" in records
    assert "aliases" in records
    assert "version" in records

    assert len(records["objects"]) == 3
    assert len(records["columns"]) == 9  # 3 + 3 + 3
    assert len(records["relationships"]) == 2

    # Check aliases extracted from table and column synonyms
    alias_terms = {a.term for a in records["aliases"]}
    assert "clients" in alias_terms
    assert "grand_total" in alias_terms
    assert "client_name" in alias_terms


def test_schema_catalog_roundtrip_from_normalized_records():
    """Verify reconstruction of SchemaCatalog from normalized records."""
    catalog = create_sample_catalog()
    records = catalog.to_normalized_records()

    reconstructed = SchemaCatalog.from_normalized_records(
        connection=records["connection"][0],
        objects=records["objects"],
        columns=records["columns"],
        relationships=records["relationships"],
        indexes=records["indexes"],
        aliases=records["aliases"],
        version=records["version"][0],
        built_at=catalog.built_at,
    )

    assert reconstructed.fingerprint == catalog.fingerprint
    assert len(reconstructed.tables) == 3
    assert "customers" in reconstructed.tables
    assert "orders" in reconstructed.tables
    assert "order_items" in reconstructed.tables

    # Check column preservation
    cust = reconstructed.tables["customers"]
    assert len(cust.columns) == 3
    assert any(c.name == "customer_id" and c.primary_key for c in cust.columns)
    assert "clients" in cust.synonyms


def test_catalog_builder_normalized_persistence_and_loading(tmp_path, monkeypatch):
    """Verify CatalogBuilder saves to normalized SQLite tables and reloads properly."""
    monkeypatch.setattr("app.schema_catalog.catalog_builder.CATALOG_DIR", tmp_path)

    builder = CatalogBuilder()
    catalog = create_sample_catalog(fp="test_persist_fp")

    builder._save_to_disk(catalog)

    db_file = tmp_path / "test_persist_fp.db"
    assert db_file.exists()

    # Inspect SQLite database tables directly
    with sqlite3.connect(db_file) as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        table_names = {r[0] for r in cur.fetchall()}
        assert "catalog_database_connection" in table_names
        assert "catalog_schema_object" in table_names
        assert "catalog_column" in table_names
        assert "catalog_relationship" in table_names
        assert "catalog_alias_term" in table_names

        cur.execute("SELECT COUNT(*) FROM catalog_schema_object")
        assert cur.fetchone()[0] == 3

    # Load from disk
    loaded = builder._load_from_disk("test_persist_fp")
    assert loaded is not None
    assert loaded.fingerprint == "test_persist_fp"
    assert len(loaded.tables) == 3


def test_catalog_builder_selective_table_subset_loading(tmp_path, monkeypatch):
    """Verify load_table_subset loads only requested tables in O(K) time."""
    monkeypatch.setattr("app.schema_catalog.catalog_builder.CATALOG_DIR", tmp_path)

    builder = CatalogBuilder()
    catalog = create_sample_catalog(fp="test_subset_fp")
    builder._save_to_disk(catalog)

    # Request only 1 table ("customers")
    subset = builder.load_table_subset("test_subset_fp", ["customers"])
    assert len(subset) == 1
    assert "customers" in subset
    assert "orders" not in subset
    assert len(subset["customers"].columns) == 3


def test_two_stage_hybrid_retrieval_and_join_expansion():
    """Verify Stage 1 Candidate Retrieval + Stage 2 Steiner-Tree Join Neighborhood Expansion."""
    catalog = create_sample_catalog()

    # Stage 1: Candidate retrieval over synonym-enriched catalog
    from app.schema_catalog.retrieval import retrieve_relevant_tables
    question = "Show client names and product items"
    candidates = retrieve_relevant_tables(question, catalog, k=5)

    assert "customers" in candidates
    assert "order_items" in candidates

    # Stage 2: Join path expansion through intermediate bridge tables (Steiner Tree)
    from app.schema_grounding.relationship_graph import SchemaRelationshipGraph

    schema_dict = {
        t: {"foreign_keys": prof.foreign_keys}
        for t, prof in catalog.tables.items()
    }
    graph = SchemaRelationshipGraph(schema_dict)

    expanded_tables = graph.get_minimal_connecting_tables(seed_tables={"customers", "order_items"})

    assert "customers" in expanded_tables
    assert "order_items" in expanded_tables
    assert "orders" in expanded_tables, "Bridge table 'orders' must connect customers and order_items!"


