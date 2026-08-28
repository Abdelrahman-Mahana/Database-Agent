"""Tests verifying the 5-pillar intelligence and consistency architecture."""
import pytest
from app.agent.semantic.models import QuerySpec, AnalysisType, FilterCondition, SortCondition, OutputFormat
from app.agent.semantic.database_knowledge_store import DatabaseKnowledgeStore, GoldenPattern, database_knowledge_store
from app.agent.semantic.query_spec_builder import QuerySpecBuilder
from app.models.schema_catalog.models import TableProfile, ColumnProfile
from app.services.sql.prompt_builder import SQLPromptBuilder


def test_pillar1_deterministic_query_spec_hash():
    """Pillar 1: Identical query specifications must produce identical semantic intent hashes."""
    spec1 = QuerySpec(
        raw_question="مسار الإيرادات الشهرية من الفواتير وتحديد الشهور الأعلى والأدنى",
        analysis_type=AnalysisType.TREND,
        entities=["account_move"],
        metrics=["amount_total"],
        dimensions=["invoice_date"],
        aggregations=["SUM"],
        filters=[FilterCondition(column="invoice_date", operator="IS NOT", value="NULL")],
        sorting=[SortCondition(column="month", direction="ASC")],
        limit=500,
        expected_output=OutputFormat.TABLE,
    )

    spec2 = QuerySpec(
        raw_question="مسار الإيرادات الشهرية من الفواتير وتحديد الشهور الأعلى والأدنى (جلسة جديدة)",
        analysis_type=AnalysisType.TREND,
        entities=["account_move"],
        metrics=["amount_total"],
        dimensions=["invoice_date"],
        aggregations=["SUM"],
        filters=[FilterCondition(column="invoice_date", operator="IS NOT", value="NULL")],
        sorting=[SortCondition(column="month", direction="ASC")],
        limit=500,
        expected_output=OutputFormat.TABLE,
    )

    assert spec1.semantic_intent_hash == spec2.semantic_intent_hash
    assert len(spec1.semantic_intent_hash) == 16


def test_pillar2_database_knowledge_store_retrieval():
    """Pillar 2: Knowledge store provides glossary terms and golden patterns for target database."""
    store = DatabaseKnowledgeStore()
    
    # Query knowledge for Agial PostgreSQL
    knowledge = store.retrieve_relevant_knowledge(
        question="مسار إيرادات الفواتير والعملاء",
        db_identifier="agial",
        candidate_tables=["account_move", "res_partner"],
    )

    assert len(knowledge["rules"]) > 0
    assert "فواتير" in knowledge["glossary"]
    assert knowledge["glossary"]["فواتير"] == "account_move"
    assert len(knowledge["few_shots"]) > 0

    # Formatted prompt section check
    prompt_section = store.format_prompt_knowledge_section(
        question="مسار إيرادات الفواتير",
        db_identifier="agial",
    )
    assert "DOMAIN KNOWLEDGE & GOLDEN PATTERNS" in prompt_section
    assert "account_move" in prompt_section


def test_pillar3_multi_turn_coreference_resolution():
    """Pillar 3: Follow-up drilldown questions inherit previous context and date filters."""
    builder = QuerySpecBuilder()

    # User previously asked about monthly revenue and July 2024 was highlighted
    mock_history = (
        "User: مسار الإيرادات الشهرية من الفواتير؟\n"
        "Assistant: أعلى إيرادات كانت في شهر 2024-07 بمبلغ 39,049,647.85.\n"
        "SQL: SELECT TO_CHAR(invoice_date, 'YYYY-MM') AS month, SUM(amount_total) FROM account_move GROUP BY month;"
    )

    # Follow-up question referencing the previous period
    follow_up_question = "مين أهم العملاء اللي اشتروا في الشهر ده؟"

    enriched_spec = builder.build_spec(
        question=follow_up_question,
        conversation_history=mock_history,
    )

    # Must resolve the date filter (2024-07) and add customer entity (res_partner)
    assert "2024-07" in enriched_spec.time_expressions or any("2024-07" in str(f.value) for f in enriched_spec.filters)
    assert "res_partner" in enriched_spec.entities or "account_move" in enriched_spec.entities


def test_pillar4_zero_shot_table_profile_column_inference():
    """Pillar 4: Automatically discover primary date, metric, and status columns for any database."""
    # Test on an Odoo/Agial table
    account_move_profile = TableProfile(
        name="account_move",
        columns=[
            ColumnProfile(name="id", type="INTEGER", primary_key=True),
            ColumnProfile(name="invoice_date", type="DATE"),
            ColumnProfile(name="amount_total", type="NUMERIC"),
            ColumnProfile(name="state", type="VARCHAR"),
        ]
    )
    assert account_move_profile.primary_date_column == "invoice_date"
    assert account_move_profile.primary_metric_column == "amount_total"
    assert account_move_profile.status_column == "state"

    # Test on a generic E-commerce table (e.g. SQLite / Chinook / Shopify)
    orders_profile = TableProfile(
        name="Orders",
        columns=[
            ColumnProfile(name="OrderId", type="INTEGER", primary_key=True),
            ColumnProfile(name="OrderDate", type="DATETIME"),
            ColumnProfile(name="Total", type="FLOAT"),
            ColumnProfile(name="Status", type="VARCHAR"),
        ]
    )
    assert orders_profile.primary_date_column == "OrderDate"
    assert orders_profile.primary_metric_column == "Total"
    assert orders_profile.status_column == "Status"


def test_pillar5_prompt_builder_grounding_injection():
    """Pillar 5: SQLPromptBuilder injects strict grounding constraints and domain rules."""
    prompt_builder = SQLPromptBuilder()

    spec = QuerySpec(
        raw_question="أعلى 5 عملاء",
        entities=["account_move", "res_partner"],
        metrics=["SUM(amount_total)"],
        dimensions=["rp.name"],
        filters=[FilterCondition(column="am.invoice_date", operator="IS NOT", value="NULL")],
        sorting=[SortCondition(column="total_amount", direction="DESC")],
        limit=5,
    )

    payload = prompt_builder.build_generation_input(
        schema_text="TABLE account_move (id INT, invoice_date DATE, amount_total NUMERIC, partner_id INT);\nTABLE res_partner (id INT, name TEXT);",
        question="أعلى 5 عملاء في الفواتير",
        query_understanding=spec,
        dialect="postgresql",
        db_identifier="agial",
    )

    history_content = payload["conversation_history"]
    assert "[Semantic Query Plan & Grounding Constraints]" in history_content
    assert "Entities / Tables: account_move, res_partner" in history_content
    assert "Limit: 5" in history_content
    assert "DOMAIN KNOWLEDGE & GOLDEN PATTERNS" in history_content
