"""Unit tests for Schema Grounding Engine."""
import pytest
from app.semantic.models import QueryUnderstanding
from app.schema_grounding import (
    SchemaGroundingEngine,
    SchemaRelationshipGraph,
    SchemaPruner,
    GroundedSchema,
)


@pytest.fixture
def mock_schema():
    return {
        "Artist": {
            "columns": [{"name": "ArtistId", "type": "INTEGER"}, {"name": "Name", "type": "VARCHAR"}],
            "primary_key": ["ArtistId"],
            "foreign_keys": [],
        },
        "Album": {
            "columns": [{"name": "AlbumId", "type": "INTEGER"}, {"name": "Title", "type": "VARCHAR"}, {"name": "ArtistId", "type": "INTEGER"}],
            "primary_key": ["AlbumId"],
            "foreign_keys": [{"constrained_columns": ["ArtistId"], "referred_table": "Artist", "referred_columns": ["ArtistId"]}],
        },
        "Track": {
            "columns": [{"name": "TrackId", "type": "INTEGER"}, {"name": "Name", "type": "VARCHAR"}, {"name": "AlbumId", "type": "INTEGER"}],
            "primary_key": ["TrackId"],
            "foreign_keys": [{"constrained_columns": ["AlbumId"], "referred_table": "Album", "referred_columns": ["AlbumId"]}],
        },
        "InvoiceLine": {
            "columns": [{"name": "InvoiceLineId", "type": "INTEGER"}, {"name": "InvoiceId", "type": "INTEGER"}, {"name": "TrackId", "type": "INTEGER"}],
            "primary_key": ["InvoiceLineId"],
            "foreign_keys": [
                {"constrained_columns": ["InvoiceId"], "referred_table": "Invoice", "referred_columns": ["InvoiceId"]},
                {"constrained_columns": ["TrackId"], "referred_table": "Track", "referred_columns": ["TrackId"]},
            ],
        },
        "Invoice": {
            "columns": [{"name": "InvoiceId", "type": "INTEGER"}, {"name": "Total", "type": "NUMERIC"}],
            "primary_key": ["InvoiceId"],
            "foreign_keys": [],
        },
        "UnrelatedTable": {
            "columns": [{"name": "Id", "type": "INTEGER"}],
            "primary_key": ["Id"],
            "foreign_keys": [],
        },
    }


def test_relationship_graph_path_expansion(mock_schema):
    graph = SchemaRelationshipGraph(mock_schema)
    path = graph.find_shortest_path("Artist", "Invoice")
    assert path == ["Artist", "Album", "Track", "InvoiceLine", "Invoice"]

    minimal = graph.get_minimal_connecting_tables({"Artist", "Invoice"})
    assert "Artist" in minimal
    assert "Album" in minimal
    assert "Track" in minimal
    assert "InvoiceLine" in minimal
    assert "Invoice" in minimal
    assert "UnrelatedTable" not in minimal


def test_schema_grounding_engine(mock_schema):
    engine = SchemaGroundingEngine()

    qu = QueryUnderstanding(
        raw_question="Top artists by invoice sales",
        entities=["Artist", "Invoice"],
    )

    grounded = engine.build_grounded_schema(schema=mock_schema, query_understanding=qu)

    assert isinstance(grounded, GroundedSchema)
    assert "Artist" in grounded.selected_tables
    assert "Invoice" in grounded.selected_tables
    assert "UnrelatedTable" not in grounded.selected_tables
    assert grounded.pruned_table_count == 5
    assert grounded.original_table_count == 6
    assert "Database Schema (Grounded Subset):" in grounded.schema_text


def test_schema_grounding_keyword_fallback_and_stemming():
    engine = SchemaGroundingEngine()
    
    schema = {
        "Categories": {
            "columns": [{"name": "CategoryID", "type": "INTEGER"}, {"name": "CategoryName", "type": "VARCHAR"}],
            "primary_key": ["CategoryID"],
            "foreign_keys": [],
        },
        "Products": {
            "columns": [{"name": "ProductID", "type": "INTEGER"}, {"name": "CategoryID", "type": "INTEGER"}],
            "primary_key": ["ProductID"],
            "foreign_keys": [{"constrained_columns": ["CategoryID"], "referred_table": "Categories", "referred_columns": ["CategoryID"]}],
        },
        "Orders": {
            "columns": [{"name": "OrderID", "type": "INTEGER"}],
            "primary_key": ["OrderID"],
            "foreign_keys": [],
        },
        "Order Details": {
            "columns": [{"name": "OrderID", "type": "INTEGER"}, {"name": "ProductID", "type": "INTEGER"}],
            "primary_key": ["OrderID", "ProductID"],
            "foreign_keys": [
                {"constrained_columns": ["OrderID"], "referred_table": "Orders", "referred_columns": ["OrderID"]},
                {"constrained_columns": ["ProductID"], "referred_table": "Products", "referred_columns": ["ProductID"]},
            ],
        },
        "Suppliers": {
            "columns": [{"name": "SupplierID", "type": "INTEGER"}],
            "primary_key": ["SupplierID"],
            "foreign_keys": [],
        },
        "Customers": {
            "columns": [{"name": "CustomerID", "type": "INTEGER"}],
            "primary_key": ["CustomerID"],
            "foreign_keys": [],
        },
        "Employees": {
            "columns": [{"name": "EmployeeID", "type": "INTEGER"}],
            "primary_key": ["EmployeeID"],
            "foreign_keys": [],
        },
        "Regions": {
            "columns": [{"name": "RegionID", "type": "INTEGER"}],
            "primary_key": ["RegionID"],
            "foreign_keys": [],
        },
        "Shippers": {
            "columns": [{"name": "ShipperID", "type": "INTEGER"}],
            "primary_key": ["ShipperID"],
            "foreign_keys": [],
        },
        "Territories": {
            "columns": [{"name": "TerritoryID", "type": "INTEGER"}],
            "primary_key": ["TerritoryID"],
            "foreign_keys": [],
        }
    }
    
    # 10 tables total. 
    # Question with singular forms "product", "order", "category".
    question = "What are the top 3 product categories with the highest average order value"
    
    grounded = engine.build_grounded_schema(schema=schema, question=question)
    
    assert "Products" in grounded.selected_tables
    assert "Categories" in grounded.selected_tables
    assert "Orders" in grounded.selected_tables
    assert "Order Details" in grounded.selected_tables
    
    # Test fallback: a question matching only 1 table.
    question_low_confidence = "Where is the territory?"
    grounded_fallback = engine.build_grounded_schema(schema=schema, question=question_low_confidence)
    assert grounded_fallback.pruned_table_count == 10
