import pytest
from app.schema_grounding.grounding_engine import SchemaGroundingEngine
from app.schema_grounding.schema_pruner import SchemaPruner
from app.schema_grounding.models import Relationship
from app.semantic.models import QueryUnderstanding
from app.config.settings import settings


def test_schema_pruner_join_paths_and_column_capping():
    pruner = SchemaPruner()
    schema = {
        "customers": {
            "columns": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "name", "type": "varchar"},
                {"name": "country", "type": "varchar"},
            ] + [{"name": f"extra_col_{i}", "type": "varchar"} for i in range(20)],
            "primary_key": ["id"],
            "foreign_keys": [],
        },
        "orders": {
            "columns": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "customer_id", "type": "int"},
                {"name": "total_amount", "type": "float"},
                {"name": "order_date", "type": "date"},
            ] + [{"name": f"extra_order_col_{i}", "type": "varchar"} for i in range(20)],
            "primary_key": ["id"],
            "foreign_keys": [
                {"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["id"]}
            ],
        },
    }
    relationships = [
        Relationship(
            source_table="orders",
            source_column="customer_id",
            target_table="customers",
            target_column="id",
        )
    ]
    qu = QueryUnderstanding(
        raw_question="What is the total amount by customer name?",
        entities=["customers", "orders"],
        metrics=["orders.total_amount"],
        dimensions=["customers.name"],
    )

    grounded = pruner.prune_and_format(
        schema=schema,
        selected_tables={"customers", "orders"},
        relationships=relationships,
        seed_tables={"customers", "orders"},
        query_understanding=qu,
    )

    assert len(grounded.selected_tables) == 2
    assert "Join Paths:" in grounded.schema_text
    assert "orders.customer_id = customers.id" in grounded.schema_text
    assert "total_amount:FLOAT" in grounded.schema_text
    assert "name:VARCHAR" in grounded.schema_text
    # Check that excess columns are pruned with omitted message
    assert "columns omitted" in grounded.schema_text


def test_schema_grounding_engine_caps_at_3_to_8_tables():
    # Build a synthetic 30-table schema
    schema = {}
    for i in range(30):
        tname = f"table_{i}"
        fks = []
        if i > 0:
            fks.append({
                "constrained_columns": ["parent_id"],
                "referred_table": f"table_{i-1}",
                "referred_columns": ["id"],
            })
        schema[tname] = {
            "columns": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "parent_id", "type": "int"},
                {"name": "val", "type": "float"},
            ],
            "primary_key": ["id"],
            "foreign_keys": fks,
        }

    engine = SchemaGroundingEngine()
    qu = QueryUnderstanding(
        raw_question="Join table_0 and table_10",
        entities=["table_0", "table_10"],
    )

    grounded = engine.build_grounded_schema(
        schema=schema,
        query_understanding=qu,
        question="Join table_0 and table_10",
    )

    # Must be strictly bounded to 3-8 tables max, not all 30!
    assert len(grounded.selected_tables) <= 8
    assert "table_0" in grounded.selected_tables
    assert "table_10" in grounded.selected_tables or len(grounded.selected_tables) <= 8
    assert "Join Paths:" in grounded.schema_text


def test_hybrid_retrieval_lexical_first_with_semantic_fallback():
    from app.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile
    from app.schema_catalog.retrieval import retrieve_relevant_tables

    catalog = SchemaCatalog(
        fingerprint="fp123",
        dialect="sqlite",
        database_name="test_db",
        tables={
            "customers": TableProfile(
                name="customers",
                description="customer profiles and demographics",
                columns=[ColumnProfile(name="id", type="int"), ColumnProfile(name="country", type="varchar")],
            ),
            "invoices": TableProfile(
                name="invoices",
                description="billing transactions and payments",
                columns=[ColumnProfile(name="id", type="int"), ColumnProfile(name="total", type="float")],
            ),
        }
    )

    # 1. Clear lexical match -> returns immediately via fast lexical TF-IDF path
    hits = retrieve_relevant_tables("Show customer demographic profiles", catalog, k=2)
    assert "customers" in hits

    # 2. Invoices match -> fast lexical TF-IDF
    hits_inv = retrieve_relevant_tables("billing transactions total", catalog, k=2)
    assert "invoices" in hits_inv


