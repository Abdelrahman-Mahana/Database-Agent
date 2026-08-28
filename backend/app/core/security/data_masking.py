"""Phase 5 — column-level sensitive-data masking.

Applied to query result rows right after execution, BEFORE they reach the
report-writing LLM call or the user — so a column like `password_hash` or
`ssn` never gets echoed into a generated report or sent to the LLM as
context, even if a question's SQL happens to select it (e.g. `SELECT *`).

Deliberately name/pattern-based rather than value-based (regex-sniffing
actual values for e.g. credit-card-shaped numbers) — value sniffing is
slower, less predictable, and has more false negatives/positives than just
trusting column naming conventions, which are extremely consistent in
practice (`password`, `ssn`, `credit_card_number`, `api_key`...).
"""
from __future__ import annotations

import re
from typing import Any

# Built-in patterns cover the common PII/secret column-naming conventions.
# Matched as case-insensitive substrings against the column name.
DEFAULT_MASKED_PATTERNS: list[str] = [
    "password", "passwd", "pwd",
    "ssn", "social_security", "socialsecurity", "national_id", "nationalid", "passport",
    "credit_card", "creditcard", "card_number", "cardnumber", "cvv", "cvc",
    "api_key", "apikey", "secret", "access_token", "accesstoken",
    "auth_token", "authtoken", "private_key", "privatekey",
    "bank_account", "bankaccount", "iban", "swift_code", "swiftcode",
    "routing_number", "routingnumber",
]

MASK_VALUE = "***MASKED***"


def _compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(re.escape(p), re.IGNORECASE) for p in patterns]


def _is_sensitive_column(column_name: str, compiled_patterns: list[re.Pattern]) -> bool:
    return any(p.search(column_name) for p in compiled_patterns)


def mask_sensitive_columns(
    rows: list[dict[str, Any]],
    extra_patterns: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (masked_rows, masked_column_names). Never mutates the input list/dicts.

    `extra_patterns`: additional column-name substrings to mask beyond the
    built-in list (see `settings.extra_masked_column_patterns`), for
    domain-specific sensitive fields the built-ins won't know about.
    """
    if not rows:
        return rows, []

    all_patterns = DEFAULT_MASKED_PATTERNS + (extra_patterns or [])
    compiled = _compile_patterns(all_patterns)

    columns = list(rows[0].keys())
    sensitive_cols = [c for c in columns if _is_sensitive_column(c, compiled)]
    if not sensitive_cols:
        return rows, []

    masked_rows = []
    for row in rows:
        new_row = dict(row)
        for col in sensitive_cols:
            if col in new_row and new_row[col] is not None:
                new_row[col] = MASK_VALUE
        masked_rows.append(new_row)

    return masked_rows, sensitive_cols
