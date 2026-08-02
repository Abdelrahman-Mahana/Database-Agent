from datetime import datetime, timezone
from typing import Any
from app.conversation.interfaces import ITTLManager

class TTLManager(ITTLManager):
    def __init__(self, ttl_seconds: int = 3600, context_ttl_seconds: int = 1800):
        self.ttl_seconds = ttl_seconds
        self.context_ttl_seconds = context_ttl_seconds

    def check_expiration(self, last_active: Any) -> bool:
        if not last_active:
            return True
        now = datetime.now(timezone.utc)
        diff = (now - last_active).total_seconds()
        return diff > self.ttl_seconds

    def is_context_valid(self, created_at: Any) -> bool:
        if not created_at:
            return False
        now = datetime.now(timezone.utc)
        diff = (now - created_at).total_seconds()
        return diff <= self.context_ttl_seconds
