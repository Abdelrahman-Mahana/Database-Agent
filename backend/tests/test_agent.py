import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agents.analyst_agent import AnalystAgent


class MockMsg:
    """Helper to mock LangChain message response containing content."""
    def __init__(self, content: str):
        self.content = content


@pytest.mark.asyncio
async def test_agent_successful_ask(db_session, mock_llm_chain):
    # Set the mocked LLM output to return a query that works
    mock_llm_chain.return_value = {
        "text": "SELECT * FROM Artist LIMIT 5;"
    }
    
    agent = AnalystAgent()
    result = await agent.ask("Give me some artists.", db_session)
    
    assert result["success"]
    assert result["error"] is None
    assert "Artist" in result["sql"]
    assert len(result["results"]) == 5
    assert result["report"] != ""


@pytest.mark.asyncio
async def test_agent_unanswerable_ask(db_session, mock_llm_chain, monkeypatch):
    # Mock LLM to return the UNANSWERABLE sentinel
    mock_llm_chain.return_value = {
        "text": "SELECT 'UNANSWERABLE: No ratings table exists' AS error;"
    }

    agent = AnalystAgent()

    # The no-answer explanation is now LLM-humanized (see report_service.
    # generate_no_answer_response); stub it here so this test verifies the
    # routing/reason plumbing in AnalystAgent rather than exact LLM wording.
    async def fake_no_answer_response(question, situation, reason, table_names=None):
        return f"[no-answer] {situation} {reason}"
    monkeypatch.setattr(agent.report_service, "generate_no_answer_response", fake_no_answer_response)

    result = await agent.ask("Show me movie ratings.", db_session)

    assert result["success"]
    assert "No ratings table exists" in result["report"]
    assert len(result["results"]) == 0


def test_schema_exploration_routing_tables():
    agent = AnalystAgent()
    result = agent.schema_service.get_schema()
    assert "Artist" in result


@pytest.mark.asyncio
async def test_schema_exploration_routing_tables_async(db_session):
    agent = AnalystAgent()
    result = await agent.ask("List all tables in the database", db_session)
    assert result["success"]
    assert "Artist" in result["report"]
    assert "-- Schema Exploration" in result["sql"]
    assert len(result["results"]) > 0


@pytest.mark.asyncio
async def test_schema_exploration_routing_columns_async(db_session):
    agent = AnalystAgent()
    result = await agent.ask("Show me the columns in Table Customer", db_session)
    assert result["success"]
    assert "CustomerId" in result["report"]
    assert "Table Columns: Customer" in result["report"]


@pytest.mark.asyncio
async def test_schema_exploration_routing_relations_async(db_session):
    agent = AnalystAgent()
    result = await agent.ask("Show me the foreign key relations for Invoice", db_session)
    assert result["success"]
    assert "Relationships for table: Invoice" in result["report"]
    assert "CustomerId" in result["report"]


@pytest.mark.asyncio
async def test_agent_multi_step_reasoning(db_session, monkeypatch):
    agent = AnalystAgent()
    
    # Mock decompose_chain
    mock_decompose = AsyncMock(return_value=MockMsg('{"steps": ["Get artists", "Get albums for top artist"]}'))
    monkeypatch.setattr(agent.planner.decompose_chain, "ainvoke", mock_decompose)
    
    # Mock sub_question_chain
    mock_sub_query = AsyncMock(return_value=MockMsg("SELECT * FROM Artist LIMIT 1;"))
    monkeypatch.setattr(agent.planner.sub_question_chain, "ainvoke", mock_sub_query)
    
    # Mock synthesis_chain
    mock_synthesis = AsyncMock(return_value=MockMsg("Here is the synthesized multi-step report."))
    monkeypatch.setattr(agent.planner.synthesis_chain, "ainvoke", mock_synthesis)
    
    result = await agent.ask("Who is the top artist and what albums do they have?", db_session)
    
    assert result["success"]
    assert "SELECT" in result["sql"]
    assert "synthesized" in result["report"].lower()
    assert result["error"] is None


