"""Unit tests for deterministic SemanticQueryParser."""
import pytest
from app.semantic import SemanticQueryParser, QueryUnderstanding, OutputFormat
from app.utils.text_processor import AnalysisType


def test_semantic_parser_ranking_query():
    schema = {
        "Artist": {"columns": [{"name": "Name", "type": "VARCHAR"}]},
        "Invoice": {"columns": [{"name": "Total", "type": "NUMERIC"}, {"name": "InvoiceDate", "type": "DATETIME"}]},
    }
    parser = SemanticQueryParser()
    qu = parser.parse("Who are the top 5 artists by total spending in 2023?", schema=schema)

    assert isinstance(qu, QueryUnderstanding)
    assert qu.analysis_type == AnalysisType.RANKING
    assert "Artist" in qu.entities
    assert "Invoice" in qu.entities
    assert "Invoice.Total" in qu.metrics
    assert qu.limit == 5
    assert len(qu.sorting) == 1
    assert qu.sorting[0].direction == "DESC"
    assert "2023" in qu.time_expressions
    assert qu.expected_output == OutputFormat.RANKING


def test_semantic_parser_count_query():
    schema = {
        "Track": {"columns": [{"name": "Name", "type": "VARCHAR"}]},
        "Genre": {"columns": [{"name": "Name", "type": "VARCHAR"}]},
    }
    parser = SemanticQueryParser()
    qu = parser.parse("How many tracks belong to Rock genre?", schema=schema)

    assert qu.analysis_type == AnalysisType.COUNT
    assert "COUNT" in qu.aggregations
    assert qu.expected_output == OutputFormat.SCALAR
