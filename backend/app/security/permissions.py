"""
Agent permission system (agent-hijacking defence).

Each agent has an explicit allow-list of the tables it may read and write.
Every data access an agent makes goes through @enforce_permission, which
checks the allow-list BEFORE the wrapped function runs. Whatever an LLM
"decides" (for example after reading a poisoned article that says "now update
the recommendations table"), the code path refuses: the agent identity is
fixed in code at decoration time, never taken from LLM output.

On a violation:
  - the wrapped function is NOT called,
  - a security_logs row is written (event_type = agent_hijack, blocked = true)
    in its own transaction, so it survives even if the caller rolls back,
  - AgentPermissionError (a PermissionError) is raised.
If writing the audit row fails (e.g. DB down), the call is still blocked.

Design rules: default deny (unknown agent / table / operation -> denied), and
the allow-list is immutable at runtime.
"""

import asyncio
import functools
import inspect
import logging
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Literal, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import AsyncSessionLocal
from app.models import Base, SecurityLog
from app.models.enums import SecurityEventType, Severity

logger = logging.getLogger(__name__)

Operation = Literal["read", "write"]
OPERATIONS: frozenset[str] = frozenset({"read", "write"})

# Tables holding a specific user's private data: reading them without permission
# is treated as seriously as an unauthorised write.
USER_PRIVATE_TABLES = frozenset({"users", "user_profiles", "portfolio_holdings", "transactions",
                                 "broker_connections", "recommendations"})


def _freeze(permissions: dict[str, dict[str, list[str]]]) -> Mapping[str, Mapping[str, frozenset[str]]]:
    return MappingProxyType(
        {agent: MappingProxyType({op: frozenset(tables) for op, tables in ops.items()}) for agent, ops in permissions.items()}
    )


# The allow-list. Anything not listed here is denied.
AGENT_PERMISSIONS: Mapping[str, Mapping[str, frozenset[str]]] = _freeze({
    "news_agent": {"read": ["news_events"], "write": ["news_events"]},
    # Added to the spec's list: technical_indicators (cached Alpha Vantage RSI) and
    # price_history (daily closes for moving averages / local RSI; read-only, the
    # market data job writes it).
    "market_agent": {"read": ["market_snapshots", "technical_indicators", "price_history"],
                     "write": ["market_snapshots", "technical_indicators"]},
    # market_snapshots / price_history added (read-only): current prices are needed for P/L and
    # portfolio weights. They are public market data, not user data.
    "portfolio_agent": {"read": ["portfolio_holdings", "transactions", "market_snapshots", "price_history"],
                        "write": []},
    # user_profiles added to read: the agent must see the user's STATED preferences.
    "user_profiling_agent": {"read": ["transactions", "portfolio_holdings", "user_profiles"],
                             "write": ["user_profiles"]},
    # company_fundamentals added (read-only): the cached P/E / sector data. It is
    # refreshed by a system service, never written by the agent.
    "fundamental_economic_agent": {"read": ["news_events", "market_snapshots", "company_fundamentals"], "write": []},
    "recommendation_agent": {"read": ["news_events", "market_snapshots", "portfolio_holdings", "user_profiles"],
                             "write": ["recommendations"]},
    # The AI Assistant (chatbot) can read context for answers but WRITE NOTHING: even a
    # successful jailbreak of the chat LLM cannot change any data. (Chat history itself is
    # stored by the API route, not by the assistant.)
    # company_fundamentals: read-only, to recognise company names ("Infosys" -> INFY.NS) in messages.
    "assistant": {"read": ["news_events", "portfolio_holdings", "user_profiles", "recommendations",
                           "company_fundamentals"], "write": []},
})


def _validate_allow_list() -> None:
    """Fail at import time if the allow-list names an unknown operation or table (typo protection)."""
    known_tables = set(Base.metadata.tables)
    for agent, ops in AGENT_PERMISSIONS.items():
        for op, tables in ops.items():
            if op not in OPERATIONS:
                raise ValueError(f"{agent}: unknown operation {op!r}")
            unknown = tables - known_tables
            if unknown:
                raise ValueError(f"{agent}: unknown table(s) {sorted(unknown)} in {op!r}")


