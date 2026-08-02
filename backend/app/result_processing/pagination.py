# Cursor and Pagination managers to construct pagination metadata
# Usually integrated with Chunk Reader and Stream Processor
# Here provided as modular helpers
from typing import Optional
import base64
import json

class CursorManager:
    def encode_cursor(self, offset: int, limit: int) -> str:
        data = {"offset": offset, "limit": limit}
        return base64.b64encode(json.dumps(data).encode()).decode()
        
    def decode_cursor(self, cursor_str: str) -> dict:
        try:
            return json.loads(base64.b64decode(cursor_str.encode()).decode())
        except Exception:
            return {"offset": 0, "limit": 1000}

class PaginationHelper:
    def __init__(self, cursor_manager: CursorManager):
        self.cursor_manager = cursor_manager
        
    def calculate_pagination(self, current_offset: int, limit: int, total_fetched: int, has_more: bool):
        next_cursor = None
        if has_more:
            next_cursor = self.cursor_manager.encode_cursor(current_offset + total_fetched, limit)
        return next_cursor
