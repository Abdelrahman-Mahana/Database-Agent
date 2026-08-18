import time
import pytest
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
from app.database.system_store import SystemStore
from app.schema_catalog.catalog_builder import CatalogBuilder
from app.database.context import DatabaseContext, db_context_manager


def create_mock_catalog(fp: str = "fp_auth_test") -> SchemaCatalog:
    cols_users = [
        ColumnProfile(name="user_id", type="INTEGER", primary_key=True),
        ColumnProfile(name="username", type="VARCHAR", synonyms=["handle", "account_name"]),
        ColumnProfile(name="email", type="VARCHAR"),
    ]
    cols_orders = [
        ColumnProfile(name="order_id", type="INTEGER", primary_key=True),
        ColumnProfile(name="user_id", type="INTEGER", is_foreign_key=True),
        ColumnProfile(name="amount", type="NUMERIC", synonyms=["price", "cost"]),
    ]

    tables = {
        "users": TableProfile(
            name="users",
            columns=cols_users,
            primary_key=["user_id"],
            description="Registered user accounts",
            synonyms=["accounts", "members"],
            profiled=True,
            last_profiled_at=time.time(),
            profile_status="profiled",
            row_count=1500,
        ),
        "orders": TableProfile(
            name="orders",
            columns=cols_orders,
            primary_key=["order_id"],
            foreign_keys=[{
                "constrained_columns": ["user_id"],
                "referred_table": "users",
                "referred_columns": ["user_id"],
            }],
            description="Customer order purchases",
            synonyms=["purchases", "invoices"],
            profiled=False,
            profile_status="unprofiled",
        ),
    }

    return SchemaCatalog(
        fingerprint=fp,
        dialect="sqlite",
        database_name="test_authoritative_db",
        tables=tables,
        built_at=time.time(),
        glossary_enriched=True,
        glossary_version=1,
    )


def test_system_store_normalized_catalog_persistence(tmp_path):
    """Verify that SystemStore saves and loads normalized catalog records across tables."""
    db_file = tmp_path / "test_sys_cat.db"
    store = SystemStore(db_url_or_path=f"sqlite:///{db_file}")

    catalog = create_mock_catalog(fp="fp_store_test")
    saved = store.save_normalized_catalog(catalog)
    assert saved is True

    # Verify loading full catalog from normalized records
    loaded = store.load_normalized_catalog("fp_store_test")
    assert loaded is not None
    assert loaded.fingerprint == "fp_store_test"
    assert loaded.database_name == "test_authoritative_db"
    assert len(loaded.tables) == 2
    assert "users" in loaded.tables
    assert "orders" in loaded.tables

    users_tbl = loaded.tables["users"]
    assert users_tbl.row_count == 1500
    assert users_tbl.profiled is True
    assert users_tbl.profile_status == "profiled"
    assert "accounts" in users_tbl.synonyms
    assert any(c.name == "username" and "handle" in c.synonyms for c in users_tbl.columns)


def test_independent_table_column_relationship_records(tmp_path):
    """Verify independent persistence and retrieval of table, column, and relationship records."""
    db_file = tmp_path / "test_indep.db"
    store = SystemStore(db_url_or_path=f"sqlite:///{db_file}")
    fp = "fp_indep_test"

    # 1. Independent connection record
    conn_rec = DatabaseConnectionRecord(
        connection_id="conn_test_01",
        database_name="InventoryDB",
        dialect="postgresql",
        fingerprint=fp,
        version="2.0",
        last_introspected_at=time.time(),
    )
    assert store.save_catalog_connection(conn_rec) is True
    fetched_conn = store.get_catalog_connection(fp)
    assert fetched_conn is not None
    assert fetched_conn.database_name == "InventoryDB"

    # 2. Independent schema object records
    obj_rec = SchemaObjectRecord(
        object_id=f"{fp}:products",
        fingerprint=fp,
        schema_name="public",
        object_name="products",
        object_type="table",
        row_count_estimate=5000,
        description="Catalog products",
        status="active",
        fk_degree=3,
        profile_status="unprofiled",
    )
    assert store.save_schema_objects([obj_rec]) is True
    objs = store.get_schema_objects(fp, table_names=["products"])
    assert len(objs) == 1
    assert objs[0].object_name == "products"
    assert objs[0].row_count_estimate == 5000

    # 3. Independent column records
    col_recs = [
        ColumnRecord(
            column_id=f"{fp}:products:sku",
            object_id=f"{fp}:products",
            fingerprint=fp,
            name="sku",
            data_type="VARCHAR",
            primary_key=True,
            samples=["SKU-001", "SKU-002"],
            synonyms=["product_code", "item_sku"],
        ),
        ColumnRecord(
            column_id=f"{fp}:products:price",
            object_id=f"{fp}:products",
            fingerprint=fp,
            name="price",
            data_type="NUMERIC",
            null_fraction=0.0,
            distinct_estimate=450,
        ),
    ]
    assert store.save_columns(col_recs) is True
    cols = store.get_columns_for_objects(fp, object_ids=[f"{fp}:products"])
    assert len(cols) == 2
    sku_col = next(c for c in cols if c.name == "sku")
    assert sku_col.primary_key is True
    assert "product_code" in sku_col.synonyms
    assert sku_col.samples == ["SKU-001", "SKU-002"]

    # 4. Independent relationship records
    rel_rec = RelationshipRecord(
        relationship_id=f"{fp}:rel_prod_cat",
        fingerprint=fp,
        source_object="products",
        source_column="category_id",
        target_object="categories",
        target_column="id",
        relationship_type="foreign_key",
        confidence=1.0,
    )
    assert store.save_relationships([rel_rec]) is True
    rels = store.get_relationships(fp)
    assert len(rels) == 1
    assert rels[0].source_object == "products"
    assert rels[0].target_object == "categories"


