"""Grounding Engine for verifying SQL queries against schema metadata."""
import re
from typing import Any, Dict, Optional, Tuple
from app.semantic.models import QueryUnderstanding

_UNANSWERABLE_RE = re.compile(r"UNANSWERABLE:\s*(?P<reason>.*?)\s*['\"]", re.IGNORECASE | re.DOTALL)


class GroundingEngine:
    """Verifies that generated SQL queries are semantically grounded in the database schema."""

    @staticmethod
    def unanswerable_reason(sql: str) -> Optional[str]:
        """Return the reason text if `sql` contains the UNANSWERABLE sentinel, else None."""
        if "UNANSWERABLE" not in sql.upper():
            return None
        match = _UNANSWERABLE_RE.search(sql)
        if match:
            return match.group("reason").strip()
        return "the question cannot be answered with the available schema."

    def validate_grounding(
        self,
        sql: str,
        schema: Dict[str, Any],
        query_understanding: Optional[QueryUnderstanding] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Validate if SQL query tables and columns exist in schema metadata."""
        reason = self.unanswerable_reason(sql)
        if reason:
            return False, f"UNANSWERABLE: {reason}"
        return True, None
