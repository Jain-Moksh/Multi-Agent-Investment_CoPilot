"""Response bodies for /recommendations."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AgentView(BaseModel):
    status: str | None
    signal: float | None
    confidence: float | None
    summary: str | None


class RecommendationOut(BaseModel):
    """Returned by POST /recommendations/{symbol}: the decision plus everything behind it."""

    id: int
    symbol: str
    company_name: str | None
    decision: str                   # buy | hold | sell (as stored)
    decision_label: str             # Buy | Hold | Sell | Avoid (Sell for a stock you don't own)
    confidence: float               # 0..1
    confidence_level: str           # low | moderate | high
    overall_lean: float             # -1 bearish .. +1 bullish
    explanation: str
    explanation_source: str         # llm | template
    main_driver: dict[str, Any] | None
    conflicts: list[str]
    agents: dict[str, AgentView]
    excluded: dict[str, str]        # agents whose evidence was unavailable, and why
    created_at: datetime
    disclaimer: str


class RecommendationSummary(BaseModel):
    """One row of GET /recommendations (history)."""

    id: int
    symbol: str
    decision: str
    decision_label: str
    confidence: float
    overall_lean: float | None
    explanation: str
    created_at: datetime
