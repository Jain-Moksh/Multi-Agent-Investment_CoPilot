"""User Profiling Agent: behaviour metrics, rules, stated-vs-behaviour combination, and the
agent end to end on PostgreSQL (TEST_DATABASE_URL)."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents import user_profiling_agent as upa
from app.agents.user_profiling_agent import (
    UserProfilingAgent, classify_horizon, classify_risk, combine, holding_metrics, portfolio_mix, risk_points,
    trades_per_month,
)
from app.models import AgentLog, PortfolioHolding, Transaction, User, UserProfile
from app.models.enums import AssetType, InvestmentHorizon, RiskAppetite, TransactionAction, TransactionSource
from app.security.permissions import check_permission

D = Decimal
TODAY = datetime.now(UTC).date()
R, H = RiskAppetite, InvestmentHorizon


def trade(symbol, action, qty, price, days_ago):
    return SimpleNamespace(symbol=symbol, action=TransactionAction(action), quantity=D(str(qty)), price=D(str(price)),
                           transaction_date=datetime.now(UTC) - timedelta(days=days_ago))


# ---------------- metrics ----------------

def test_holding_metrics_value_weighted_fifo():
    trades = [
        trade("A", "buy", 10, 100, 500), trade("A", "sell", 10, 120, 100),   # held 400 days, value 1,000
        trade("B", "buy", 10, 300, 20), trade("B", "sell", 10, 310, 10),     # held 10 days, value 3,000 (quick flip)
    ]
    m = holding_metrics(trades, TODAY)
    assert m["avg_holding_days"] == 107.5      # (400 x 1000 + 10 x 3000) / 4000
    assert m["quick_flip_pct"] == 50.0         # 10 of 20 sold shares held < 30 days


def test_open_lots_count_until_today():
    m = holding_metrics([trade("A", "buy", 5, 100, 200)], TODAY)
    assert m["avg_holding_days"] == 200 and m["quick_flip_pct"] == 0.0


def test_trades_per_month_has_one_month_minimum():
    assert trades_per_month([trade("A", "buy", 1, 1, 3)] * 6, TODAY) == 6.0        # 6 trades, 3 days -> per 30 days
    assert trades_per_month([trade("A", "buy", 1, 1, 300)] * 10, TODAY) == 1.0      # 10 trades over 10 months
    assert trades_per_month([], TODAY) == 0.0


def test_portfolio_mix_at_cost():
    holdings = [SimpleNamespace(asset_type=AssetType.STOCK, symbol="INFY.NS", quantity=D(10), avg_buy_price=D(1000)),
                SimpleNamespace(asset_type=AssetType.STOCK, symbol="TCS.NS", quantity=D(1), avg_buy_price=D(5000)),
                SimpleNamespace(asset_type=AssetType.FD, symbol="FD", quantity=D(1), avg_buy_price=D(35000))]
    assert portfolio_mix(holdings) == {"equity_share_pct": 30.0, "max_position_pct": 20.0, "distinct_stocks": 2}
    assert portfolio_mix([])["equity_share_pct"] is None


# ---------------- rules ----------------

@pytest.mark.parametrize("days, horizon", [(400, H.LONG_TERM), (365, H.MEDIUM_TERM), (90, H.MEDIUM_TERM),
                                           (89, H.SHORT_TERM), (None, None)])
def test_classify_horizon(days, horizon):
    assert classify_horizon(days) == horizon


@pytest.mark.parametrize(
    "metrics, expected",
    [
        (dict(trades_per_month=12, quick_flip_pct=50, equity_share_pct=95, max_position_pct=60), R.AGGRESSIVE),
        (dict(trades_per_month=4, quick_flip_pct=10, equity_share_pct=85, max_position_pct=20), R.AGGRESSIVE),
        (dict(trades_per_month=2, quick_flip_pct=0, equity_share_pct=60, max_position_pct=15), R.MODERATE),
        (dict(trades_per_month=0.5, quick_flip_pct=0, equity_share_pct=30, max_position_pct=10), R.CONSERVATIVE),
        (dict(trades_per_month=0.5, quick_flip_pct=0, equity_share_pct=None, max_position_pct=None), R.CONSERVATIVE),
    ],
)
def test_classify_risk(metrics, expected):
    assert classify_risk(risk_points(metrics)) == expected


@pytest.mark.parametrize(
    "stated, behaviour, kind, expected",
    [
        (R.AGGRESSIVE, R.CONSERVATIVE, "risk", (R.CONSERVATIVE, "blended")),   # more conservative wins
        (R.CONSERVATIVE, R.AGGRESSIVE, "risk", (R.CONSERVATIVE, "blended")),
        (R.MODERATE, R.MODERATE, "risk", (R.MODERATE, "stated")),
        (None, R.AGGRESSIVE, "risk", (R.AGGRESSIVE, "behaviour")),
        (R.AGGRESSIVE, None, "risk", (R.AGGRESSIVE, "stated")),
        (None, None, "risk", (R.MODERATE, "default")),
        (H.LONG_TERM, H.SHORT_TERM, "horizon", (H.LONG_TERM, "stated")),       # stated horizon wins
        (None, H.SHORT_TERM, "horizon", (H.SHORT_TERM, "behaviour")),
        (None, None, "horizon", (H.MEDIUM_TERM, "default")),
    ],
)
def test_combine(stated, behaviour, kind, expected):
    assert combine(stated, behaviour, kind=kind) == expected


# ---------------- the agent (PostgreSQL) ----------------

async def setup_user(session_factory, user_id=1, stated_risk=None, stated_horizon=None, effective_risk=None):
    async with session_factory() as db:
        db.add(User(id=user_id, email=f"u{user_id}@x.com", hashed_password="x"))
        await db.flush()
        if stated_risk or stated_horizon or effective_risk:
            db.add(UserProfile(user_id=user_id, stated_risk_appetite=stated_risk, stated_investment_horizon=stated_horizon,
                               risk_appetite=effective_risk, goals="Retirement corpus"))
        await db.commit()


async def add_trades(session_factory, user_id, trades):
    async with session_factory() as db:
        for t in trades:
            db.add(Transaction(user_id=user_id, symbol=t.symbol, action=t.action, quantity=t.quantity, price=t.price,
                               transaction_date=t.transaction_date, source=TransactionSource.TRADEBOOK_UPLOAD))
        await db.commit()


async def add_holding(session_factory, user_id, symbol, qty, cost, asset=AssetType.STOCK):
    async with session_factory() as db:
        db.add(PortfolioHolding(user_id=user_id, asset_type=asset, symbol=symbol, quantity=D(str(qty)),
                                avg_buy_price=D(str(cost)), source=TransactionSource.MANUAL))
        await db.commit()


async def stored_profile(session_factory, user_id=1) -> UserProfile:
    async with session_factory() as db:
        return await db.get(UserProfile, user_id)


ACTIVE_TRADER = ([trade(f"S{i}.NS", "buy", 10, 100, 25 - i) for i in range(6)]
                 + [trade(f"S{i}.NS", "sell", 10, 105, 20 - i) for i in range(6)])     # 12 trades in ~25 days, 5-day flips
BUY_AND_HOLD = [trade(f"L{i}.NS", "buy", 10, 1000, 700 - i * 30) for i in range(6)]    # 6 buys, held ~1.5-2 years


async def test_active_trader_is_aggressive_short_term_and_saved(pg_sessionmaker):
    await setup_user(pg_sessionmaker)
    await add_trades(pg_sessionmaker, 1, ACTIVE_TRADER)
    await add_holding(pg_sessionmaker, 1, "S0.NS", 50, 100)

    r = await UserProfilingAgent(pg_sessionmaker).analyze(1)

    assert (r["agent"], r["status"], r["risk_appetite"], r["investment_horizon"]) == \
        ("user_profiling_agent", "ok", "aggressive", "short_term")
    assert r["basis"] == {"risk": "behaviour", "horizon": "behaviour"}
    assert r["behaviour"]["quick_flip_pct"] == 100.0 and r["behaviour"]["trades_per_month"] == 12.0
    assert any("very frequent trading" in reason for reason in r["risk_reasons"])
    assert r["signal"] == 0.0 and r["confidence"] == 0.6                       # 12 trades / 20
    assert "Effective profile: aggressive, short-term." in r["summary"]

    p = await stored_profile(pg_sessionmaker)
    assert (p.risk_appetite, p.investment_horizon) == (R.AGGRESSIVE, H.SHORT_TERM)
    assert p.profile_basis == {"risk": "behaviour", "horizon": "behaviour"}
    assert p.behavior_metrics["transactions_count"] == 12 and p.classified_at is not None
    assert p.stated_risk_appetite is None                                      # never invented


async def test_buy_and_hold_is_long_term(pg_sessionmaker):
    await setup_user(pg_sessionmaker)
    await add_trades(pg_sessionmaker, 1, BUY_AND_HOLD)
    await add_holding(pg_sessionmaker, 1, "L0.NS", 10, 1000)
    await add_holding(pg_sessionmaker, 1, "FD", 1, 50000, asset=AssetType.FD)  # 16.7% equity -> conservative points
    r = await UserProfilingAgent(pg_sessionmaker).analyze(1)
    assert (r["risk_appetite"], r["investment_horizon"]) == ("conservative", "long_term")


async def test_stated_aggressive_but_cautious_behaviour_is_blended_conservative(pg_sessionmaker):
    await setup_user(pg_sessionmaker, stated_risk=R.AGGRESSIVE, stated_horizon=H.SHORT_TERM)
    await add_trades(pg_sessionmaker, 1, BUY_AND_HOLD)
    await add_holding(pg_sessionmaker, 1, "FD", 1, 50000, asset=AssetType.FD)
    await add_holding(pg_sessionmaker, 1, "L0.NS", 10, 1000)

    r = await UserProfilingAgent(pg_sessionmaker).analyze(1)
    assert r["risk_appetite"] == "conservative" and r["basis"]["risk"] == "blended"
    assert r["investment_horizon"] == "short_term" and r["basis"]["horizon"] == "stated"   # stated horizon kept
    assert "The user stated aggressive, so the more conservative 'conservative' is used." in r["summary"]
    assert "Their stated short-term horizon is kept." in r["summary"]

    p = await stored_profile(pg_sessionmaker)
    assert p.stated_risk_appetite == R.AGGRESSIVE and p.stated_investment_horizon == H.SHORT_TERM  # untouched
    assert p.risk_appetite == R.CONSERVATIVE and p.goals == "Retirement corpus"                    # other fields kept


async def test_few_trades_use_stated_preferences(pg_sessionmaker):
    await setup_user(pg_sessionmaker, stated_risk=R.MODERATE, stated_horizon=H.LONG_TERM)
    await add_trades(pg_sessionmaker, 1, ACTIVE_TRADER[:2])
    r = await UserProfilingAgent(pg_sessionmaker).analyze(1)
    assert r["status"] == "insufficient_history"
    assert (r["risk_appetite"], r["investment_horizon"]) == ("moderate", "long_term")
    assert r["basis"] == {"risk": "stated", "horizon": "stated"} and r["confidence"] == 0.5
    assert r["summary"].startswith("Only 2 trade(s) on record")


async def test_new_user_gets_defaults_and_a_profile_row(pg_sessionmaker):
    await setup_user(pg_sessionmaker)
    r = await UserProfilingAgent(pg_sessionmaker).analyze(1)
    assert (r["risk_appetite"], r["investment_horizon"], r["confidence"]) == ("moderate", "medium_term", 0.0)
    assert r["basis"] == {"risk": "default", "horizon": "default"}
    p = await stored_profile(pg_sessionmaker)
    assert p is not None and p.risk_appetite == R.MODERATE


async def test_rerunning_does_not_drift(pg_sessionmaker):
    """The effective value must never be read back as if it were the user's stated choice."""
    await setup_user(pg_sessionmaker, stated_risk=R.CONSERVATIVE)
    await add_trades(pg_sessionmaker, 1, ACTIVE_TRADER)
    agent = UserProfilingAgent(pg_sessionmaker)
    first, second = await agent.analyze(1), await agent.analyze(1)
    assert first["risk_appetite"] == second["risk_appetite"] == "conservative"
    assert (await stored_profile(pg_sessionmaker)).stated_risk_appetite == R.CONSERVATIVE


