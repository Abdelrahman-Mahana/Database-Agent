"""Semantic Data Type Classifier.

Classifies column attributes into high-level business semantic data types:
- MONEY
- IDENTIFIER
- DATE
- PERCENTAGE
- STATUS
- CATEGORY
- GEOGRAPHY
- COUNT
- FREE_TEXT
- GENERIC
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Optional


class SemanticType(str, Enum):
    IDENTIFIER = "identifier"
    MONEY = "money"
    DATE = "date"
    PERCENTAGE = "percentage"
    STATUS = "status"
    CATEGORY = "category"
    GEOGRAPHY = "geography"
    COUNT = "count"
    FREE_TEXT = "free_text"
    GENERIC = "generic"


_MONEY_PATTERNS = re.compile(r"(price|amount|revenue|salary|cost|total|fee|tax|discount|budget|wage|payment|charge)", re.I)
_ID_PATTERNS = re.compile(r"(_id$|^id$|uuid|guid|_key$|^key$|_code$|^code$)", re.I)
_DATE_PATTERNS = re.compile(r"(date|time|timestamp|created_at|updated_at|birth|year|month|day)", re.I)
_PERCENT_PATTERNS = re.compile(r"(percent|rate|ratio|margin|pct|share)", re.I)
_STATUS_PATTERNS = re.compile(r"(status|state|is_|has_|active|enabled|completed|deleted|flag)", re.I)
_CATEGORY_PATTERNS = re.compile(r"(type|category|kind|genre|tier|department|role|channel|source|mode|segment|brand)", re.I)
_GEO_PATTERNS = re.compile(r"(country|city|state|region|province|address|street|zip|postal|lat|long|geo)", re.I)
_COUNT_PATTERNS = re.compile(r"(count|qty|quantity|num_|items_count|number_of)", re.I)
_TEXT_PATTERNS = re.compile(r"(description|note|notes|comment|comments|body|bio|text|content|details|message)", re.I)


def infer_semantic_type(column_name: str, data_type: str = "", distinct_count: Optional[int] = None) -> SemanticType:
    """Infer semantic business type from column name, SQL data type, and cardinality hints."""
    col = column_name.lower().strip()
    dt = data_type.upper().strip()

    # 1. Date types
    if any(t in dt for t in ("DATE", "TIME", "TIMESTAMP")) or _DATE_PATTERNS.search(col):
        return SemanticType.DATE

    # 2. Geography (country, city, postal_code, zip, etc.)
    if _GEO_PATTERNS.search(col):
        return SemanticType.GEOGRAPHY

    # 3. Identifiers
    if _ID_PATTERNS.search(col) or "UUID" in dt:
        return SemanticType.IDENTIFIER

    # 4. Currency / Money
    if _MONEY_PATTERNS.search(col) and any(t in dt for t in ("INT", "REAL", "FLOAT", "NUMERIC", "DECIMAL", "DOUBLE", "MONEY")):
        return SemanticType.MONEY

    # 5. Percentages
    if _PERCENT_PATTERNS.search(col):
        return SemanticType.PERCENTAGE

    # 6. Status / Booleans
    if "BOOL" in dt or _STATUS_PATTERNS.search(col):
        return SemanticType.STATUS

    # 7. Count / Quantities
    if _COUNT_PATTERNS.search(col):
        return SemanticType.COUNT

    # 8. Free text / Long text
    if any(t in dt for t in ("TEXT", "CLOB", "BLOB")) or _TEXT_PATTERNS.search(col):
        return SemanticType.FREE_TEXT

    # 9. Categories
    if _CATEGORY_PATTERNS.search(col) or (distinct_count is not None and 1 < distinct_count <= 20):
        return SemanticType.CATEGORY

    # Fallbacks based on data type
    if any(t in dt for t in ("INT", "FLOAT", "NUMERIC", "DOUBLE")):
        return SemanticType.COUNT
    if any(t in dt for t in ("CHAR", "VARCHAR", "STRING")):
        return SemanticType.CATEGORY if (distinct_count and distinct_count <= 50) else SemanticType.GENERIC

    return SemanticType.GENERIC