_validate_allow_list()


class AgentPermissionError(PermissionError):
    def __init__(self, agent_name: str, operation: str, table: str):
        super().__init__(f"Agent {agent_name!r} is not allowed to {operation} table {table!r}")
        self.agent_name, self.operation, self.table = agent_name, operation, table


def check_permission(agent_name: str, operation: Operation, table: str) -> bool:
    """True only if `table` is in `agent_name`'s allow-list for `operation`. Unknown anything -> False."""
    return table in AGENT_PERMISSIONS.get(agent_name, {}).get(operation, frozenset())


# ---------------- audit logging ----------------

# Separate from request sessions on purpose (own transaction). Tests point it at the test DB.
audit_session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal

_pending_audit_tasks: set[asyncio.Task] = set()  # keeps fire-and-forget tasks from sync callers alive


def _severity(operation: str, table: str) -> Severity:
    return Severity.HIGH if operation == "write" or table in USER_PRIVATE_TABLES else Severity.MEDIUM


async def log_violation(agent_name: str, operation: str, table: str, function: str) -> None:
    """Write one agent_hijack row to security_logs. Never raises (the caller is blocked regardless)."""
    logger.warning("[permissions] BLOCKED %s -> %s %s (in %s)", agent_name, operation, table, function)
    try:
        async with audit_session_factory() as db:
            db.add(
                SecurityLog(
                    event_type=SecurityEventType.AGENT_HIJACK,
                    severity=_severity(operation, table),
                    blocked=True,
                    details={
                        "kind": "agent_hijack_attempt",
                        "agent": agent_name,
                        "operation": operation,
                        "table": table,
                        "function": function,
                        "allowed": {op: sorted(t) for op, t in AGENT_PERMISSIONS.get(agent_name, {}).items()},
                    },
                )
            )
            await db.commit()
    except Exception:
        logger.exception("[permissions] could not write security log for %s %s %s", agent_name, operation, table)


# ---------------- decorator ----------------

F = TypeVar("F", bound=Callable[..., Any])


def enforce_permission(agent_name: str, operation: Operation, table: str) -> Callable[[F], F]:
    """
    Guard a function that reads/writes `table` on behalf of `agent_name`.

        @enforce_permission("news_agent", "write", "news_events")
        async def save_news_event(db, row): ...

    Works on async functions (logs the violation, then raises) and on plain
    functions (raises immediately; the log entry is written in the background
    if an event loop is running, otherwise synchronously).
    The names are validated when decorating, so a typo fails at import, not at runtime.
    """
    if agent_name not in AGENT_PERMISSIONS:
        raise ValueError(f"Unknown agent {agent_name!r}; add it to AGENT_PERMISSIONS first")
    if operation not in OPERATIONS:
        raise ValueError(f"operation must be 'read' or 'write', got {operation!r}")
    if table not in Base.metadata.tables:
        raise ValueError(f"Unknown table {table!r}")

    def decorator(func: F) -> F:
        name = f"{func.__module__}.{func.__qualname__}"

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if not check_permission(agent_name, operation, table):
                    await log_violation(agent_name, operation, table, name)
                    raise AgentPermissionError(agent_name, operation, table)
                return await func(*args, **kwargs)

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not check_permission(agent_name, operation, table):
                audit = log_violation(agent_name, operation, table, name)
                try:
                    task = asyncio.get_running_loop().create_task(audit)
                    _pending_audit_tasks.add(task)
                    task.add_done_callback(_pending_audit_tasks.discard)
                except RuntimeError:  # no running loop (scripts, threads)
                    asyncio.run(audit)
                raise AgentPermissionError(agent_name, operation, table)
            return func(*args, **kwargs)

        return sync_wrapper  # type: ignore[return-value]

    return decorator
