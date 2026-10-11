"""Response bodies for /agents/logs and /system/status."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AgentLogOut(BaseModel):
    id: int
    agent_name: str
    action: str
    input_summary: Any        # parsed JSON object when the stored text is JSON (it always is for agents), else the text
    output_summary: Any
    created_at: datetime


class DatabaseStatus(BaseModel):
    ok: bool
    error: str | None = None


class VectorStoreStatus(BaseModel):
    vectors: int | None       # vectors in the ChromaDB collection; null if it could not be read
    collection: str
    error: str | None = None


class LLMProviderStatus(BaseModel):
    keys_configured: int      # how many keys (never the keys themselves)
    models: list[str]         # tried in this order


class LLMStatus(BaseModel):
    primary_provider: str
    cross_provider_fallback: bool
    providers: dict[str, LLMProviderStatus]


class SystemStatus(BaseModel):
    checked_at: datetime
    database: DatabaseStatus
    scheduler: dict[str, Any]  # same data as GET /health/scheduler
    row_counts: dict[str, int | None]
    vector_store: VectorStoreStatus
    llm: LLMStatus
    data_sources: dict[str, bool]   # True = a key is configured (values are never returned)