async def test_only_this_users_trades_count(pg_sessionmaker):
    await setup_user(pg_sessionmaker, 1)
    await setup_user(pg_sessionmaker, 2)
    await add_trades(pg_sessionmaker, 2, ACTIVE_TRADER)
    r = await UserProfilingAgent(pg_sessionmaker).analyze(1)
    assert r["behaviour"]["transactions_count"] == 0 and r["status"] == "insufficient_history"


async def test_every_call_is_logged(pg_sessionmaker):
    await setup_user(pg_sessionmaker)
    await UserProfilingAgent(pg_sessionmaker).analyze(1)
    async with pg_sessionmaker() as db:
        log = await db.scalar(select(AgentLog))
    assert log.agent_name == "user_profiling_agent" and json.loads(log.input_summary) == {"user_id": 1}


async def test_cannot_write_stated_preferences(pg_sessionmaker):
    await setup_user(pg_sessionmaker)
    with pytest.raises(ValueError, match="never overwrite"):
        await UserProfilingAgent(pg_sessionmaker)._save_profile(1, {"stated_risk_appetite": R.AGGRESSIVE})


# ---------------- permissions ----------------

def test_permissions():
    for method in (UserProfilingAgent._transactions, UserProfilingAgent._holdings, UserProfilingAgent._profile,
                   UserProfilingAgent._save_profile):
        assert hasattr(method, "__wrapped__")
    assert check_permission("user_profiling_agent", "write", "user_profiles")
    assert check_permission("user_profiling_agent", "read", "user_profiles")
    for table in ("recommendations", "news_events", "portfolio_holdings", "transactions", "users"):
        assert not check_permission("user_profiling_agent", "write", table)
    assert upa.MIN_TRADES == 5
