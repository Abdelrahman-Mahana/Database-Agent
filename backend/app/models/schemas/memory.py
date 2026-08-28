"""Pydantic schemas for the long-term memory API (Phase 7)."""
from typing import Any
from pydantic import BaseModel


class SaveQueryRequest(BaseModel):
    user_id: str
    question: str
    sql: str
    label: str | None = None


class SavedQueryResponse(BaseModel):
    id: str
    question: str
    sql: str
    label: str = ""
    created_at: float


class SetPreferenceRequest(BaseModel):
    user_id: str
    key: str
    value: Any


class PreferencesResponse(BaseModel):
    preferences: dict[str, Any]
