"""Comprehensive test suite for the Semantic Contract system.

Tests:
1. Semantic Contract Data Models & Immutability Freeze Hashing
2. Business Metric Registry (English and Arabic business concepts)
3. Time Semantics Resolver (Dates, ranges, quarters, relative times)
4. Filter Normalization & Grounding Resolver
5. Pre-Execution AST Semantic Contract Validator
6. QuerySpec & QuerySpecBuilder Integration
"""
import pytest
from app.agent.semantic.models import (
    SemanticContract,
    SemanticGrain,
    GrainType,
    MetricSpec,
    DimensionSpec,
    TimeSpec,
    FilterSpec,
    SortSpec,
    FormulaType,
    FilterOperator,
)
from app.agent.semantic.models import business_metric_registry, BusinessMetricRegistry
from app.agent.semantic.resolvers import time_resolver, TimeResolver
from app.agent.semantic.resolvers import filter_resolver, FilterResolver
from app.agent.semantic.contract_builder import semantic_contract_builder
from app.agent.semantic.models import QuerySpec, IntentType, ExecutionRoute
from app.services.sql.validator import sql_validator


SAMPLE_CHINOOK_SCHEMA = {
    "Invoice": {
        "columns": [
            {"name": "InvoiceId", "type": "INTEGER"},
            {"name": "CustomerId", "type": "INTEGER"},
            {"name": "InvoiceDate", "type": "DATETIME"},
            {"name": "BillingCountry", "type": "NVARCHAR(40)"},
            {"name": "Total", "type": "NUMERIC(10,2)"},
        ]
    },
    "Customer": {
        "columns": [
            {"name": "CustomerId", "type": "INTEGER"},
            {"name": "FirstName", "type": "NVARCHAR(40)"},
            {"name": "LastName", "type": "NVARCHAR(20)"},
            {"name": "Country", "type": "NVARCHAR(40)"},
            {"name": "Email", "type": "NVARCHAR(60)"},
        ]
    },
    "InvoiceLine": {
        "columns": [
            {"name": "InvoiceLineId", "type": "INTEGER"},
            {"name": "InvoiceId", "type": "INTEGER"},
            {"name": "TrackId", "type": "INTEGER"},
            {"name": "UnitPrice", "type": "NUMERIC(10,2)"},
            {"name": "Quantity", "type": "INTEGER"},
        ]
    }
}


def test_semantic_contract_freeze_hash():
    """Test that freeze() calculates deterministic SHA256 contract hash."""
    contract1 = SemanticContract(
        raw_question="What is the total revenue by country in 2012?",
        normalized_question="What is the total revenue by country in 2012?",
        primary_entity="Customer",
        grain=SemanticGrain(grain_type=GrainType.ENTITY_GRAIN, primary_entity="Customer", grain_keys=["Country"]),
        measures=[
            MetricSpec(metric_id="revenue", formula_type=FormulaType.SUM, source_table="Invoice", source_column="Total")
        ],
        dimensions=[
            DimensionSpec(dimension_id="country", source_table="Customer", source_column="Country")
        ],
        time_spec=TimeSpec(time_column="InvoiceDate", start_date="2012-01-01", end_date="2012-12-31"),
        filters=[
            FilterSpec(concept="country", operator=FilterOperator.EQ, normalized_value="USA")
        ],
    )
    contract1.freeze()

    assert contract1.is_frozen is True
    assert len(contract1.contract_hash) == 16
    assert isinstance(contract1.contract_hash, str)

    # Same contract contents produce identical hash
    contract2 = SemanticContract(
        raw_question="What is the total revenue by country in 2012?",
        normalized_question="What is the total revenue by country in 2012?",
        primary_entity="Customer",
        grain=SemanticGrain(grain_type=GrainType.ENTITY_GRAIN, primary_entity="Customer", grain_keys=["Country"]),
        measures=[
            MetricSpec(metric_id="revenue", formula_type=FormulaType.SUM, source_table="Invoice", source_column="Total")
        ],
        dimensions=[
            DimensionSpec(dimension_id="country", source_table="Customer", source_column="Country")
        ],
        time_spec=TimeSpec(time_column="InvoiceDate", start_date="2012-01-01", end_date="2012-12-31"),
        filters=[
            FilterSpec(concept="country", operator=FilterOperator.EQ, normalized_value="USA")
        ],
    )
    contract2.freeze()
    assert contract1.contract_hash == contract2.contract_hash


