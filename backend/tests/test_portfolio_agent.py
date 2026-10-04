"""Portfolio Agent: FIFO / risk maths and the agent end to end on PostgreSQL (TEST_DATABASE_URL)."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.agents.portfolio_agent import PortfolioAgent, compute_signal, concentration_risk, fifo
from app.models import AgentLog, MarketSnapshot, PortfolioHolding, PriceHistory, Transaction, User
from app.models.enums import AssetType, TransactionAction, TransactionSource
from app.security.permissions import check_permission

NOW = datetime.now(UTC)
D = Decimal


def trade(action: str, qty, price, days_ago: int):
    return SimpleNamespace(action=TransactionAction(action), quantity=D(str(qty)), price=D(str(price)),
                           transaction_date=NOW - timedelta(days=days_ago))


# ---------------- pure maths ----------------

def test_fifo_realised_pl_and_open_lots():
    result = fifo([trade("buy", 10, 100, 50), trade("buy", 5, 120, 40), trade("sell", 12, 150, 10)])
    assert result.realized_pl == D(560)            # (150-100)x10 + (150-120)x2
    assert result.open_quantity == D(3)            # 3 left from the second lot
    assert result.oldest_open_date == (NOW - timedelta(days=40)).date()
    assert result.complete


def test_fifo_sell_before_recorded_history_is_flagged():
    result = fifo([trade("buy", 5, 100, 20), trade("sell", 8, 110, 5)])
    assert result.realized_pl == D(50) and result.open_quantity == 0 and not result.complete


def test_fifo_order_by_date_not_input_order():
    result = fifo([trade("sell", 5, 200, 1), trade("buy", 5, 100, 30)])
    assert result.realized_pl == D(500) and result.complete


@pytest.mark.parametrize("weight, risk, signal",
                         [(None, "none", 0.1), (0.0, "none", 0.1), (5, "low", 0.1), (10, "medium", -0.2),
                          (25, "medium", -0.2), (30, "high", -0.6), (55, "high", -0.9)])
def test_concentration_and_signal(weight, risk, signal):
    assert concentration_risk(weight) == risk and compute_signal(weight) == signal


# ---------------- the agent (PostgreSQL) ----------------

async def make_user(session_factory, user_id: int) -> None:
    async with session_factory() as db:
        db.add(User(id=user_id, email=f"u{user_id}@x.com", hashed_password="x"))
        await db.commit()


async def hold(session_factory, user_id, symbol, qty, cost, asset=AssetType.STOCK, source=TransactionSource.MANUAL):
    async with session_factory() as db:
        db.add(PortfolioHolding(user_id=user_id, asset_type=asset, symbol=symbol, quantity=D(str(qty)),
                                avg_buy_price=D(str(cost)), source=source))
        await db.commit()


async def price(session_factory, symbol, value, when=None):
    async with session_factory() as db:
        db.add(MarketSnapshot(symbol=symbol, price=D(str(value)), source="yfinance", fetched_at=when or NOW))
        await db.commit()


async def txn(session_factory, user_id, symbol, action, qty, px, days_ago):
    async with session_factory() as db:
        db.add(Transaction(user_id=user_id, symbol=symbol, action=TransactionAction(action), quantity=D(str(qty)),
                           price=D(str(px)), transaction_date=NOW - timedelta(days=days_ago),
                           source=TransactionSource.TRADEBOOK_UPLOAD))
        await db.commit()


@pytest.fixture
async def portfolio(pg_sessionmaker):
    """User 1: INFY held manually AND via Zerodha, TCS, and an FD. User 2: a huge INFY position."""
    await make_user(pg_sessionmaker, 1)
    await make_user(pg_sessionmaker, 2)
    await hold(pg_sessionmaker, 1, "INFY.NS", 10, 1400)
    await hold(pg_sessionmaker, 1, "INFY.NS", 5, 1500, source=TransactionSource.KITE_SYNC)
    await hold(pg_sessionmaker, 1, "TCS.NS", 2, 3500)
    await hold(pg_sessionmaker, 1, "SBI FD 2027", 1, 100000, asset=AssetType.FD)
    await hold(pg_sessionmaker, 2, "INFY.NS", 1000, 1000)
    await price(pg_sessionmaker, "INFY.NS", 1500)
    await price(pg_sessionmaker, "TCS.NS", 3600)
    return pg_sessionmaker


async def test_position_pl_and_concentration(portfolio):
    r = await PortfolioAgent(portfolio).analyze(1, "infy")

    assert (r["agent"], r["user_id"], r["symbol"], r["status"], r["held"]) == ("portfolio_agent", 1, "INFY.NS", "ok", True)
    assert r["quantity"] == 15 and r["avg_cost"] == 1433.33          # manual + Zerodha rows combined
    assert r["current_price"] == 1500 and r["price_source"] == "snapshot"
    assert r["invested_value"] == 21500 and r["current_value"] == 22500
    assert r["unrealized_pl"] == 1000 and r["unrealized_pl_pct"] == 4.65
    assert r["total_portfolio_value"] == 129700                       # 22,500 + 7,200 + FD 100,000 at cost
    assert r["position_weight_pct"] == 17.35 and r["concentration_risk"] == "medium"
    assert r["holdings_count"] == 4 and r["valued_at_cost_assets"] == 1
    assert (r["signal"], r["confidence"]) == (-0.2, 1.0)
    assert r["summary"] == ("Holds 15 INFY.NS at an average ₹1,433.33; now ₹1,500.00: +₹1,000.00 (+4.7%) unrealised. "
                            "It is 17.4% of the portfolio (medium concentration risk).")
    assert r["rationale"] == r["summary"]


async def test_other_users_data_never_counts(portfolio):
    r = await PortfolioAgent(portfolio).analyze(2, "INFY.NS")
    assert r["quantity"] == 1000 and r["total_portfolio_value"] == 1_500_000
    assert r["position_weight_pct"] == 100.0 and r["concentration_risk"] == "high" and r["signal"] == -0.9


async def test_holding_period_and_tax_term_from_transactions(portfolio):
    await txn(portfolio, 1, "INFY.NS", "buy", 10, 1400, days_ago=400)
    await txn(portfolio, 1, "INFY.NS", "buy", 5, 1500, days_ago=30)
    await txn(portfolio, 1, "INFY.NS", "sell", 3, 1600, days_ago=10)
    r = await PortfolioAgent(portfolio).analyze(1, "INFY.NS")
    assert r["transactions_count"] == 3 and r["history_complete"]
    assert r["realized_pl"] == 600.0                                   # 3 x (1600 - 1400), FIFO
    assert r["holding_days"] == 400 and r["tax_term"] == "long_term"
    assert "held 400 days, so a sale now would be long-term for tax" in r["summary"]


async def test_short_term_holding(portfolio):
    await txn(portfolio, 1, "TCS.NS", "buy", 2, 3500, days_ago=90)
    r = await PortfolioAgent(portfolio).analyze(1, "TCS.NS")
    assert r["tax_term"] == "short_term" and r["concentration_risk"] == "low" and r["signal"] == 0.1


async def test_not_held_but_traded_before(portfolio):
    await txn(portfolio, 1, "WIPRO.NS", "buy", 10, 400, days_ago=200)
    await txn(portfolio, 1, "WIPRO.NS", "sell", 10, 450, days_ago=100)
    r = await PortfolioAgent(portfolio).analyze(1, "WIPRO.NS")
    assert r["status"] == "not_held" and not r["held"] and r["position_weight_pct"] == 0.0
    assert r["realized_pl"] == 500.0 and r["signal"] == 0.1
    assert "WIPRO.NS is not in the portfolio" in r["summary"] and "realised ₹500.00" in r["summary"]


async def test_uploaded_trades_not_in_holdings_are_flagged(portfolio):
    # Real case from the live run: a tradebook upload bought 7 HDFCBANK, but uploads don't
    # update holdings yet, so the agent must not just say "not in the portfolio".
    await txn(portfolio, 1, "HDFCBANK.NS", "buy", 7, 1450, days_ago=60)
    r = await PortfolioAgent(portfolio).analyze(1, "HDFCBANK.NS")
    assert r["status"] == "not_held" and r["open_quantity_from_transactions"] == 7
    assert "realised" not in r["summary"]                              # no sales -> no realised-P/L sentence
    assert r["notes"] == ["the trade history shows 7 shares still open, but they are not in the holdings "
                          "(uploaded trades don't update holdings yet)."]
    assert r["summary"].endswith(r["notes"][0])


async def test_holdings_and_trades_disagree(portfolio):
    await txn(portfolio, 1, "TCS.NS", "buy", 5, 3500, days_ago=30)     # holdings say 2
    r = await PortfolioAgent(portfolio).analyze(1, "TCS.NS")
    assert r["notes"] == ["holdings show 2 shares but the recorded trades leave 5; one of them may be out of date."]


async def test_incomplete_history_is_flagged(portfolio):
    await txn(portfolio, 1, "TCS.NS", "sell", 3, 3700, days_ago=5)     # no recorded buy
    r = await PortfolioAgent(portfolio).analyze(1, "TCS.NS")
    assert not r["history_complete"]
    assert any("realised P/L is partial" in n for n in r["notes"])


async def test_no_portfolio(pg_sessionmaker):
    await make_user(pg_sessionmaker, 9)
    r = await PortfolioAgent(pg_sessionmaker).analyze(9, "INFY.NS")
    assert r["status"] == "no_portfolio" and r["total_portfolio_value"] == 0 and r["concentration_risk"] == "none"


async def test_missing_price_falls_back_to_cost_and_lowers_confidence(portfolio):
    await hold(portfolio, 1, "NEWCO.NS", 100, 50)
    r = await PortfolioAgent(portfolio).analyze(1, "NEWCO.NS")
    assert r["held"] and r["current_price"] is None and r["unrealized_pl"] is None
    assert r["current_value"] == r["invested_value"] == 5000          # valued at cost
    assert r["valued_at_cost_assets"] == 2                            # FD + NEWCO
    assert r["confidence"] == 0.55                                    # 0.4 + 0.6 x 3/4 priced - 0.3 (no price for it)
    assert "no current price available" in r["summary"]


async def test_price_from_history_when_no_snapshot_and_stale_penalty(portfolio):
    await hold(portfolio, 1, "ITC.NS", 10, 400)
    async with portfolio() as db:
        db.add(PriceHistory(symbol="ITC.NS", date=date.today() - timedelta(days=10), close=D("420"), source="yfinance"))
        await db.commit()
    r = await PortfolioAgent(portfolio).analyze(1, "ITC.NS")
    assert r["current_price"] == 420 and r["price_source"] == "history"
    assert r["confidence"] == 0.9                                     # all priced, but this price is 10 days old


async def test_newest_price_wins(portfolio):
    async with portfolio() as db:
        db.add(PriceHistory(symbol="TCS.NS", date=date.today() + timedelta(days=1), close=D("3700"), source="yfinance"))
        await db.commit()
    r = await PortfolioAgent(portfolio).analyze(1, "TCS.NS")
    assert r["current_price"] == 3700 and r["price_source"] == "history"


async def test_every_call_is_logged(portfolio):
    await PortfolioAgent(portfolio).analyze(1, "INFY.NS")
    async with portfolio() as db:
        log = await db.scalar(select(AgentLog))
    assert log.agent_name == "portfolio_agent" and json.loads(log.input_summary) == {"user_id": 1, "symbol": "INFY.NS"}
    assert json.loads(log.output_summary)["concentration_risk"] == "medium"


# ---------------- permissions ----------------

def test_reads_are_guarded_and_agent_is_read_only():
    for method in (PortfolioAgent._user_holdings, PortfolioAgent._symbol_transactions,
                   PortfolioAgent._snapshot_prices, PortfolioAgent._last_closes):
        assert hasattr(method, "__wrapped__")
    for table in ("portfolio_holdings", "transactions", "market_snapshots", "price_history"):
        assert check_permission("portfolio_agent", "read", table)
        assert not check_permission("portfolio_agent", "write", table)
    for table in ("news_events", "user_profiles", "recommendations", "users", "broker_connections"):
        assert not check_permission("portfolio_agent", "read", table)
