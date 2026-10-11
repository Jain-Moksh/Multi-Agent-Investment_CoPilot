"""Request/response bodies for /chat."""

from datetime import datetime

from pydantic import BaseModel, Field


class ChatMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class ChatSource(BaseModel):
    news_event_id: int
    title: str
    url: str
    source_domain: str | None


class ChatSecurity(BaseModel):
    verdict: str                    # SAFE | SUSPICIOUS | BLOCKED
    reason: str | None = None       # shown only when not SAFE


class ChatReply(BaseModel):
    conversation_id: str
    reply: str
    status: str                     # ok | refused | refused_unverified | llm_unavailable | blocked_output
    mode: str                       # symbol | general | refused
    detected_symbols: list[str]     # held stocks recognised in the message
    security: ChatSecurity
    user_message_id: int
    assistant_message_id: int
    sources: list[ChatSource]


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    security_status: str | None
    created_at: datetime