def test_business_metric_registry_en_and_ar():
    """Test business metric resolution across English and Arabic terms."""
    # 1. English Revenue
    spec_en = business_metric_registry.resolve_metric("total sales by artist", SAMPLE_CHINOOK_SCHEMA)
    assert spec_en is not None
    assert spec_en.metric_id == "revenue"
    assert spec_en.formula_type == FormulaType.SUM
    assert spec_en.source_column == "Total"
    assert spec_en.source_table == "Invoice"

    # 2. Arabic Revenue
    spec_ar = business_metric_registry.resolve_metric("ما هو إجمالي الإيرادات في عام 2012؟", SAMPLE_CHINOOK_SCHEMA)
    assert spec_ar is not None
    assert spec_ar.metric_id == "revenue"
    assert spec_ar.formula_type == FormulaType.SUM
    assert spec_ar.source_column == "Total"

    # 3. Customer Count (Distinct)
    spec_cust = business_metric_registry.resolve_metric("عدد العملاء في كل دولة", SAMPLE_CHINOOK_SCHEMA)
    assert spec_cust is not None
    assert spec_cust.metric_id == "customer_count"
    assert spec_cust.formula_type == FormulaType.COUNT_DISTINCT
    assert spec_cust.requires_distinct is True
    assert spec_cust.source_column == "CustomerId"

    # 4. Average Order Value
    spec_aov = business_metric_registry.resolve_metric("calculate average order value", SAMPLE_CHINOOK_SCHEMA)
    assert spec_aov is not None
    assert spec_aov.metric_id == "average_order_value"
    assert spec_aov.formula_type == FormulaType.AVG


def test_time_resolver_boundaries():
    """Test date boundary normalization across various formats."""
    # 1. Single Year (English & Arabic)
    t1 = time_resolver.resolve_time("sales in 2012", SAMPLE_CHINOOK_SCHEMA)
    assert t1 is not None
    assert t1.start_date == "2012-01-01"
    assert t1.end_date == "2012-12-31"
    assert t1.time_column == "InvoiceDate"

    t2 = time_resolver.resolve_time("إجمالي المبيعات في عام 2010", SAMPLE_CHINOOK_SCHEMA)
    assert t2 is not None
    assert t2.start_date == "2010-01-01"
    assert t2.end_date == "2010-12-31"

    # 2. Year Range
    t3 = time_resolver.resolve_time("revenue between 2009 and 2011", SAMPLE_CHINOOK_SCHEMA)
    assert t3 is not None
    assert t3.start_date == "2009-01-01"
    assert t3.end_date == "2011-12-31"

    t4 = time_resolver.resolve_time("المبيعات من 2010 إلى 2013", SAMPLE_CHINOOK_SCHEMA)
    assert t4 is not None
    assert t4.start_date == "2010-01-01"
    assert t4.end_date == "2013-12-31"

    # 3. Quarters
    t5 = time_resolver.resolve_time("sales in Q3 2023", SAMPLE_CHINOOK_SCHEMA)
    assert t5 is not None
    assert t5.start_date == "2023-07-01"
    assert t5.end_date == "2023-09-30"

    t6 = time_resolver.resolve_time("أرباح الربع الأول من 2024", SAMPLE_CHINOOK_SCHEMA)
    assert t6 is not None
    assert t6.start_date == "2024-01-01"
    assert t6.end_date == "2024-03-31"

    # 4. Temporal Grain
    t7 = time_resolver.resolve_time("monthly revenue evolution", SAMPLE_CHINOOK_SCHEMA)
    assert t7 is not None
    assert t7.granularity == "MONTH"

    t8 = time_resolver.resolve_time("المبيعات شهرياً", SAMPLE_CHINOOK_SCHEMA)
    assert t8 is not None
    assert t8.granularity == "MONTH"


def test_filter_resolver():
    """Test filter parsing, operator resolution, and synonym mapping."""
    raw_filters = [
        {"column": "Country", "operator": "=", "value": "أمريكا"},
        {"column": "Total", "operator": ">=", "value": 100},
        {"column": "Email", "operator": "is not null", "value": None},
    ]
    resolved = filter_resolver.resolve_filters(raw_filters, SAMPLE_CHINOOK_SCHEMA)
    assert len(resolved) == 3

    # Synonym mapping
    assert resolved[0].normalized_value == "USA"
    assert resolved[0].operator == FilterOperator.EQ
    assert resolved[0].target_table == "Customer" or resolved[0].target_table == "Invoice"
    assert "Country = 'USA'" in resolved[0].to_sql_predicate()

    # Operator mapping
    assert resolved[1].operator == FilterOperator.GTE
    assert resolved[1].normalized_value == 100
    assert "Total >= 100" in resolved[1].to_sql_predicate()

    # Null operator mapping
    assert resolved[2].operator == FilterOperator.IS_NOT_NULL
    assert "Email IS NOT NULL" in resolved[2].to_sql_predicate()


