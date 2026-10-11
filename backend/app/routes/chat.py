"""
AI Assistant chat (login required).

POST /chat/message                    send a message; returns the reply + conversation_id
GET  /chat/conversations              the user's conversations, newest first
GET  /chat/conversations/{id}         one conversation's messages

History store: PostgreSQL (chat_conversations / chat_messages), chosen over an
in-memory dict because:
  + conversations survive server restarts (uvicorn --reload restarts on every save)
    and work with several workers;
  + each conversation belongs to a user, so another user's id gives 404;
  + every message keeps its injection-scan verdict: a permanent audit trail for the
    security demo;
  - cost: one table pair, one migration, and a few queries per message (negligible here).
An in-memory store would be simpler and faster, but loses everything on restart, can't be
shared between processes, grows without bound, and can't be audited.

Per message:
  1. scan_content() (Phase 4: rules, then the LLM classifier only if the rules flag it)
  2. BLOCKED    -> stored + security_logs (HIGH, blocked) + polite refusal; the
                   assistant LLM is NOT called, and the message never enters future history
     SUSPICIOUS -> stored + security_logs (MEDIUM, not blocked) + answered normally
                   BUT if the rules flagged it and the LLM classifier could not judge it
                   (no key / quota / timeout), it is refused like BLOCKED (status
                   "refused_unverified"): an unchecked, rule-flagged message never reaches
                   the assistant LLM (fail closed)
     SAFE       -> answered
  3. answer with the AssistantAgent (history = last messages, BLOCKED ones excluded):
       SAFE + asks to buy/sell/hold -> advice mode: one clarifying question if the amount or
                                       horizon is missing, then a sized verdict from the
                                       five-agent recommendation (recommendation_id returned)
       SAFE + mentions a stock      -> symbol mode: news + latest recommendation +
                                       Portfolio Agent analysis for that stock
       otherwise                    -> general mode: overall profile + holdings overview
       (SUSPICIOUS always gets general mode: no extra lookups for a possibly hostile prompt)
  4. a reply containing the system-prompt canary is withheld and logged (prompt leak)
  5. one chat_logs row per exchange (incl. refusals): symbols, context used, latency
Rate limit: MAX_MESSAGES_PER_MINUTE per user (each message can cost two LLM calls).
"""

import logging
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.assistant import AssistantAgent
from app.core.database import get_db, get_session_factory
from app.core.dependencies import get_current_user
from app.models import ChatConversation, ChatLog, ChatMessage, SecurityLog, User
from app.models.enums import SecurityEventType, SecurityStatus, Severity
from app.schemas.chat import ChatMessageIn, ChatMessageOut, ChatReply, ConversationSummary
from app.security.injection_classifier import BLOCKED, SAFE, SUSPICIOUS, scan_content

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

MAX_MESSAGES_PER_MINUTE = 15
REFUSAL = ("I can't help with that message. It looks like it contains instructions aimed at the assistant itself "
           "rather than a question about your investments. Please rephrase your question and I'll be happy to help.")
UNVERIFIED_REFUSAL = ("I can't answer that message right now: it contains wording our safety check needs to review, "
                      "and the check is temporarily unavailable. Please rephrase your question or try again in a minute.")
REFUSALS = (REFUSAL, UNVERIFIED_REFUSAL)


def _security_log(event: SecurityEventType, severity: Severity, blocked: bool, details: dict[str, Any]) -> SecurityLog:
    return SecurityLog(event_type=event, severity=severity, blocked=blocked, details={"origin": "chat", **details})


