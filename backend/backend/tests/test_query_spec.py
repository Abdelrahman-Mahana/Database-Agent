import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from app.semantic.query_spec_builder import QuerySpecBuilder
from app.semantic.models import IntentType, AnalysisType, OutputFormat, ExecutionRoute, QueryUnderstanding
from app.config.settings import settings
from app.agents.analyst_agent import AnalystAgent


class _MockDatabaseContext:
    """Minimal mock for DatabaseContext that provides schema, keyword_to_tables,
    table_names_set, and match_seed_tables_fast() for QuerySpecBuilder tests."""

    def __init__(self, schema: dict):
        self.schema = schema
        self.catalog = None
        self.table_names_set = set(schema.keys())
        self.keyword_to_tables = self._build_keyword_index(schema)

    @staticmethod
    def _build_keyword_index(schema: dict) -> dict:
        kw_map: dict[str, set[str]] = {}
        for table_name, info in schema.items():
            t_lower = table_name.lower()
            variations = {
                t_lower,
                t_lower + "s",
                t_lower + "es",
            }
            if t_lower.endswith("s") and not t_lower.endswith("ss"):
                variations.add(t_lower[:-1])
            if t_lower.endswith("es"):
                variations.add(t_lower[:-2])
            if t_lower.endswith("ies"):
                variations.add(t_lower[:-3] + "y")
            if t_lower.endswith("y"):
                variations.add(t_lower[:-1] + "ies")
            for v in variations:
                if len(v) > 2:
                    kw_map.setdefault(v, set()).add(table_name)
            for col in info.get("columns", []):
                c_lower = col["name"].lower()
                if len(c_lower) >= 3:
                    kw_map.setdefault(c_lower, set()).add(table_name)
        return kw_map

    def match_seed_tables_fast(self, text: str, max_tables: int = 15) -> set:
        import re
        tokens = set(re.findall(r'[\w\u0600-\u06FF]+', text.lower()))
        matched: set[str] = set()
        for token in tokens:
            if token in self.keyword_to_tables:
                matched.update(self.keyword_to_tables[token])
                if len(matched) >= max_tables:
                    break
        return matched


def _make_ctx(schema: dict) -> _MockDatabaseContext:
    return _MockDatabaseContext(schema)


# ---- Test fixtures ----

_CUSTOMERS_ORDERS_SCHEMA = {
    "customers": {
        "columns": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "name", "type": "varchar"},
            {"name": "country", "type": "varchar"},
        ]
    },
    "orders": {
        "columns": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "customer_id", "type": "int"},
            {"name": "total_amount", "type": "float"},
        ]
    },
}

_STUDENTS_GRADES_SCHEMA = {
    "students": {"columns": [{"name": "id", "type": "int"}, {"name": "name", "type": "varchar"}]},
    "grades": {"columns": [{"name": "student_id", "type": "int"}, {"name": "score", "type": "float"}]},
}

_ORDERS_PAYMENTS_SCHEMA = {
    "orders": {
        "columns": [
            {"name": "id", "type": "int"},
            {"name": "total", "type": "float"},
        ]
    },
    "payments": {
        "columns": [
            {"name": "id", "type": "int"},
            {"name": "total", "type": "float"},
        ]
    },
}


# ---- Tests ----

def test_query_spec_builder_database_query():
    builder = QuerySpecBuilder()
    ctx = _make_ctx(_CUSTOMERS_ORDERS_SCHEMA)

    # Query asking for top 5 customers by total amount
    spec = builder.build_spec(
        question="What are the top 5 customers by total_amount in 2023?",
        db_ctx=ctx,
    )

    assert spec.intent == IntentType.DATABASE
    assert "customers" in spec.entities or "orders" in spec.entities
    assert "orders.total_amount" in spec.metrics
    assert spec.limit == 5
    assert len(spec.time_expressions) > 0
    assert "2023" in spec.time_expressions
    assert spec.confidence >= 0.75
    assert spec.confidence < 1.0
    assert spec.understanding_confidence is not None
    assert spec.understanding_confidence.entity_confidence >= 0.70
    assert spec.understanding_confidence.metric_confidence >= 0.85


