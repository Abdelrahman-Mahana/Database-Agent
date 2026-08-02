"""Tests for the rebuild-plan additions: schema catalog, synonym resolution,
adaptive self-consistency routing, and Arabic business-term matching.

Run with: pytest backend/tests/test_rebuild_plan.py -v
(requires the project's normal dependencies — sqlalchemy, pydantic, loguru —
 installed via `pip install -r requirements.txt`, unlike the ad-hoc stubbed
 checks used during development in an offline sandbox.)
"""
import json

import pytest

from app.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile
from app.utils.cost_router import should_use_self_consistency
from app.utils.text_processor import AnalysisType, classify_analysis_type
from app.schema_grounding.arabic_terms import expand_with_arabic_terms
from app.schema_grounding.grounding_engine import _has_metric_column


# --------------------------------------------------------------------------
# Phase 1: Schema Catalog
# --------------------------------------------------------------------------

def _sample_catalog() -> SchemaCatalog:
    cat = SchemaCatalog(fingerprint="abc123", dialect="SQLITE", database_name="Chinook")
    cat.tables["Customers"] = TableProfile(
        name="Customers",
        columns=[
            ColumnProfile(name="CustomerId", type="INTEGER", primary_key=True),
            ColumnProfile(name="Country", type="VARCHAR", samples=["USA", "Canada"], synonyms=["دولة", "بلد"]),
        ],
        primary_key=["CustomerId"],
        row_count=59,
        fk_degree=3,
    )
    cat.tables["Customers"].synonyms = ["عملاء", "clients"]
    cat.glossary_enriched = True
    return cat


def test_schema_catalog_json_roundtrip():
    cat = _sample_catalog()
    restored = SchemaCatalog.from_dict(json.loads(json.dumps(cat.to_dict(), ensure_ascii=False)))
    assert restored.fingerprint == "abc123"
    assert restored.tables["Customers"].row_count == 59
    assert restored.tables["Customers"].columns[1].samples == ["USA", "Canada"]
    assert restored.glossary_enriched is True


def test_schema_catalog_find_by_synonym():
    cat = _sample_catalog()
    assert cat.find_by_synonym("عملاء") == [("Customers", None)]
    assert cat.find_by_synonym("دولة") == [("Customers", "Country")]
    assert cat.find_by_synonym("nonexistent term") == []


# --------------------------------------------------------------------------
# Phase 2: Synonym resolution
# --------------------------------------------------------------------------

def test_resolve_synonyms_maps_arabic_metric():
    from app.semantic.synonyms import resolve_synonyms

    cat = SchemaCatalog(fingerprint="x", dialect="SQLITE", database_name="Northwind")
    cat.tables["Orders"] = TableProfile(
        name="Orders",
        columns=[ColumnProfile(name="Freight", type="DECIMAL", synonyms=["الشحن"])],
    )
    cat.glossary_enriched = True

    class FakeUnderstanding:
        entities: list = []
        metrics: list = []
        dimensions: list = []

        def __init__(self):
            self.entities, self.metrics, self.dimensions = [], [], []

    u = resolve_synonyms("كام تكلفة الشحن؟", cat, FakeUnderstanding())
    assert "Orders.Freight" in u.metrics
    assert "Orders" in u.entities


def test_resolve_synonyms_noop_without_glossary():
    from app.semantic.synonyms import resolve_synonyms

    class FakeUnderstanding:
        def __init__(self):
            self.entities, self.metrics, self.dimensions = [], [], []

    u = resolve_synonyms("anything", None, FakeUnderstanding())
    assert u.entities == [] and u.metrics == []


# --------------------------------------------------------------------------
# Phase 4: Adaptive self-consistency routing
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "question,analysis_type,global_flag,expected",
    [
        ("How many customers are there?", AnalysisType.COUNT, False, False),
        ("Compare Q1 vs Q2 revenue", AnalysisType.COMPARISON, False, True),
        ("ما هو أفضل منتج مبيعاً؟", AnalysisType.RANKING, False, True),
        ("How many customers are there?", AnalysisType.COUNT, True, False),  # downgraded even when global ON
        ("Show trend of sales by month", AnalysisType.TREND, True, True),
    ],
)
def test_should_use_self_consistency(question, analysis_type, global_flag, expected, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "enable_self_consistency", global_flag)
    monkeypatch.setattr(settings, "sql_candidates", 3)
    assert should_use_self_consistency(question, analysis_type) is expected


def test_self_consistency_hard_disabled_below_two_candidates(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "enable_self_consistency", True)
    monkeypatch.setattr(settings, "sql_candidates", 1)
    assert should_use_self_consistency("Compare A vs B", AnalysisType.COMPARISON) is False


# --------------------------------------------------------------------------
# Arabic colloquial classification + business-term expansion
# --------------------------------------------------------------------------

def test_classify_analysis_type_handles_colloquial_kaam():
    # "كام" (Egyptian/Gulf colloquial) alongside formal "كم" for COUNT.
    assert classify_analysis_type("كام طلب اتعمل خلال يناير؟") == AnalysisType.COUNT
    assert classify_analysis_type("كم عدد العملاء؟") == AnalysisType.COUNT


def test_expand_with_arabic_terms():
    expanded = expand_with_arabic_terms("كام عميل موجود؟")
    assert "customer" in expanded
    expanded2 = expand_with_arabic_terms("كام طلب اتعمل؟")
    assert "order" in expanded2 and "orders" in expanded2  # plural added for already-plural table names


def test_expand_with_arabic_terms_noop_for_english():
    q = "how many customers are there"
    assert expand_with_arabic_terms(q) == q


# --------------------------------------------------------------------------
# Metric-aware neighbor expansion helper
# --------------------------------------------------------------------------

def test_has_metric_column_detects_real_metrics_not_ids():
    orders_like = {"columns": [{"name": "OrderID", "type": "INTEGER"}, {"name": "Freight", "type": "DECIMAL"}]}
    junction_like = {"columns": [{"name": "EmployeeID", "type": "INTEGER"}, {"name": "TerritoryID", "type": "INTEGER"}]}
    assert _has_metric_column(orders_like) is True
    assert _has_metric_column(junction_like) is False
