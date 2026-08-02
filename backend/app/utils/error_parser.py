"""Extract the missing table/column name a DB engine's error message names.

Factored out of `app.sql.repair_engine.SQLRepairEngine.analyze_db_error`
(same regexes, same behavior) so `app.services.schema_learning` (Phase 5)
can reuse the exact identifier the error was actually about, not just the
fuzzy-matched suggestion list `analyze_db_error` returns. Kept dependency-free
(stdlib only) so it can be imported from anywhere without pulling in the LLM
stack.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

_TABLE_PATTERNS = (
    re.compile(r"no such table:\s*(\w+)", re.IGNORECASE),
    re.compile(r'relation\s*"([^"]+)"\s*does not exist', re.IGNORECASE),
)
_COLUMN_PATTERNS = (
    re.compile(r"no such column:\s*([\w.]+)", re.IGNORECASE),
    re.compile(r'column\s*"([^"]+)"\s*does not exist', re.IGNORECASE),
)


def extract_missing_identifier(error_msg: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (kind, name) where kind is "table" or "column", or (None, None)
    if the error message doesn't match a known "unknown identifier" shape
    (e.g. it's a syntax error, permissions error, timeout, ...).

    For columns, any leading "table." qualifier is stripped - callers only
    get the bare column name, matching what `analyze_db_error` already does.
    """
    if not error_msg:
        return None, None
    for pattern in _TABLE_PATTERNS:
        m = pattern.search(error_msg)
        if m:
            return "table", m.group(1)
    for pattern in _COLUMN_PATTERNS:
        m = pattern.search(error_msg)
        if m:
            return "column", m.group(1).split(".")[-1]
    return None, None
