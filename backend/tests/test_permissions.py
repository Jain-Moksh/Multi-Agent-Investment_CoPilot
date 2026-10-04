"""
Agent permission system. The headline test: a hijacked news_agent tries to
write a fake BUY into recommendations -> blocked, nothing written, logged.
Logging tests use PostgreSQL (TEST_DATABASE_URL); pure checks need no DB.
"""

import asyncio

import pytest
from sqlalchemy import func, select

from app.models import NewsEvent, Recommendation, SecurityLog, User
from app.models.enums import Decision, SecurityEventType, SecurityStatus, Severity
from app.security import permissions as perm
from app.security.permissions import AgentPermissionError, check_permission, enforce_permission


@pytest.fixture
def audit_db(pg_sessionmaker, monkeypatch):
    monkeypatch.setattr(perm, "audit_session_factory", pg_sessionmaker)
    return pg_sessionmaker


async def count(session_factory, model) -> int:
    async with session_factory() as db:
        return await db.scalar(select(func.count()).select_from(model))


# ---------------- check_permission ----------------

@pytest.mark.parametrize(
    "agent, op, table, allowed",
    [
        ("news_agent", "read", "news_events", True),
        ("news_agent", "write", "news_events", True),
        ("news_agent", "write", "recommendations", False),       # the hijack scenario
        ("news_agent", "read", "portfolio_holdings", False),      # can't read user portfolios
        ("market_agent", "write", "market_snapshots", True),
        ("market_agent", "read", "transactions", False),
        ("portfolio_agent", "read", "transactions", True),
        ("portfolio_agent", "write", "portfolio_holdings", False),  # read-only agent
        ("user_profiling_agent", "write", "user_profiles", True),
        ("user_profiling_agent", "write", "recommendations", False),
        ("fundamental_economic_agent", "read", "market_snapshots", True),
        ("fundamental_economic_agent", "write", "news_events", False),
        ("recommendation_agent", "write", "recommendations", True),
        ("recommendation_agent", "read", "transactions", False),
        ("recommendation_agent", "read", "users", False),
    ],
)
def test_check_permission(agent, op, table, allowed):
    assert check_permission(agent, op, table) is allowed


@pytest.mark.parametrize(
    "agent, op, table",
    [("unknown_agent", "read", "news_events"), ("news_agent", "delete", "news_events"),
     ("news_agent", "read", "no_such_table"), ("", "", "")],
)
def test_default_deny(agent, op, table):
    assert check_permission(agent, op, table) is False


def test_allow_list_cannot_be_modified_at_runtime():
    with pytest.raises(TypeError):
        perm.AGENT_PERMISSIONS["news_agent"] = {"write": frozenset({"recommendations"})}
    with pytest.raises(TypeError):
        perm.AGENT_PERMISSIONS["news_agent"]["write"] = frozenset({"recommendations"})
    with pytest.raises(AttributeError):
        perm.AGENT_PERMISSIONS["news_agent"]["write"].add("recommendations")
    assert check_permission("news_agent", "write", "recommendations") is False


@pytest.mark.parametrize(
    "agent, op, table, message",
    [("newz_agent", "read", "news_events", "Unknown agent"),
     ("news_agent", "update", "news_events", "operation must be"),
     ("news_agent", "read", "news_event", "Unknown table")],
)
def test_typos_fail_at_decoration_time(agent, op, table, message):
    with pytest.raises(ValueError, match=message):
        enforce_permission(agent, op, table)


# ---------------- the hijack scenario (PostgreSQL) ----------------