@pytest.mark.asyncio
async def test_intent_classification_database(db_session, monkeypatch):
    agent = AnalystAgent()
    
    mock_classify = AsyncMock(return_value=MockMsg('{"intent": "database", "reasoning": "wants sales data"}'))
    monkeypatch.setattr(agent.intent_classifier.intent_classification_chain, "ainvoke", mock_classify)
    
    mock_sql_gen = AsyncMock(return_value=MockMsg("SELECT * FROM Invoice LIMIT 5;"))
    monkeypatch.setattr(agent.sql_generator.sql_generation_chain, "ainvoke", mock_sql_gen)
    
    result = await agent.ask("How many users signed up this month?", db_session)
    
    assert result["success"]
    assert result["intent"] == "database"
    assert "Invoice" in result["sql"]
    mock_classify.assert_called_once()


@pytest.mark.asyncio
async def test_intent_classification_off_topic(db_session, monkeypatch):
    agent = AnalystAgent()
    
    mock_classify = AsyncMock(return_value=MockMsg('{"intent": "off_topic", "reasoning": "unrelated question"}'))
    monkeypatch.setattr(agent.intent_classifier.intent_classification_chain, "ainvoke", mock_classify)
    
    mock_off_topic = AsyncMock(return_value=MockMsg("I specialize in database analysis. I can help with Invoice table."))
    monkeypatch.setattr(agent.intent_classifier.off_topic_chain, "ainvoke", mock_off_topic)
    
    result = await agent.ask("What is the capital of France?", db_session)
    
    assert result["success"]
    assert result["intent"] == "off_topic"
    assert "specialize" in result["report"]
    assert result["sql"] == ""
    assert len(result["results"]) == 0
    mock_classify.assert_called_once()
    mock_off_topic.assert_called_once()


@pytest.mark.asyncio
async def test_intent_classification_schema_fallback(db_session, monkeypatch):
    agent = AnalystAgent()
    
    mock_classify = MagicMock(side_effect=Exception("LLM failure"))
    monkeypatch.setattr(agent.intent_classifier.intent_classification_chain, "ainvoke", mock_classify)
    
    mock_sql_gen = AsyncMock(return_value=MockMsg("SELECT * FROM Artist LIMIT 1;"))
    monkeypatch.setattr(agent.sql_generator.sql_generation_chain, "ainvoke", mock_sql_gen)
    
    # Classification failing should fall back to database intent and proceed
    result = await agent.ask("Who is the top artist?", db_session)
    
    assert result["success"]
    assert result["intent"] == "database"
    assert "Artist" in result["sql"]


@pytest.mark.asyncio
async def test_memory_follow_up_question(db_session, mock_llm_chain, monkeypatch):
    agent = AnalystAgent()
    session_id = "agent_session_123"

    # Mock classification and SQL generation
    mock_classify = AsyncMock(return_value=MockMsg('{"intent": "database", "reasoning": "follow-up request"}'))
    monkeypatch.setattr(agent.intent_classifier.intent_classification_chain, "ainvoke", mock_classify)

    mock_sql_gen = AsyncMock(return_value=MockMsg("SELECT * FROM Artist LIMIT 5;"))
    monkeypatch.setattr(agent.sql_generator.sql_generation_chain, "ainvoke", mock_sql_gen)

    # First turn
    result1 = await agent.ask("Show all artists", db_session, session_id=session_id)
    assert result1["success"]

    # Verify memory contains the first turn
    from app.services.memory import memory_manager
    memory = memory_manager.get_memory(session_id)
    assert len(memory) == 1
    assert "Show all artists" in memory.get_history_text()

    # Second turn (follow-up)
    result2 = await agent.ask("How many are there?", db_session, session_id=session_id)
    assert result2["success"]

    # Verify history is passed
    assert len(memory) == 2
    
    # Clean up session
    memory_manager.clear_memory(session_id)


