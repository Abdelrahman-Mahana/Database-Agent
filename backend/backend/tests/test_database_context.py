import time
import pytest
from sqlalchemy import create_engine

from app.database.context import (
    DatabaseContext,
    DatabaseContextManager,
    compute_db_fingerprint,
    db_context_manager,
)
from app.services.sql_service import SchemaService


def test_compute_db_fingerprint():
    engine1 = create_engine("sqlite:///:memory:")
    engine2 = create_engine("sqlite:///:memory:")

    fp1 = compute_db_fingerprint(engine1)
    fp2 = compute_db_fingerprint(engine2)
    assert fp1 == fp2
    assert len(fp1) == 64


def test_database_context_lifecycle():
    ctx = DatabaseContext(
        fingerprint="fp_test_123",
        url="sqlite:///:memory:",
        dialect="sqlite",
        database_name="TestDB",
        schema={"users": {"columns": [{"name": "id", "type": "int"}]}},
        ttl=10,
    )
    assert not ctx.is_expired()
    assert "users" in ctx.get_table_summary()

    old_access = ctx.last_accessed_at
    time.sleep(0.01)
    ctx.touch()
    assert ctx.last_accessed_at > old_access


def test_database_context_manager_lru_and_invalidation():
    mgr = DatabaseContextManager(capacity=2)

    ctx1 = DatabaseContext(fingerprint="fp1", url="sqlite:///1.db")
    ctx2 = DatabaseContext(fingerprint="fp2", url="sqlite:///2.db")
    ctx3 = DatabaseContext(fingerprint="fp3", url="sqlite:///3.db")

    mgr.set("fp1", ctx1)
    mgr.set("fp2", ctx2)
    assert mgr.count() == 2
    assert mgr.get("fp1") is not None
    assert mgr.get("fp2") is not None

    # Adding 3rd should evict the oldest accessed (fp1 was accessed, so fp2 is older or fp1 was touched)
    mgr.get("fp1")  # touches fp1, making fp2 least recently used
    mgr.set("fp3", ctx3)
    assert mgr.count() == 2
    assert mgr.get("fp1") is not None
    assert mgr.get("fp3") is not None
    assert mgr.get("fp2") is None  # evicted

    # Invalidate
    mgr.invalidate("fp1")
    assert mgr.get("fp1") is None
    assert mgr.count() == 1

    # Clear
    mgr.clear()
    assert mgr.count() == 0


def test_schema_service_database_context_integration():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        from sqlalchemy import text
        conn.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price REAL);"))
        conn.commit()

    service = SchemaService(bind_engine=engine)
    fp = service._get_db_fingerprint()

    # Clear RAM and persistent cache first
    db_context_manager.invalidate(fp)
    from app.database.system_store import system_store
    system_store.clear_schema_cache()

    # First call: populates DatabaseContext in RAM
    ctx1 = service.get_database_context()
    assert ctx1 is not None
    assert "products" in ctx1.schema
    assert ctx1.relationship_graph is not None

    # Second call: instant RAM hit (same object)
    ctx2 = service.get_database_context()
    assert ctx1 is ctx2

    # SchemaService.get_schema_with_timing() also hits RAM instantly
    schema, hit, lookup_ms, disc_ms = service.get_schema_with_timing()
    assert hit is True
    assert "products" in schema
    assert lookup_ms < 5.0  # sub-millisecond to few ms


def test_prebuilt_indexes_and_fast_matching():
    schema = {
        "customers": {
            "columns": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "first_name", "type": "varchar"},
                {"name": "country", "type": "varchar"},
            ],
            "primary_key": ["id"],
            "foreign_keys": [],
        },
        "orders": {
            "columns": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "customer_id", "type": "int"},
                {"name": "total_amount", "type": "float"},
            ],
            "primary_key": ["id"],
            "foreign_keys": [
                {"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["id"]}
            ],
        }
    }

    ctx = DatabaseContext(
        fingerprint="fp_orders_customers",
        url="sqlite:///:memory:",
        schema=schema,
    )
    # 1. Build indexes once ahead of time
    ctx.ensure_indexes()
    assert ctx.indexes_built is True
    assert ctx.relationship_graph is not None
    assert "orders" in ctx.keyword_to_tables.get("order", set()) or "orders" in ctx.keyword_to_tables.get("orders", set())
    assert "customers" in ctx.keyword_to_tables.get("customer", set()) or "customers" in ctx.keyword_to_tables.get("customers", set())

    # 2. Match seed tables in 0ms without rebuilding
    seeds = ctx.match_seed_tables_fast("What is the total amount for customer in country Germany?")
    assert "orders" in seeds or "customers" in seeds


def test_tfidf_and_faiss_in_ram_caching():
    from app.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile
    from app.schema_catalog.embedding_retrieval import _FAISS_RAM_CACHE, clear_faiss_ram_cache

    clear_faiss_ram_cache()

    catalog = SchemaCatalog(
        fingerprint="fp_ram_test",
        dialect="sqlite",
        database_name="test_db",
        tables={
            "users": TableProfile(
                name="users",
                description="user accounts",
                columns=[ColumnProfile(name="id", type="int"), ColumnProfile(name="email", type="varchar")],
            )
        },
    )

    ctx = DatabaseContext(
        fingerprint="fp_ram_test",
        url="sqlite:///:memory:",
        schema={"users": {"columns": [{"name": "id", "type": "int"}, {"name": "email", "type": "varchar"}]}},
        catalog=catalog,
    )

    ctx.ensure_indexes()
    # Check that TF-IDF retriever was instantiated and cached in RAM
    assert ctx.tfidf_retriever is not None
    # Check that keyword index was computed
    assert "users" in ctx.keyword_to_tables
    assert ctx.indexes_built is True

    # Second call to ensure_indexes is a no-op that reuses in-RAM instances
    ctx.ensure_indexes(force=False)
    assert ctx.tfidf_retriever is not None


def test_cold_start_local_store_cache_loading_without_recursion(monkeypatch):
    """Verify that loading from SQLite system store on cold start does not cause recursion errors."""
    from app.database.system_store import system_store
    from app.services.sql_service import SchemaCacheEntry

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        from sqlalchemy import text
        conn.execute(text("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);"))
        conn.commit()

    service = SchemaService(bind_engine=engine)
    fp = service._get_db_fingerprint()

    # Pre-populate local SQLite store with a schema entry
    fake_entry = SchemaCacheEntry(
        schema={"customers": {"columns": [{"name": "id", "type": "INTEGER"}, {"name": "name", "type": "TEXT"}]}},
        schema_text="Table customers (id INTEGER, name TEXT)",
        fingerprint=fp,
        timestamp=time.time(),
    )
    system_store.set_schema_cache(fp, fake_entry.to_dict())

    # Clear RAM cache to simulate a fresh cold start
    db_context_manager.clear()

    # _get_valid_entry must succeed without hitting recursion limits
    entry = service._get_valid_entry()
    assert entry is not None
    assert "customers" in entry.schema

    # DatabaseContext should be loaded and indexed in RAM
    ctx = db_context_manager.get(fp)
    assert ctx is not None
    assert "customers" in ctx.schema

    # Clean up
    system_store.clear_schema_cache()
    db_context_manager.clear()