async def test_hijacked_news_agent_cannot_write_a_recommendation(audit_db):
    async with audit_db() as db:
        db.add(User(id=1, email="victim@example.com", hashed_password="x"))
        await db.commit()

    # Imagine a poisoned article convinced the news agent's LLM to "save a strong
    # BUY for XYZ". The code path it reaches is guarded by the news agent's identity:
    @enforce_permission("news_agent", "write", "recommendations")
    async def save_recommendation(user_id: int, symbol: str):
        async with audit_db() as db:
            db.add(Recommendation(user_id=user_id, symbol=symbol, decision=Decision.BUY,
                                  confidence_score=0.99, explanation="Guaranteed 10x!"))
            await db.commit()

    with pytest.raises(AgentPermissionError) as exc:
        await save_recommendation(1, "XYZ.NS")

    assert isinstance(exc.value, PermissionError)
    assert str(exc.value) == "Agent 'news_agent' is not allowed to write table 'recommendations'"
    assert await count(audit_db, Recommendation) == 0          # the function body never ran

    async with audit_db() as db:
        log = await db.scalar(select(SecurityLog))
    assert log.event_type == SecurityEventType.AGENT_HIJACK
    assert log.severity == Severity.HIGH and log.blocked is True
    assert log.details["kind"] == "agent_hijack_attempt"
    assert (log.details["agent"], log.details["operation"], log.details["table"]) == ("news_agent", "write", "recommendations")
    assert log.details["function"].endswith("save_recommendation")
    assert log.details["allowed"] == {"read": ["news_events"], "write": ["news_events"]}


async def test_permitted_call_runs_normally_and_logs_nothing(audit_db):
    @enforce_permission("news_agent", "write", "news_events")
    async def save_news(title: str) -> int:
        async with audit_db() as db:
            row = NewsEvent(source_api="test", url="https://example.com/a", title=title,
                            security_status=SecurityStatus.SAFE)
            db.add(row)
            await db.commit()
            return row.id

    assert isinstance(await save_news("RBI holds rates"), int)
    assert save_news.__name__ == "save_news"  # functools.wraps keeps the identity
    assert await count(audit_db, NewsEvent) == 1
    assert await count(audit_db, SecurityLog) == 0


async def test_unauthorised_read_of_private_data_is_logged_high(audit_db):
    @enforce_permission("news_agent", "read", "portfolio_holdings")
    async def peek_at_portfolios():
        raise AssertionError("must not run")

    with pytest.raises(AgentPermissionError):
        await peek_at_portfolios()
    async with audit_db() as db:
        assert (await db.scalar(select(SecurityLog))).severity == Severity.HIGH


async def test_still_blocked_when_audit_logging_fails(monkeypatch, caplog):
    def broken_factory():
        raise ConnectionRefusedError("database down")

    monkeypatch.setattr(perm, "audit_session_factory", broken_factory)
    ran = False

    @enforce_permission("market_agent", "write", "recommendations")
    async def write_rec():
        nonlocal ran
        ran = True

    with pytest.raises(AgentPermissionError):
        await write_rec()
    assert ran is False
    assert "could not write security log" in caplog.text


async def test_sync_functions_are_guarded_too(audit_db):
    calls = []

    @enforce_permission("portfolio_agent", "read", "transactions")
    def allowed(x):
        calls.append(x)
        return x * 2

    @enforce_permission("portfolio_agent", "write", "portfolio_holdings")
    def forbidden():
        calls.append("forbidden ran")

    assert allowed(21) == 42
    with pytest.raises(AgentPermissionError):
        forbidden()
    await asyncio.gather(*perm._pending_audit_tasks)  # let the background audit write finish

    assert calls == [21]
    async with audit_db() as db:
        log = await db.scalar(select(SecurityLog))
    assert log.details["operation"] == "write" and log.details["table"] == "portfolio_holdings"


async def test_every_agent_denied_outside_its_allow_list(audit_db):
    """Exhaustive: for every agent x operation x table, the decorator agrees with the allow-list."""
    from app.models import Base

    denied = 0
    for agent in perm.AGENT_PERMISSIONS:
        for op in ("read", "write"):
            for table in Base.metadata.tables:
                @enforce_permission(agent, op, table)
                async def action():
                    return "ran"

                if check_permission(agent, op, table):
                    assert await action() == "ran"
                else:
                    with pytest.raises(AgentPermissionError):
                        await action()
                    denied += 1
    assert await count(audit_db, SecurityLog) == denied