@pytest.mark.asyncio
async def test_memory_no_session_id(db_session, mock_llm_chain, monkeypatch):
    agent = AnalystAgent()

    mock_classify = AsyncMock(return_value=MockMsg('{"intent": "database", "reasoning": "no session request"}'))
    monkeypatch.setattr(agent.intent_classifier.intent_classification_chain, "ainvoke", mock_classify)

    mock_sql_gen = AsyncMock(return_value=MockMsg("SELECT * FROM Artist LIMIT 1;"))
    monkeypatch.setattr(agent.sql_generator.sql_generation_chain, "ainvoke", mock_sql_gen)

    # Passing session_id=None should work without persisting memory
    result = await agent.ask("Who is the top artist?", db_session, session_id=None)
    assert result["success"]


def test_schema_service_caching_and_invalidation():
    from app.services.sql_service import SchemaService
    service = SchemaService()

    # 1. Fetch schema and schema text
    schema1 = service.get_schema()
    text1 = service.get_schema_text()
    assert "Artist" in schema1
    assert "Artist" in text1

    # 2. Subsequent call should hit valid cache
    schema2 = service.get_schema()
    text2 = service.get_schema_text()
    assert schema1 is schema2
    assert text1 is text2

    # 3. Explicit refresh_cache should re-introspect and update
    schema3, text3 = service.refresh_cache()
    assert "Artist" in schema3

    # 4. Explicit clear_cache should invalidate stored cache
    SchemaService.clear_cache()
    schema4 = service.get_schema()
    assert "Artist" in schema4


def test_is_complex_query_routing():
    from app.utils.text_processor import is_complex_query

    # Simple queries (should return False and bypass Planner)
    assert not is_complex_query("Who are the top 5 customers by total spending?")
    assert not is_complex_query("How many tracks belong to Rock genre?")
    assert not is_complex_query("Show all albums by Queen")
    assert not is_complex_query("Total sales for 2023")

    # Complex queries (should return True and trigger Planner)
    assert is_complex_query("Compare sales in 2022 vs 2023")
    assert is_complex_query("Show revenue trends over time")
    assert is_complex_query("Who is the top artist and what albums do they have?")
    assert is_complex_query("What are the top 3 genres? Then list the tracks in each.")
    assert is_complex_query("Explain why sales dropped in June")


def test_classify_analysis_type():
    from app.utils.text_processor import classify_analysis_type, AnalysisType, COMPLEX_ANALYSIS_TYPES

    assert classify_analysis_type("Show all albums by Queen") == AnalysisType.LOOKUP
    assert classify_analysis_type("How many tracks belong to Rock genre?") == AnalysisType.COUNT
    assert classify_analysis_type("Total sales for 2023") == AnalysisType.AGGREGATION
    assert classify_analysis_type("Who are the top 5 customers by total spending?") == AnalysisType.RANKING

    assert classify_analysis_type("Compare sales in 2022 vs 2023") == AnalysisType.COMPARISON
    assert classify_analysis_type("Show revenue trends over time") == AnalysisType.TREND
    assert classify_analysis_type("Explain why sales dropped in June") == AnalysisType.ROOT_CAUSE
    assert classify_analysis_type("Who is the top artist and what albums do they have?") == AnalysisType.MULTI_STEP

    # Complex set verification
    assert classify_analysis_type("Compare sales") in COMPLEX_ANALYSIS_TYPES
    assert classify_analysis_type("Show all albums") not in COMPLEX_ANALYSIS_TYPES


@pytest.mark.asyncio
async def test_analytics_pipeline_integration(db_session, mock_llm_chain, monkeypatch):
    agent = AnalystAgent()

    mock_classify = AsyncMock(return_value=MockMsg('{"intent": "database", "reasoning": "analytics test"}'))
    monkeypatch.setattr(agent.intent_classifier.intent_classification_chain, "ainvoke", mock_classify)

    mock_sql_gen = AsyncMock(return_value=MockMsg("SELECT * FROM Artist LIMIT 5;"))
    monkeypatch.setattr(agent.sql_generator.sql_generation_chain, "ainvoke", mock_sql_gen)

    result = await agent.ask("List artists", db_session)
    assert result["success"]
    assert "results" in result
    assert len(result["results"]) > 0