def test_independent_table_profile_stats_update(tmp_path):
    """Verify updating a single table's row count and column samples independently without full rewrite."""
    db_file = tmp_path / "test_prof_update.db"
    store = SystemStore(db_url_or_path=f"sqlite:///{db_file}")
    fp = "fp_prof_test"

    catalog = create_mock_catalog(fp=fp)
    store.save_normalized_catalog(catalog)

    # Initial state: orders is unprofiled
    orders_obj = store.get_schema_objects(fp, table_names=["orders"])[0]
    assert orders_obj.row_count_estimate is None
    assert orders_obj.profile_status == "unprofiled"

    # Independently profile orders table
    t_now = time.time()
    success = store.update_table_profile_stats(
        fingerprint=fp,
        table_name="orders",
        row_count=8920,
        column_stats={
            "amount": {
                "samples": ["19.99", "45.50", "120.00"],
                "distinct_estimate": 310,
                "null_fraction": 0.01,
            }
        },
        profiled_at=t_now,
    )
    assert success is True

    # Verify orders table updated in store
    updated_obj = store.get_schema_objects(fp, table_names=["orders"])[0]
    assert updated_obj.row_count_estimate == 8920
    assert updated_obj.profile_status == "profiled"
    assert updated_obj.last_profiled_at == pytest.approx(t_now, abs=1.0)

    # Verify column statistics updated
    updated_cols = store.get_columns_for_objects(fp, object_ids=[f"{fp}:orders"])
    amt_col = next(c for c in updated_cols if c.name == "amount")
    assert amt_col.samples == ["19.99", "45.50", "120.00"]
    assert amt_col.distinct_estimate == 310
    assert amt_col.null_fraction == 0.01


def test_explicit_catalog_versioning_and_freshness_tracking(tmp_path):
    """Verify explicit catalog version records and profile freshness report."""
    db_file = tmp_path / "test_versioning.db"
    store = SystemStore(db_url_or_path=f"sqlite:///{db_file}")
    fp = "fp_ver_test"

    catalog = create_mock_catalog(fp=fp)
    assert catalog.glossary_version == 1

    # Check initial freshness report
    report1 = catalog.get_freshness_report()
    assert report1["total_tables"] == 2
    assert report1["profiled_tables"] == 1
    assert report1["unprofiled_tables"] == 1
    assert report1["status"] == "partially_profiled"

    # Bump version upon glossary merge or full profiling
    ver_rec = catalog.bump_version(build_status="completed")
    assert catalog.glossary_version == 2
    assert ver_rec.version == 2
    assert ver_rec.profile_freshness_status == "partially_profiled"

    # Save to store
    store.save_catalog_version(ver_rec)
    latest = store.get_latest_catalog_version(fp)
    assert latest is not None
    assert latest.version == 2
    assert latest.profile_freshness_status == "partially_profiled"


def test_database_context_in_worker_cache_rehydration(tmp_path, monkeypatch):
    """Verify DatabaseContext behaves as an in-worker cache and rehydrates when store version advances."""
    db_file = tmp_path / "test_worker_cache.db"
    store = SystemStore(db_url_or_path=f"sqlite:///{db_file}")
    monkeypatch.setattr("app.database.system_store.system_store", store)
    monkeypatch.setattr("app.schema_catalog.catalog_builder.system_store", store)

    fp = "fp_cache_rehydrate_test"
    catalog_v1 = create_mock_catalog(fp=fp)
    store.save_normalized_catalog(catalog_v1)

    # Worker initializes DatabaseContext in RAM with v1
    ctx = DatabaseContext(
        fingerprint=fp,
        url="sqlite:///:memory:",
        schema={"users": {"columns": [{"name": "user_id", "type": "int"}]}},
        catalog=catalog_v1,
        catalog_version=1,
    )
    db_context_manager.set(fp, ctx)

    # Currently fresh against v1
    assert ctx.is_stale_against_version(1) is False
    assert ctx.is_stale_against_version(2) is True

    # Background worker or another node enriches glossary and bumps store version to v2
    catalog_v2 = create_mock_catalog(fp=fp)
    catalog_v2.tables["users"].description = "Updated VIP business accounts"
    catalog_v2.tables["users"].synonyms.append("vip_clients")
    catalog_v2.bump_version()
    store.save_normalized_catalog(catalog_v2)

    # Worker detects store version bumped and rehydrates RAM cache
    rehydrated = ctx.rehydrate_catalog_if_stale()
    assert rehydrated is True
    assert ctx.catalog_version == 2
    assert ctx.catalog.tables["users"].description == "Updated VIP business accounts"
    assert "vip_clients" in ctx.catalog.tables["users"].synonyms

    # Clean up RAM cache
    db_context_manager.clear()