async def _get_conversation(db: AsyncSession, user: User, conversation_id: str) -> ChatConversation:
    conversation = await db.get(ChatConversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


@router.post("/message", response_model=ChatReply)
async def send_message(
    body: ChatMessageIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
):
    started = time.perf_counter()
    message = body.message.strip()
    if not message:
        raise HTTPException(422, "Message is empty")

    # ---- rate limit ----
    recent = await db.scalar(
        select(func.count()).select_from(ChatMessage).join(ChatConversation)
        .where(ChatConversation.user_id == user.id, ChatMessage.role == "user",
               ChatMessage.created_at >= datetime.now(UTC) - timedelta(minutes=1))
    )
    if recent >= MAX_MESSAGES_PER_MINUTE:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many messages; please wait a minute.",
                            headers={"Retry-After": "60"})

    # ---- conversation (new or existing, owned by this user) ----
    if body.conversation_id:
        conversation = await _get_conversation(db, user, body.conversation_id)
    else:
        conversation = ChatConversation(id=secrets.token_hex(16), user_id=user.id, title=message[:60])
        db.add(conversation)
        await db.flush()

    # ---- 1. injection scan of the incoming message ----
    scan = await scan_content(message)
    verdict = scan["verdict"]
    user_msg = ChatMessage(conversation_id=conversation.id, role="user", content=message,
                           security_status=SecurityStatus(verdict.lower()),
                           security_reason=None if verdict == SAFE else scan["reason"][:1000])
    db.add(user_msg)
    log_details = {"user_id": user.id, "conversation_id": conversation.id, "verdict": verdict, "stage": scan["stage"],
                   "matched_patterns": scan["matched_patterns"], "reason": scan["reason"], "message": message[:300]}

    # ---- 2a. BLOCKED, or flagged but unverifiable: refuse without calling the assistant LLM ----
    answer: dict[str, Any] = {"mode": "refused", "detected_symbols": [], "sources": [], "context": {}}
    unverified = verdict == SUSPICIOUS and bool(scan.get("classifier_unavailable"))
    if verdict == BLOCKED:
        logger.warning("[chat] BLOCKED message from user %s: %s", user.id, scan["reason"])
        db.add(_security_log(SecurityEventType.PROMPT_INJECTION, Severity.HIGH, True, log_details))
        reply_text, reply_status, sources = REFUSAL, "refused", []
    elif unverified:
        logger.warning("[chat] flagged message from user %s refused: classifier unavailable: %s", user.id, scan["reason"])
        db.add(_security_log(SecurityEventType.PROMPT_INJECTION, Severity.HIGH, True,
                             {**log_details, "kind": "unverified_refused"}))
        reply_text, reply_status, sources = UNVERIFIED_REFUSAL, "refused_unverified", []
    else:
        if verdict == SUSPICIOUS:
            logger.warning("[chat] SUSPICIOUS message from user %s answered: %s", user.id, scan["reason"])
            db.add(_security_log(SecurityEventType.PROMPT_INJECTION, Severity.MEDIUM, False, log_details))

        # ---- 3. answer, with history (oldest first; refused messages and their refusals excluded) ----
        rows = (await db.scalars(
            select(ChatMessage).where(ChatMessage.conversation_id == conversation.id)
            .order_by(ChatMessage.id.desc()).limit(40)
        )).all()
        chronological = list(reversed([r for r in rows if r is not user_msg]))
        skip: set[int] = set()
        for i, row in enumerate(chronological):
            reply_row = chronological[i + 1] if i + 1 < len(chronological) else None
            refused = reply_row is not None and reply_row.role == "assistant" and reply_row.content in REFUSALS
            if row.role == "user" and (row.security_status == SecurityStatus.BLOCKED
                                       or (row.security_status == SecurityStatus.SUSPICIOUS and refused)):
                skip.add(i)
                if refused:
                    skip.add(i + 1)
        history: list[tuple[str, str]] = [(row.role, row.content) for i, row in enumerate(chronological)
                                          if i not in skip]

        # Only SAFE messages get stock-specific lookups (news, recommendation, portfolio analysis);
        # a SUSPICIOUS one gets a general answer so it can't pull extra data into the context.
        answer = await AssistantAgent(session_factory).reply(user.id, history, message, enrich=verdict == SAFE)
        reply_text, reply_status, sources = answer["reply"], answer["status"], answer["sources"]

        # ---- 4. prompt-leak canary ----
        if answer["leak_detected"]:
            db.add(_security_log(SecurityEventType.AGENT_HIJACK, Severity.HIGH, True,
                                 {**log_details, "kind": "system_prompt_leak", "detail": "canary token in reply"}))

    assistant_msg = ChatMessage(conversation_id=conversation.id, role="assistant", content=reply_text)
    db.add(assistant_msg)
    conversation.updated_at = datetime.now(UTC)
    await db.flush()  # assigns message ids for the log row

    # ---- 5. chat_logs: one row per exchange (refusals included) ----
    db.add(ChatLog(
        user_id=user.id, conversation_id=conversation.id, user_message_id=user_msg.id,
        assistant_message_id=assistant_msg.id, message=message, reply=reply_text, security_verdict=verdict,
        status=reply_status, mode=answer["mode"], detected_symbols=answer["detected_symbols"],
        context_used=answer["context"], latency_ms=round((time.perf_counter() - started) * 1000),
    ))
    await db.commit()

    return ChatReply(
        conversation_id=conversation.id,
        reply=reply_text,
        status=reply_status,
        mode=answer["mode"],
        detected_symbols=answer["detected_symbols"],
        security={"verdict": verdict, "reason": None if verdict == SAFE else scan["reason"]},
        user_message_id=user_msg.id,
        assistant_message_id=assistant_msg.id,
        sources=sources,
        recommendation_id=answer.get("recommendation_id"),
    )


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(
        select(ChatConversation).where(ChatConversation.user_id == user.id)
        .order_by(ChatConversation.updated_at.desc()).limit(50)
    )
    return list(rows)


@router.get("/conversations/{conversation_id}", response_model=list[ChatMessageOut])
async def get_conversation(conversation_id: str, user: User = Depends(get_current_user),
                           db: AsyncSession = Depends(get_db)):
    conversation = await _get_conversation(db, user, conversation_id)
    rows = await db.scalars(
        select(ChatMessage).where(ChatMessage.conversation_id == conversation.id).order_by(ChatMessage.id)
    )
    return [ChatMessageOut(id=m.id, role=m.role, content=m.content, created_at=m.created_at,
                           security_status=m.security_status.value if m.security_status else None) for m in rows]