def test_ast_semantic_contract_validator():
    """Test that SQL AST validator strictly enforces Semantic Contract."""
    contract = SemanticContract(
        raw_question="Total sales by country in 2012",
        grain=SemanticGrain(grain_type=GrainType.ENTITY_GRAIN, primary_entity="Customer"),
        measures=[
            MetricSpec(metric_id="revenue", formula_type=FormulaType.SUM, source_table="Invoice", source_column="Total")
        ],
        dimensions=[
            DimensionSpec(dimension_id="Country", source_table="Invoice", source_column="BillingCountry")
        ],
        time_spec=TimeSpec(time_column="InvoiceDate", start_date="2012-01-01", end_date="2012-12-31"),
        filters=[
            FilterSpec(concept="BillingCountry", target_column="BillingCountry", operator=FilterOperator.EQ, normalized_value="USA")
        ],
        limit=5,
    )
    contract.freeze()

    # 1. Fully Valid SQL
    valid_sql = """
    SELECT BillingCountry, SUM(Total) AS total_revenue
    FROM Invoice
    WHERE InvoiceDate >= '2012-01-01' AND InvoiceDate <= '2012-12-31' AND BillingCountry = 'USA'
    GROUP BY BillingCountry
    LIMIT 5
    """
    ok, warnings = sql_validator.verify_semantic_contract_alignment(valid_sql, contract)
    assert ok is True
    assert len(warnings) == 0

    # 2. SQL Missing SUM aggregate
    missing_agg_sql = """
    SELECT BillingCountry, Total
    FROM Invoice
    WHERE InvoiceDate >= '2012-01-01' AND BillingCountry = 'USA'
    LIMIT 5
    """
    ok, warnings = sql_validator.verify_semantic_contract_alignment(missing_agg_sql, contract)
    assert ok is False
    assert any("SUM" in w for w in warnings)

    # 3. SQL Missing GROUP BY when dimensions & measures specified
    missing_group_sql = """
    SELECT BillingCountry, SUM(Total) AS total_revenue
    FROM Invoice
    WHERE InvoiceDate >= '2012-01-01' AND BillingCountry = 'USA'
    LIMIT 5
    """
    ok, warnings = sql_validator.verify_semantic_contract_alignment(missing_group_sql, contract)
    assert ok is False
    assert any("GROUP BY" in w for w in warnings)

    # 4. SQL Missing WHERE clause when filters and time bounds specified
    missing_where_sql = """
    SELECT BillingCountry, SUM(Total) AS total_revenue
    FROM Invoice
    GROUP BY BillingCountry
    LIMIT 5
    """
    ok, warnings = sql_validator.verify_semantic_contract_alignment(missing_where_sql, contract)
    assert ok is False
    assert any("WHERE" in w for w in warnings)

    # 5. SQL Missing LIMIT clause when limit specified
    missing_limit_sql = """
    SELECT BillingCountry, SUM(Total) AS total_revenue
    FROM Invoice
    WHERE InvoiceDate >= '2012-01-01' AND BillingCountry = 'USA'
    GROUP BY BillingCountry
    """
    ok, warnings = sql_validator.verify_semantic_contract_alignment(missing_limit_sql, contract)
    assert ok is False
    assert any("LIMIT" in w for w in warnings)


def test_query_spec_to_semantic_contract_integration():
    """Test seamless QuerySpec to SemanticContract integration."""
    qspec = QuerySpec(
        raw_question="What are the top 5 countries by total revenue in 2012?",
        entities=["Invoice"],
        metrics=["revenue"],
        dimensions=["BillingCountry"],
        aggregations=["SUM"],
        limit=5,
    )
    contract = qspec.to_semantic_contract(schema=SAMPLE_CHINOOK_SCHEMA)

    assert contract is not None
    assert contract.is_frozen is True
    assert len(contract.measures) >= 1
    assert contract.measures[0].formula_type == FormulaType.SUM
    assert contract.limit == 5
    assert qspec.semantic_intent_hash == contract.contract_hash
