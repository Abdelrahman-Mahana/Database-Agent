import time
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from app.config.settings import settings


class ConversationTurn(BaseModel):
    """Represents a single turn in the conversation."""
    question: str
    sql: str
    result_summary: str
    intent: str
    timestamp: float = Field(default_factory=time.time)


class ConversationMemory:
    """Sliding-window conversation memory for a single session."""

    def __init__(self, max_turns: int = 5):
        self.max_turns = max_turns
        self.turns: List[ConversationTurn] = []
        self.last_accessed: float = time.time()

    def add_turn(self, question: str, sql: str, result_summary: str, intent: str):
        """Add a new turn to the memory, maintaining the sliding window."""
        self.last_accessed = time.time()
        turn = ConversationTurn(
            question=question,
            sql=sql,
            result_summary=result_summary,
            intent=intent
        )
        self.turns.append(turn)
        if len(self.turns) > self.max_turns:
            self.turns.pop(0)

    def get_history_text(self, max_history_turns: int = 2) -> str:
        """Format the memory turns as text to be injected into prompts, keeping history concise."""
        self.last_accessed = time.time()
        if not self.turns:
            return ""

        recent_turns = self.turns[-max_history_turns:]
        lines = ["\nPrevious conversation turns:"]
        for turn in recent_turns:
            summary = " ".join((turn.result_summary or "").strip().split())[:500]
            if turn.intent == "database" and turn.sql:
                sql_clean = " ".join(turn.sql.strip().split())[:120]
                lines.append(f"User: {turn.question}\nAction: database query\nSQL: {sql_clean}\nAssistant: {summary}")
            else:
                lines.append(f"User: {turn.question}\nAction: {turn.intent}\nAssistant: {summary}")
        return "\n".join(lines) + "\n"

    def clear(self):
        """Clear all turns from the memory."""
        self.turns.clear()
        self.last_accessed = time.time()

    def __len__(self) -> int:
        return len(self.turns)


class MemoryManager:
    """Manages per-session ConversationMemory instances with TTL expiry."""

    def __init__(self, max_turns: int = 5, ttl_seconds: int = 3600):
        self.max_turns = max_turns
        self.ttl_seconds = ttl_seconds
        self.sessions: Dict[str, ConversationMemory] = {}

    def get_memory(self, session_id: Optional[str]) -> ConversationMemory:
        """Retrieve the ConversationMemory for a session ID. Creates one if it doesn't exist."""
        self._cleanup_expired()
        if not session_id:
            return ConversationMemory(max_turns=self.max_turns)

        if session_id not in self.sessions:
            self.sessions[session_id] = ConversationMemory(max_turns=self.max_turns)
        else:
            self.sessions[session_id].last_accessed = time.time()

        return self.sessions[session_id]

    def clear_memory(self, session_id: str):
        """Explicitly clear the memory of a session ID."""
        if session_id in self.sessions:
            del self.sessions[session_id]
        self._cleanup_expired()

    def clear_all(self):
        """Wipe memory across all active sessions (e.g. when database connection changes)."""
        self.sessions.clear()

    def _cleanup_expired(self):
        """Remove sessions that have been inactive for longer than the TTL."""
        now = time.time()
        expired_ids = [
            sid for sid, mem in self.sessions.items()
            if now - mem.last_accessed > self.ttl_seconds
        ]
        for sid in expired_ids:
            del self.sessions[sid]


# Singleton instance configured with settings
memory_manager = MemoryManager(
    max_turns=settings.memory_window_size,
    ttl_seconds=settings.memory_ttl_seconds
)