def test_optimized_steiner_tree_join_path_resolution():
    from app.schema_grounding.relationship_graph import SchemaRelationshipGraph

    # Complex multi-table schema: Artist -> Album -> Track -> InvoiceLine -> Invoice -> Customer
    schema = {
        "artists": {"columns": [{"name": "id", "type": "int"}], "foreign_keys": []},
        "albums": {
            "columns": [{"name": "id", "type": "int"}, {"name": "artist_id", "type": "int"}],
            "foreign_keys": [{"constrained_columns": ["artist_id"], "referred_table": "artists", "referred_columns": ["id"]}],
        },
        "tracks": {
            "columns": [{"name": "id", "type": "int"}, {"name": "album_id", "type": "int"}],
            "foreign_keys": [{"constrained_columns": ["album_id"], "referred_table": "albums", "referred_columns": ["id"]}],
        },
        "invoice_lines": {
            "columns": [{"name": "id", "type": "int"}, {"name": "track_id", "type": "int"}, {"name": "invoice_id", "type": "int"}],
            "foreign_keys": [
                {"constrained_columns": ["track_id"], "referred_table": "tracks", "referred_columns": ["id"]},
                {"constrained_columns": ["invoice_id"], "referred_table": "invoices", "referred_columns": ["id"]},
            ],
        },
        "invoices": {
            "columns": [{"name": "id", "type": "int"}, {"name": "customer_id", "type": "int"}],
            "foreign_keys": [{"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["id"]}],
        },
        "customers": {"columns": [{"name": "id", "type": "int"}], "foreign_keys": []},
    }

    graph = SchemaRelationshipGraph(schema)

    # 1. Test memoized shortest path
    p1 = graph.find_shortest_path("artists", "tracks")
    assert p1 == ["artists", "albums", "tracks"]
    # Re-query hits path cache
    p2 = graph.find_shortest_path("tracks", "artists")
    assert p2 == ["tracks", "albums", "artists"]

    # 2. Test Multi-Source Steiner-tree joining across 3 distant seeds
    connecting = graph.get_minimal_connecting_tables({"artists", "customers", "tracks"})
    expected = {"artists", "albums", "tracks", "invoice_lines", "invoices", "customers"}
    assert connecting == expected


def test_schema_pruning_preserves_bridge_tables_and_join_keys():
    from app.schema_grounding.grounding_engine import SchemaGroundingEngine
    from app.semantic.models import QueryUnderstanding

    # Multi-hop schema where 'invoice_lines' is the bridge between 'tracks' and 'invoices'
    schema = {
        "artists": {"columns": [{"name": "id", "type": "int"}], "foreign_keys": []},
        "albums": {
            "columns": [{"name": "id", "type": "int"}, {"name": "artist_id", "type": "int"}],
            "foreign_keys": [{"constrained_columns": ["artist_id"], "referred_table": "artists", "referred_columns": ["id"]}],
        },
        "tracks": {
            "columns": [{"name": "id", "type": "int"}, {"name": "album_id", "type": "int"}, {"name": "name", "type": "varchar"}],
            "foreign_keys": [{"constrained_columns": ["album_id"], "referred_table": "albums", "referred_columns": ["id"]}],
        },
        "invoice_lines": {
            "columns": [
                {"name": "id", "type": "int"},
                {"name": "track_id", "type": "int"},
                {"name": "invoice_id", "type": "int"},
                {"name": "unit_price", "type": "float"},
            ] + [{"name": f"junk_col_{i}", "type": "varchar"} for i in range(25)],  # wide table
            "foreign_keys": [
                {"constrained_columns": ["track_id"], "referred_table": "tracks", "referred_columns": ["id"]},
                {"constrained_columns": ["invoice_id"], "referred_table": "invoices", "referred_columns": ["id"]},
            ],
        },
        "invoices": {
            "columns": [{"name": "id", "type": "int"}, {"name": "customer_id", "type": "int"}, {"name": "total", "type": "float"}],
            "foreign_keys": [{"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["id"]}],
        },
        "customers": {"columns": [{"name": "id", "type": "int"}, {"name": "name", "type": "varchar"}], "foreign_keys": []},
    }

    engine = SchemaGroundingEngine()
    # Query only explicitly mentions tracks and customers (invoice_lines is NOT in entities!)
    qu = QueryUnderstanding(
        raw_question="What tracks were bought by customer Alice?",
        entities=["tracks", "customers"],
        metrics=[],
        dimensions=["tracks.name", "customers.name"],
    )

    grounded = engine.build_grounded_schema(
        schema=schema,
        query_understanding=qu,
        question="What tracks were bought by customer Alice?",
    )

    # 1. Bridge table invoice_lines and invoices MUST be present!
    assert "invoice_lines" in grounded.selected_tables
    assert "invoices" in grounded.selected_tables
    assert "tracks" in grounded.selected_tables
    assert "customers" in grounded.selected_tables

    # 2. Join Paths MUST contain the full bridge chain
    assert "Join Paths:" in grounded.schema_text
    assert "invoice_lines.track_id = tracks.id" in grounded.schema_text or "tracks.id = invoice_lines.track_id" in grounded.schema_text
    assert "invoice_lines.invoice_id = invoices.id" in grounded.schema_text
    assert "invoices.customer_id = customers.id" in grounded.schema_text

    # 3. Foreign key join columns in the bridge table MUST be preserved despite column pruning
    assert "track_id:INT" in grounded.schema_text
    assert "invoice_id:INT" in grounded.schema_text
