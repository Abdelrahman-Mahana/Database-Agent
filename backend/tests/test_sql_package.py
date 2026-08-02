"""Unit tests for app/sql modular package and refactored SQLGenerator."""
import pytest
from app.sql import SQLPromptBuilder, GroundingEngine, SQLValidator, SQLRepairEngine, ValidationResult, GroundingResult


def test_sql_prompt_builder():
    builder = SQLPromptBuilder()
    payload = builder.build_generation_input(
        schema_text="Table Artist",
        question="Show artists",
    )
    assert payload["schema"] == "Table Artist"
    assert payload["question"] == "Show artists"


def test_grounding_engine_unanswerable():
    ge = GroundingEngine()
    sql = 'UNANSWERABLE: "The table xyz does not exist in schema"'
    reason = ge.unanswerable_reason(sql)
    assert reason == "The table xyz does not exist in schema"
    
    is_grounded, err_msg = ge.validate_grounding(sql, {})
    assert is_grounded is False
    assert "UNANSWERABLE" in err_msg


def test_sql_validator():
    validator = SQLValidator()
    raw = "```sql\nSELECT * FROM Artist;\n```"
    clean = validator.sanitize_and_extract(raw)
    assert clean == "SELECT * FROM Artist;"

    val_res = validator.validate_safety("SELECT * FROM Artist;")
    assert val_res["valid"] is True


def test_repair_engine_fuzzy_matches(monkeypatch):
    from unittest.mock import MagicMock
    mock_llm = MagicMock()
    repair_engine = SQLRepairEngine(primary_llm=mock_llm)

    # Test error analysis
    err_msg = "no such table: Artst"
    err_type, suggestions = repair_engine.analyze_db_error(err_msg)
    assert err_type == "schema"
    assert "Artist" in suggestions
