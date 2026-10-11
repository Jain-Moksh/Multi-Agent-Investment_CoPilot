"""
Agent orchestrator (LangGraph): run all five specialist agents for one
(user, stock) and collect their outputs for the decision layer.

    analysis = await run_analysis(user_id=7, symbol="INFY.NS")
    analysis["agents"]["market_agent"]["signal"]   # -> 0.32

Graph:

                      +--> news_agent ------------------+
                      +--> market_agent ----------------+
    START -> prepare -+--> portfolio_agent -------------+--> aggregate -> END
                      +--> user_profiling_agent --------+
                      +--> fundamental_economic_agent --+

  prepare    checks the user exists, makes sure there is FRESH market data for the symbol
             (the scheduler only collects prices for held stocks, so for any other stock the
             price/history/RSI are fetched now) and rejects symbols for which no price exists
             at all (UnknownSymbolError -> HTTP 404, nothing saved). Then it looks up the
             company name once (the News Agent searches better with "Infosys" than "INFY"; it
             also warms the fundamentals cache the Fundamental Agent reads). These are
             system-level data refreshes of public market data, like the scheduler's jobs.
  5 agents   independent of each other, so LangGraph runs them in the same step,
             concurrently (asyncio). Each writes only its own key into the shared state.
  aggregate  waits for all five, then assembles the combined result.

Failure isolation: an agent that crashes or times out (AGENT_TIMEOUT) never stops
the others. Its slot gets a neutral placeholder (status "error"/"timeout", signal 0,
confidence 0) and the reason is recorded in `errors`, so the decision layer can see
exactly which evidence is missing. A permission violation inside an agent is already
written to security_logs by the agent's guard; here it is just recorded like any error.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.fundamental_economic_agent import FundamentalEconomicAgent
from app.agents.market_agent import MarketAgent
from app.agents.news_agent import NewsAgent
from app.agents.portfolio_agent import PortfolioAgent
from app.agents.user_profiling_agent import UserProfilingAgent
from app.core.database import AsyncSessionLocal
from app.models import MarketSnapshot, User
from app.models.enums import AssetType
from app.schemas.portfolio import normalize_symbol
from app.services import fundamentals as fundamentals_service
from app.services import market_data

logger = logging.getLogger(__name__)

AGENT_NAMES = ("news_agent", "market_agent", "portfolio_agent", "user_profiling_agent", "fundamental_economic_agent")
AGENT_TIMEOUT = 90.0  # seconds per agent; the News Agent's LLM call is the slowest part
# A stored price younger than this is used as is; older (or none) -> fetched on demand.
# Matches the scheduler's market job interval, so held stocks are normally not re-fetched.
MARKET_DATA_MAX_AGE = timedelta(minutes=30)


class UnknownSymbolError(ValueError):
    """No price could be found for the symbol (not a listed ticker, or every price source is down)."""


async def ensure_market_data(symbol: str, session_factory: async_sessionmaker[AsyncSession]) -> bool:
    """
    Make sure `symbol` has a recent market_snapshots row, fetching price, daily history and
    RSI now if needed. Returns False only when no price exists at all (nothing stored and
    the fetch failed). A stale stored price is still accepted if the fetch fails.
    """
    async with session_factory() as db:
        latest = await db.scalar(select(func.max(MarketSnapshot.fetched_at)).where(MarketSnapshot.symbol == symbol))
    if latest is not None:
        latest = latest if latest.tzinfo else latest.replace(tzinfo=UTC)
        if datetime.now(UTC) - latest < MARKET_DATA_MAX_AGE:
            return True
    update = await market_data.update_market_snapshot(symbol, session_factory)
    if update.quote is None and latest is not None:
        logger.warning("[orchestrator] could not refresh %s; using the stored price from %s", symbol, latest)
    return update.quote is not None or latest is not None


def _merge(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    """Reducer: parallel nodes each add their own keys to the same dict."""
    return {**(left or {}), **(right or {})}


class AnalysisState(TypedDict, total=False):
    # inputs
    user_id: int
    symbol: str
    # set by `prepare`
    company_name: str | None
    started_at: str
    # filled concurrently by the five agent nodes (merged by the reducer)
    agent_outputs: Annotated[dict[str, dict[str, Any]], _merge]
    errors: Annotated[dict[str, str], _merge]
    timings_ms: Annotated[dict[str, int], _merge]
    # set by `aggregate`
    result: dict[str, Any]


class UnknownUserError(ValueError):
    pass


def placeholder(agent_name: str, symbol: str, status: str, reason: str) -> dict[str, Any]:
    """Neutral stand-in for an agent that failed: no influence on the decision."""
    return {"agent": agent_name, "symbol": symbol, "status": status, "signal": 0.0, "confidence": 0.0,
            "summary": reason, "rationale": reason}


def build_graph(session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal) -> Any:
    """Compile the analysis graph. Agents are created per graph with the given session factory."""
    agents = {
        "news_agent": NewsAgent(session_factory),
        "market_agent": MarketAgent(session_factory),
        "portfolio_agent": PortfolioAgent(session_factory),
        "user_profiling_agent": UserProfilingAgent(session_factory),
        "fundamental_economic_agent": FundamentalEconomicAgent(session_factory),
    }
    calls: dict[str, Callable[[AnalysisState], Awaitable[dict[str, Any]]]] = {
        "news_agent": lambda s: agents["news_agent"].analyze(s["symbol"], company_name=s.get("company_name")),
        "market_agent": lambda s: agents["market_agent"].analyze(s["symbol"]),
        "portfolio_agent": lambda s: agents["portfolio_agent"].analyze(s["user_id"], s["symbol"]),
        "user_profiling_agent": lambda s: agents["user_profiling_agent"].analyze(s["user_id"]),
        "fundamental_economic_agent": lambda s: agents["fundamental_economic_agent"].analyze(s["symbol"]),
    }

    async def prepare(state: AnalysisState) -> dict[str, Any]:
        async with session_factory() as db:
            if await db.get(User, state["user_id"]) is None:
                raise UnknownUserError(f"user {state['user_id']} does not exist")
        if not await ensure_market_data(state["symbol"], session_factory):
            raise UnknownSymbolError(
                f"No market data found for {state['symbol']}: it is not a listed NSE/BSE ticker, "
                "or the price sources are unreachable right now."
            )
        company_name = None
        try:  # system-level lookup (public data); a failure just means the ticker is used instead
            row = await fundamentals_service.refresh_if_stale(state["symbol"], session_factory)
            company_name = row.name if row else None
        except Exception as exc:
            logger.warning("[orchestrator] company name lookup failed for %s: %s", state["symbol"], exc)
        return {"company_name": company_name, "started_at": datetime.now(UTC).isoformat(timespec="seconds")}

    def agent_node(name: str) -> Callable[[AnalysisState], Awaitable[dict[str, Any]]]:
        async def run(state: AnalysisState) -> dict[str, Any]:
            start = time.perf_counter()
            try:
                output = await asyncio.wait_for(calls[name](state), timeout=AGENT_TIMEOUT)
                error = None
            except TimeoutError:
                error = f"timed out after {AGENT_TIMEOUT:.0f}s"
                output = placeholder(name, state["symbol"], "timeout", f"{name} {error}")
            except Exception as exc:  # incl. AgentPermissionError (already in security_logs)
                error = f"{type(exc).__name__}: {exc}"
                output = placeholder(name, state["symbol"], "error", f"{name} failed: {error}")
                logger.exception("[orchestrator] %s failed for %s", name, state["symbol"])
            update: dict[str, Any] = {
                "agent_outputs": {name: output},
                "timings_ms": {name: round((time.perf_counter() - start) * 1000)},
            }
            if error:
                update["errors"] = {name: error}
            return update

        run.__name__ = name
        return run

    async def aggregate(state: AnalysisState) -> dict[str, Any]:
        outputs = state.get("agent_outputs", {})
        agents_out = {name: outputs.get(name) or placeholder(name, state["symbol"], "error", "no output") for name in AGENT_NAMES}
        return {"result": {
            "user_id": state["user_id"],
            "symbol": state["symbol"],
            "company_name": state.get("company_name"),
            "agents": agents_out,
            "signals": {name: out.get("signal", 0.0) for name, out in agents_out.items()},
            "confidences": {name: out.get("confidence", 0.0) for name, out in agents_out.items()},
            "statuses": {name: out.get("status") for name, out in agents_out.items()},
            "errors": state.get("errors", {}),
            "timings_ms": state.get("timings_ms", {}),
            "started_at": state.get("started_at"),
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }}

    graph = StateGraph(AnalysisState)
    graph.add_node("prepare", prepare)
    graph.add_node("aggregate", aggregate)
    graph.add_edge(START, "prepare")
    for name in AGENT_NAMES:
        graph.add_node(name, agent_node(name))
        graph.add_edge("prepare", name)    # fan out: all five start together
        graph.add_edge(name, "aggregate")  # fan in: aggregate waits for all five
    graph.add_edge("aggregate", END)
    return graph.compile()


async def run_analysis(
    user_id: int, symbol: str, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal
) -> dict[str, Any]:
    """
    Run all five agents for (user_id, symbol) and return:
      {user_id, symbol, company_name,
       agents:      {agent_name: that agent's full output dict},
       signals / confidences / statuses: {agent_name: value}   (quick view for Phase 7.2),
       errors:      {agent_name: reason} for agents that failed or timed out,
       timings_ms:  {agent_name: duration}, started_at, finished_at}
    Raises UnknownUserError if the user doesn't exist.
    """
    symbol = normalize_symbol(AssetType.STOCK, symbol)
    start = time.perf_counter()
    final = await build_graph(session_factory).ainvoke(
        {"user_id": user_id, "symbol": symbol, "agent_outputs": {}, "errors": {}, "timings_ms": {}}
    )
    result = final["result"]
    result["timings_ms"]["total"] = round((time.perf_counter() - start) * 1000)
    logger.info("[orchestrator] %s for user %s: statuses %s, total %d ms", symbol, user_id, result["statuses"],
                result["timings_ms"]["total"])
    return result
