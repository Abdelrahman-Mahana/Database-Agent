import pytest
from app.utils.token_tracker import (
    ContextTokenTrackerCallback,
    get_current_token_usage,
    reset_token_usage,
    record_llm_trace,
    get_llm_trace,
    reset_llm_trace
)
from langchain_core.outputs import LLMResult, Generation, ChatGeneration
from langchain_core.messages import AIMessage

def test_token_tracker_context_vars():
    """Test that context variables properly store and reset token and trace data."""
    reset_token_usage()
    reset_llm_trace()
    
    assert get_current_token_usage() == {"prompt_tokens": 0, "completion_tokens": 0}
    assert get_llm_trace() == []
    
    record_llm_trace({"model": "test-model"})
    assert len(get_llm_trace()) == 1
    
    reset_llm_trace()
    assert get_llm_trace() == []

@pytest.mark.asyncio
async def test_callback_on_llm_end():
    """Test the callback logic when an LLM finishes."""
    reset_token_usage()
    reset_llm_trace()
    
    cb = ContextTokenTrackerCallback()
    await cb.on_llm_start(serialized={}, prompts=["Hello"], run_id="123")
    
    # Simulate LangChain LLMResult
    message = AIMessage(content="World", response_metadata={"token_usage": {"prompt_tokens": 5, "completion_tokens": 10}, "model": "test-gpt"})
    generation = ChatGeneration(message=message)
    
    result = LLMResult(generations=[[generation]])
    await cb.on_llm_end(result, run_id="123")
    
    usage = get_current_token_usage()
    assert usage["prompt_tokens"] == 5
    assert usage["completion_tokens"] == 10
    
    trace = get_llm_trace()
    assert len(trace) == 1
    assert trace[0]["model"] == "test-gpt"
    assert trace[0]["success"] is True