def test_query_spec_builder_off_topic_and_greetings():
    builder = QuerySpecBuilder()

    # Greeting in Arabic
    spec_ar = builder.build_spec(question="مرحبا كيف حالك؟")
    assert spec_ar.intent == IntentType.OFF_TOPIC
    assert spec_ar.off_topic_response is not None
    assert ("أهلاً" in spec_ar.off_topic_response or "مرحباً" in spec_ar.off_topic_response or "مرحبا" in spec_ar.off_topic_response)

    # Greeting in English
    spec_en = builder.build_spec(question="hello, who are you?")
    assert spec_en.intent == IntentType.OFF_TOPIC
    assert spec_en.off_topic_response is not None
    assert "database assistant" in spec_en.off_topic_response.lower()


def test_query_spec_builder_schema_queries():
    builder = QuerySpecBuilder()

    spec = builder.build_spec(question="show tables in database")
    assert spec.intent == IntentType.SCHEMA


def test_conversational_database_routing_does_not_generate_sql_path():
    builder = QuerySpecBuilder()
    ctx = _make_ctx(_STUDENTS_GRADES_SCHEMA)

    spec = builder.build_spec("ممكن تشرحلي قواعد البيانات دي؟", db_ctx=ctx)
    assert spec.route == ExecutionRoute.SCHEMA
    assert spec.intent == IntentType.SCHEMA
    assert spec.analysis_type == AnalysisType.UNKNOWN

    spec = builder.build_spec("كام عدد الطلاب المسجلين؟", db_ctx=ctx)
    assert spec.route == ExecutionRoute.DATA_QUERY
    assert spec.intent == IntentType.DATABASE

    spec = builder.build_spec("إيه الفرق بين جدول الطلاب وجدول الدرجات؟", db_ctx=ctx)
    assert spec.route == ExecutionRoute.SCHEMA

    spec = builder.build_spec("what is machine learning?", db_ctx=ctx)
    assert spec.route == ExecutionRoute.CONVERSATION
    assert spec.intent == IntentType.OFF_TOPIC
    assert spec.off_topic_response is not None
    assert "database" in spec.off_topic_response.lower()


