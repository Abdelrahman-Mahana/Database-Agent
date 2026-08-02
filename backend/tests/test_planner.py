import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agents.planner import Planner

@pytest.mark.asyncio
async def test_execute_plan_success():
    primary_llm = MagicMock()
    fast_llm = MagicMock()
    
    planner = Planner(primary_llm, fast_llm)
    
    # Mock synthesis chain to return a simple report
    mock_synthesis_resp = MagicMock()
    mock_synthesis_resp.content = "Here is the synthesized report."
    planner.synthesis_chain.ainvoke = AsyncMock(return_value=mock_synthesis_resp)
    
    # Mock sub_question_chain to return SQL
    mock_sub_resp = MagicMock()
    mock_sub_resp.content = "SELECT * FROM test;"
    planner.sub_question_chain.ainvoke = AsyncMock(return_value=mock_sub_resp)
    
    # Mock SQL execution
    planner.sql_executor = MagicMock()
    planner.sql_executor.execute.return_value = [{"id": 1, "value": "test"}]
    
    # Dependencies
    db = MagicMock()
    sql_generator = MagicMock()
    sql_generator.extract_sql.return_value = "SELECT * FROM test;"
    
    report_service = MagicMock()
    report_service.suggest_chart = AsyncMock(return_value={"type": "bar"})
    
    memory = MagicMock()
    
    result = await planner.execute_plan(
        question="What is the test value?",
        plan_steps=["Step 1", "Step 2"],
        schema_text="Table test",
        db=db,
        conversation_history="",
        sql_generator=sql_generator,
        report_service=report_service,
        memory=memory
    )
    
    assert result is not None
    assert result["success"] is True
    assert result["report"] == "Here is the synthesized report."
    assert result["chart_suggestion"] == {"type": "bar"}
    assert result["sql"] == "SELECT * FROM test;"
    
    # Check that suggest_chart was called
    report_service.suggest_chart.assert_called_once()
