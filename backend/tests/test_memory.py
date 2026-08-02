import time
import pytest
from app.services.memory import ConversationTurn, ConversationMemory, MemoryManager


def test_turn_storage_and_sliding_window():
    memory = ConversationMemory(max_turns=3)
    assert len(memory) == 0
    assert memory.get_history_text() == ""

    # Add 1 turn
    memory.add_turn("What is total revenue?", "SELECT SUM(Total) FROM Invoice;", "1 row. Sample: {SUM(Total): 2328.6}", "database")
    assert len(memory) == 1
    assert "User asked 'What is total revenue?'" in memory.get_history_text()
    assert "SELECT SUM(Total) FROM Invoice;" in memory.get_history_text()

    # Add 2 more turns
    memory.add_turn("Break that down by month", "SELECT strftime('%Y-%m', InvoiceDate) FROM Invoice;", "12 rows.", "database")
    memory.add_turn("Show columns", "", "Details", "schema")
    assert len(memory) == 3

    # Add 4th turn -> should drop the first turn
    memory.add_turn("Exclude USA", "SELECT * FROM Invoice WHERE BillingCountry != 'USA';", "10 rows.", "database")
    assert len(memory) == 3
    history = memory.get_history_text()
    assert "What is total revenue?" not in history
    assert "Exclude USA" in history


def test_memory_manager_retrieval_and_ttl():
    manager = MemoryManager(max_turns=5, ttl_seconds=2)
    session_id = "test_session_123"

    mem = manager.get_memory(session_id)
    assert mem is not None
    assert len(mem) == 0

    # Add a turn
    mem.add_turn("Hello", "", "Hi", "off_topic")
    
    # Retrieve again -> should be the same memory instance
    mem2 = manager.get_memory(session_id)
    assert mem2 is mem
    assert len(mem2) == 1

    # Simulate TTL expiration by manually modifying last_accessed timestamp
    mem.last_accessed = time.time() - 5
    
    # Trigger cleanup by calling retrieve
    mem_new = manager.get_memory(session_id)
    assert mem_new is not mem  # Should be a new, empty memory instance
    assert len(mem_new) == 0


def test_memory_manager_clear():
    manager = MemoryManager(max_turns=5, ttl_seconds=3600)
    session_id = "test_session_clear"

    mem = manager.get_memory(session_id)
    mem.add_turn("Hello", "", "Hi", "off_topic")
    assert len(manager.get_memory(session_id)) == 1

    manager.clear_memory(session_id)
    mem_after = manager.get_memory(session_id)
    assert len(mem_after) == 0
