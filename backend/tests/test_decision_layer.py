import pytest
from app.semantic.decision import DecisionLayer
from app.semantic.models import ExecutionRoute


@pytest.mark.asyncio
async def test_conversation_does_not_need_database():
    decision = await DecisionLayer().decide("what is machine learning?")
    assert decision.route == ExecutionRoute.CONVERSATION
    assert decision.needs_database is False
    assert decision.needs_sql is False


@pytest.mark.asyncio
async def test_data_question_needs_database_and_sql():
    decision = await DecisionLayer().decide("how many students do we have?")
    assert decision.route == ExecutionRoute.DATA_QUERY
    assert decision.needs_database is True
    assert decision.needs_sql is True


@pytest.mark.asyncio
async def test_schema_question_needs_schema_not_sql():
    decision = await DecisionLayer().decide("show me the database schema")
    assert decision.route == ExecutionRoute.SCHEMA
    assert decision.needs_schema is True
    assert decision.needs_sql is False