def test_large_schema_uses_indexed_path():
    """Verify that build_spec() with a 10,000-table mock db_ctx completes in <50ms,
    proving the indexed path is used (not O(T*C) linear scan)."""
    # Generate a synthetic 10,000-table schema
    schema = {}
    for i in range(10_000):
        schema[f"table_{i}"] = {
            "columns": [
                {"name": f"col_{j}", "type": "varchar" if j % 2 == 0 else "int"}
                for j in range(20)
            ]
        }
    ctx = _make_ctx(schema)
    builder = QuerySpecBuilder()

    t0 = time.perf_counter()
    spec = builder.build_spec(
        question="How many records are in table_42?",
        db_ctx=ctx,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert spec.route == ExecutionRoute.DATA_QUERY
    assert "table_42" in spec.entities
    # The indexed path should complete well under 50ms even with 10K tables
    assert elapsed_ms < 50, f"build_spec took {elapsed_ms:.1f}ms on 10K tables, expected <50ms"


def test_query_spec_confidence_penalizes_unmapped_business_terms():
    builder = QuerySpecBuilder()
    ctx = _make_ctx(_CUSTOMERS_ORDERS_SCHEMA)

    spec = builder.build_spec(question="What is the total revenue by country?", db_ctx=ctx)

    assert spec.route == ExecutionRoute.DATA_QUERY
    assert spec.confidence < 0.75
    assert spec.understanding_confidence is not None
    assert spec.understanding_confidence.metric_confidence <= 0.40
    assert spec.understanding_confidence.ambiguity_penalty >= 0.15


def test_query_spec_routes_business_metric_without_table_name():
    builder = QuerySpecBuilder()
    ctx = _make_ctx(_CUSTOMERS_ORDERS_SCHEMA)

    spec = builder.build_spec(question="ما هو إجمالي الإيرادات؟", db_ctx=ctx)

    assert spec.route == ExecutionRoute.DATA_QUERY
    assert spec.intent == IntentType.DATABASE


def test_query_spec_routes_column_mention_without_table_name():
    builder = QuerySpecBuilder()
    ctx = _make_ctx(_CUSTOMERS_ORDERS_SCHEMA)

    spec = builder.build_spec(question="What is the total total_amount?", db_ctx=ctx)

    assert spec.route == ExecutionRoute.DATA_QUERY
    assert spec.intent == IntentType.DATABASE


def test_query_spec_requires_clarification_for_ambiguous_column_across_tables():
    builder = QuerySpecBuilder()
    ctx = _make_ctx(_ORDERS_PAYMENTS_SCHEMA)

    spec = builder.build_spec(question="total", db_ctx=ctx)

    assert spec.route == ExecutionRoute.DATA_QUERY
    assert spec.requires_clarification is True
    assert spec.clarification_prompt is not None
    assert "orders" in spec.ambiguity_candidates
    assert "payments" in spec.ambiguity_candidates


def test_explicit_schema_qualified_table_name_skips_ambiguity_gate():
    builder = QuerySpecBuilder()
    ctx = _make_ctx({"public.patient_model": {"columns": []}})

    assert builder._question_has_explicit_table_reference(
        "how many records are in patient_model?", ctx
    ) is True


def test_explicit_table_overrides_generic_keyword_matches():
    builder = QuerySpecBuilder()
    ctx = _make_ctx({
        "public.patient_model": {"columns": [{"name": "id", "type": "INTEGER"}]},
        "public.agial_opu": {"columns": [{"name": "r", "type": "TEXT"}, {"name": "l", "type": "TEXT"}]},
    })

    spec = builder.build_spec("How many records are in patient_model?", db_ctx=ctx)

    assert spec.entities == ["public.patient_model"]
    assert spec.dimensions == []
    assert spec.aggregations == ["COUNT"]


def test_query_spec_confidence_low_when_entities_and_metrics_missing():
    builder = QuerySpecBuilder()
    ctx = _make_ctx(_CUSTOMERS_ORDERS_SCHEMA)

    spec = builder.build_spec(question="show me data", db_ctx=ctx)

    assert spec.route == ExecutionRoute.DATA_QUERY
    assert spec.confidence <= 0.65
    assert spec.understanding_confidence.entity_confidence <= 0.45


@pytest.mark.asyncio
async def test_query_spec_builder_async_uses_llm_understanding_when_enabled():
    builder = QuerySpecBuilder(fast_llm=lambda x: x)
    ctx = _make_ctx(_CUSTOMERS_ORDERS_SCHEMA)

    llm_spec = QueryUnderstanding(
        raw_question="What is the total revenue by country?",
        intent=IntentType.DATABASE,
        route=ExecutionRoute.DATA_QUERY,
        route_confidence=0.91,
        analysis_type=AnalysisType.AGGREGATION,
        entities=["orders"],
        metrics=["orders.total_amount"],
        dimensions=["customers.country"],
        aggregations=["SUM"],
        confidence=0.91,
        source="llm_understanding",
    )

    with patch.object(settings, "use_llm_understanding", True), \
         patch.object(builder.llm_understander, "understand", new_callable=AsyncMock) as mock_understand:
        mock_understand.return_value = llm_spec

        spec = await builder.build_spec_async(
            question="What is the total revenue by country?",
            db_ctx=ctx,
        )

    assert mock_understand.await_count == 1
    assert spec.route == ExecutionRoute.DATA_QUERY
    assert spec.intent == IntentType.DATABASE
    assert spec.metrics == ["orders.total_amount"]
    assert spec.dimensions == ["customers.country"]
    assert spec.source == "llm_query_spec_builder"


@pytest.mark.asyncio
async def test_analyst_agent_asks_for_clarification_before_pipeline():
    query_spec = QueryUnderstanding(
        raw_question="total",
        intent=IntentType.DATABASE,
        route=ExecutionRoute.DATA_QUERY,
        route_confidence=0.96,
        requires_clarification=True,
        clarification_prompt="Your question could refer to multiple related tables ('orders' or 'payments'). Which one would you like to inspect?",
        ambiguity_candidates=["orders", "payments"],
    )

    agent = AnalystAgent.__new__(AnalystAgent)
    agent.schema_service = MagicMock()
    agent.schema_service.get_database_context.return_value = _make_ctx(_ORDERS_PAYMENTS_SCHEMA)
    agent.query_spec_builder = MagicMock()
    agent.query_spec_builder.build_spec_async = AsyncMock(return_value=query_spec)
    agent.schema_explorer = MagicMock()
    agent._run_graph_pipeline = AsyncMock()
    agent._run_service_pipeline = AsyncMock()

    fake_memory = MagicMock()
    fake_memory.get_history_text.return_value = ""

    with patch("app.agents.analyst_agent.memory_manager.get_memory", return_value=fake_memory), \
         patch.object(settings, "use_langgraph_orchestrator", False):
        result = await AnalystAgent.ask(agent, question="total", db=None, session_id="s1")

    assert result["success"] is True
    assert result["error_type"] == "ambiguity"
    assert "orders" in (result["report"] or "")
    assert result["suggestions"] == ["orders", "payments"]
    agent._run_service_pipeline.assert_not_awaited()
    agent._run_graph_pipeline.assert_not_awaited()
