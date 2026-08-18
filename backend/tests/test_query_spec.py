import pytest
from app.semantic.query_spec_builder import QuerySpecBuilder
from app.semantic.models import IntentType, AnalysisType, OutputFormat, ExecutionRoute


def test_query_spec_builder_database_query():
    builder = QuerySpecBuilder()
    schema = {
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
        }
    }

    # Query asking for top 5 customers by total amount
    spec = builder.build_spec(
        question="What are the top 5 customers by total_amount in 2023?",
        schema=schema,
    )

    assert spec.intent == IntentType.DATABASE
    assert "customers" in spec.entities or "orders" in spec.entities
    assert "orders.total_amount" in spec.metrics
    assert spec.limit == 5
    assert len(spec.time_expressions) > 0
    assert "2023" in spec.time_expressions
    assert spec.confidence == 1.0


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
    schema = {
        "students": {"columns": [{"name": "id", "type": "int"}, {"name": "name", "type": "varchar"}]},
        "grades": {"columns": [{"name": "student_id", "type": "int"}, {"name": "score", "type": "float"}]},
    }

    spec = builder.build_spec("ممكن تشرحلي قواعد البيانات دي؟", schema=schema)
    assert spec.route == ExecutionRoute.SCHEMA
    assert spec.intent == IntentType.SCHEMA
    assert spec.analysis_type == AnalysisType.UNKNOWN

    spec = builder.build_spec("كام عدد الطلاب المسجلين؟", schema=schema)
    assert spec.route == ExecutionRoute.DATA_QUERY
    assert spec.intent == IntentType.DATABASE

    spec = builder.build_spec("إيه الفرق بين جدول الطلاب وجدول الدرجات؟", schema=schema)
    assert spec.route == ExecutionRoute.SCHEMA

    spec = builder.build_spec("what is machine learning?", schema=schema)
    assert spec.route == ExecutionRoute.CONVERSATION
    assert spec.intent == IntentType.OFF_TOPIC
