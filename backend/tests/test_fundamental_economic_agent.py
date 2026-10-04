"""
Fundamental & Economic Agent and the fundamentals service. yfinance / Alpha Vantage are
faked; DB tests use PostgreSQL (TEST_DATABASE_URL).
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import yfinance
from sqlalchemy import func, select

from app.agents import fundamental_economic_agent as fea
from app.agents.fundamental_economic_agent import (
    FundamentalEconomicAgent, article_themes, compute_confidence, compute_signal, fundamental_points, valuation_label,
)
from app.core.config import settings
from app.models import AgentLog, CompanyFundamentals, NewsEvent
from app.models.enums import SecurityStatus
from app.security.permissions import check_permission
from app.services import fundamentals, market_data

NOW = datetime.now(UTC)


def fund(**kw) -> SimpleNamespace:
    base = dict(eps=50.0, pe_ratio=20.0, roe=0.12, debt_to_equity=0.5, revenue_growth=0.05, sector="Technology")
    return SimpleNamespace(**(base | kw))


# ---------------- macro themes ----------------

@pytest.mark.parametrize(
    "text, themes",
    [
        ("RBI keeps repo rate unchanged as inflation cools", ["interest_rates", "inflation"]),
        ("Interest rates likely to stay high: economists", ["interest_rates"]),          # plural
        ("Crude prices jump after OPEC cut; rupee weakens", ["oil_energy", "currency"]),
        ("US-Iran war sends crude soaring past $95", ["oil_energy", "geopolitics"]),
        ("Govt tightens GST policy for online gaming", ["fiscal_policy"]),
        ("Policyholders get relief; warranty claims rise; taxi fares up", []),           # no partial-word matches
        ("Infosys wins large deal", []),
    ],
)
def test_article_themes(text, themes):
    assert article_themes(text) == themes


# ---------------- fundamental rules ----------------

@pytest.mark.parametrize(
    "overrides, expected_points",
    [
        (dict(pe_ratio=12.0), [0.4]),
        (dict(pe_ratio=60.0, roe=0.2), [-0.5, 0.3]),
        (dict(pe_ratio=35.0, roe=0.05), [-0.2, -0.2]),
        (dict(eps=-3.0, pe_ratio=None), [-0.5]),                                          # loss-making
        (dict(debt_to_equity=3.0), [-0.3]),
        (dict(debt_to_equity=8.0, sector="Financial Services"), []),                      # banks: leverage not penalised
        (dict(revenue_growth=0.25), [0.2]),
        (dict(revenue_growth=-0.1), [-0.2]),
    ],
)
def test_fundamental_points(overrides, expected_points):
    assert [p for p, _ in fundamental_points(fund(**overrides))] == expected_points


def test_valuation_signal_confidence():
    assert [valuation_label(fund(pe_ratio=x)) for x in (10, 20, 40)] == ["cheap", "fair", "expensive"]
    assert valuation_label(fund(eps=-1)) == "loss_making" and valuation_label(None) == "unknown"
    assert compute_signal([(0.4, ""), (0.3, ""), (0.2, ""), (0.4, "")], 0.5) == 0.85    # fundamentals capped at 1
    assert compute_signal([], -0.4) == -0.12
    assert compute_confidence(True, 5, 4) == 1.0 and compute_confidence(False, 1, 0) == 0.2


# ---------------- fundamentals service ----------------

YF_INFO = {"shortName": "HDFC BANK LTD", "longName": "HDFC Bank Limited", "sector": "Financial Services",
           "industry": "Banks - Regional", "currency": "INR", "marketCap": 11119805595648, "trailingPE": 15.77,
           "forwardPE": 11.5, "priceToBook": 1.83, "trailingEps": 45.72, "returnOnEquity": 0.138,
           "debtToEquity": 46.3, "dividendYield": 1.8, "profitMargins": 0.268, "revenueGrowth": 0.166,
           "fiftyTwoWeekHigh": 1020.5, "fiftyTwoWeekLow": 681.9}


class FakeYFinance:
    """Stands in for yfinance.Ticker: every ticker returns `self.info`; calls are recorded."""

    def __init__(self):
        self.info: dict = dict(YF_INFO)
        self.calls: list[str] = []

    def __call__(self, symbol):
        self.calls.append(symbol)
        return SimpleNamespace(info=self.info)


@pytest.fixture
def fake_yf(monkeypatch) -> FakeYFinance:
    fake = FakeYFinance()
    monkeypatch.setattr(yfinance, "Ticker", fake)
    return fake


def test_yfinance_normalisation(fake_yf):
    data = fundamentals._yfinance_sync("HDFCBANK.NS")
    assert data["debt_to_equity"] == 0.463            # percent -> ratio
    assert data["dividend_yield_pct"] == 1.8 and data["roe"] == 0.138 and data["source"] == "yfinance"
    fake_yf.info = {"trailingPE": None}               # unknown symbol: near-empty info
    assert fundamentals._yfinance_sync("NOPE.NS") is None


def test_alpha_vantage_overview_parsing():
    payload = {"Symbol": "RELIANCE.BSE", "Name": "Reliance Industries", "Sector": "ENERGY", "Industry": "OIL & GAS",
               "PERatio": "21.1", "TrailingPE": "None", "EPS": "55.2", "DividendYield": "0.0051",
               "ReturnOnEquityTTM": "0.09", "MarketCapitalization": "15800000000000", "52WeekHigh": "1611.8",
               "52WeekLow": "1160.8", "PriceToBookRatio": "-"}
    data = fundamentals.parse_overview(payload)
    assert data["sector"] == "Energy" and data["pe_ratio"] == 21.1               # TrailingPE "None" -> PERatio
    assert data["dividend_yield_pct"] == 0.51                                    # fraction -> percent
    assert data["price_to_book"] is None and data["source"] == "alphavantage"
    assert fundamentals.parse_overview({}) is None                               # AV: symbol not covered


async def test_refresh_uses_cache_then_refreshes_when_stale(pg_sessionmaker, fake_yf):
    first = await fundamentals.refresh_if_stale("HDFCBANK.NS", pg_sessionmaker)
    again = await fundamentals.refresh_if_stale("HDFCBANK.NS", pg_sessionmaker)
    assert first.pe_ratio == 15.77 and again.id == first.id and fake_yf.calls == ["HDFCBANK.NS"]  # one fetch

    async with pg_sessionmaker() as db:
        row = await db.get(CompanyFundamentals, first.id)
        row.fetched_at = NOW - timedelta(days=8)
        await db.commit()
    fake_yf.info = dict(YF_INFO, trailingPE=18.0)
    refreshed = await fundamentals.refresh_if_stale("HDFCBANK.NS", pg_sessionmaker)
    assert refreshed.pe_ratio == 18.0 and len(fake_yf.calls) == 2
    async with pg_sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(CompanyFundamentals)) == 1  # upserted


async def test_failed_refresh_keeps_stale_row(pg_sessionmaker, fake_yf, monkeypatch):
    await fundamentals.refresh_if_stale("HDFCBANK.NS", pg_sessionmaker)
    async with pg_sessionmaker() as db:
        row = await db.scalar(select(CompanyFundamentals))
        row.fetched_at = NOW - timedelta(days=30)
        await db.commit()
    monkeypatch.setattr(settings, "ALPHAVANTAGE_API_KEY", "")
    fake_yf.info = {}
    kept = await fundamentals.refresh_if_stale("HDFCBANK.NS", pg_sessionmaker)
    assert kept is not None and kept.pe_ratio == 15.77


async def test_alpha_vantage_fallback(pg_sessionmaker, fake_yf, monkeypatch):
    fake_yf.info = {}
    monkeypatch.setattr(settings, "ALPHAVANTAGE_API_KEY", "test-av-key")
    monkeypatch.setattr(market_data, "_alphavantage_blocked_until", None)
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json={"Symbol": "ITC.BSE", "Name": "ITC", "Sector": "CONSUMER DEFENSIVE",
                                         "PERatio": "25"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        row = await fundamentals.refresh_if_stale("ITC.NS", pg_sessionmaker, client)
    assert row.source == "alphavantage" and row.sector == "Consumer Defensive" and row.pe_ratio == 25
    assert seen["function"] == "OVERVIEW" and seen["symbol"] == "ITC.BSE"


async def test_nothing_available(pg_sessionmaker, fake_yf, monkeypatch):
    fake_yf.info = {}
    monkeypatch.setattr(settings, "ALPHAVANTAGE_API_KEY", "")
    assert await fundamentals.refresh_if_stale("ZZZ.NS", pg_sessionmaker) is None


# ---------------- the agent (PostgreSQL) ----------------

async def seed_fundamentals(session_factory, symbol="HDFCBANK.NS", **kw):
    values = dict(name="HDFC Bank Limited", sector="Financial Services", industry="Banks - Regional",
                  pe_ratio=15.77, eps=45.72, roe=0.138, debt_to_equity=None, revenue_growth=0.166,
                  market_cap=Decimal("11119805595648"), source="yfinance", fetched_at=NOW) | kw
    async with session_factory() as db:
        db.add(CompanyFundamentals(symbol=symbol, **values))
        await db.commit()


async def seed_news(session_factory, title, sentiment=None, status=SecurityStatus.SAFE, hours_ago=5, n=[0]):
    n[0] += 1
    async with session_factory() as db:
        db.add(NewsEvent(source_api="google_rss", url=f"https://x.example/{n[0]}", title=title, source_domain="x.example",
                         sentiment=sentiment, seen_at=NOW - timedelta(hours=hours_ago), security_status=status))
        await db.commit()


@pytest.fixture
def no_network(monkeypatch):
    async def fail(*args, **kwargs):
        raise AssertionError("no fetch expected: the cache is fresh")

    monkeypatch.setattr(fundamentals, "fetch_yfinance_fundamentals", fail)


async def test_bank_with_rate_news(pg_sessionmaker, no_network):
    await seed_fundamentals(pg_sessionmaker)
    await seed_news(pg_sessionmaker, "RBI hikes repo rate by 25 bps to fight inflation", sentiment=-0.6)
    await seed_news(pg_sessionmaker, "Inflation eases to 4.1% in September", sentiment=0.4)
    await seed_news(pg_sessionmaker, "Interest rates to stay higher for longer", sentiment=-0.4, hours_ago=1)
    await seed_news(pg_sessionmaker, "Crude oil jumps 3% on OPEC cut", sentiment=-0.8)               # not a bank theme
    await seed_news(pg_sessionmaker, "RBI policy: banks told to tighten norms", sentiment=-0.5,
                    status=SecurityStatus.SUSPICIOUS)                                                     # not SAFE
    await seed_news(pg_sessionmaker, "RBI cuts rates", sentiment=0.9, hours_ago=24 * 10)               # too old
    await seed_news(pg_sessionmaker, "Infosys wins large deal", sentiment=0.9)                         # not macro

    r = await FundamentalEconomicAgent(pg_sessionmaker).analyze("hdfcbank")

    assert (r["agent"], r["symbol"], r["status"]) == ("fundamental_economic_agent", "HDFCBANK.NS", "ok")
    c = r["company"]
    assert (c["sector"], c["pe_ratio"], c["roe_pct"], c["market_cap_crore"]) == ("Financial Services", 15.77, 13.8, 1111981)
    assert r["valuation"] == "fair" and r["fundamental_reasons"] == ["revenue growing 17% a year"]

    m = r["macro"]
    assert m["article_count"] == 4                                   # SAFE, recent, macro only
    assert m["themes"] == {"interest_rates": 2, "inflation": 2, "oil_energy": 1}
    assert m["relevant_themes"] == ["interest_rates", "inflation", "growth"]
    assert m["relevant_article_count"] == 3                          # the crude article isn't relevant to banks
    assert m["relevant_avg_sentiment"] == -0.2                       # (-0.6 + 0.4 - 0.4) / 3
    assert [h["title"] for h in m["headlines"]][:1] == ["Interest rates to stay higher for longer"]  # relevant + newest
    assert m["headlines"][-1]["title"].startswith("Crude")          # irrelevant themes last

    assert r["signal"] == round(0.7 * 0.2 + 0.3 * -0.2, 2)           # 0.08
    assert r["confidence"] == 1.0
    assert r["summary"].startswith("HDFC Bank Limited (Financial Services, P/E 15.8): revenue growing 17% a year.")
    assert "news relevant to this sector is negative on average (-0.20)" in r["summary"]


async def test_too_few_scored_articles_means_no_macro_sentiment(pg_sessionmaker, no_network):
    await seed_fundamentals(pg_sessionmaker, "INFY.NS", sector="Technology", pe_ratio=13.3, roe=0.32)
    await seed_news(pg_sessionmaker, "Rupee falls to record low against dollar", sentiment=0.5)
    await seed_news(pg_sessionmaker, "Iran war escalates in the Gulf", sentiment=-0.9)   # not an IT theme
    r = await FundamentalEconomicAgent(pg_sessionmaker).analyze("INFY.NS")
    assert r["macro"]["relevant_themes"] == ["currency", "growth"]
    assert r["macro"]["relevant_article_count"] == 1 and r["macro"]["headlines"][0]["title"].startswith("Rupee")
    assert r["macro"]["relevant_avg_sentiment"] is None and r["valuation"] == "cheap"
    # cheap P/E +0.4, ROE 32% +0.3, revenue growth 16.6% +0.2 (from the seed defaults)
    assert r["signal"] == round(0.7 * (0.4 + 0.3 + 0.2), 2) and r["confidence"] == 0.6


async def test_no_data(pg_sessionmaker, monkeypatch):
    async def nothing(*args, **kwargs):
        return None

    monkeypatch.setattr(fundamentals, "refresh_if_stale", nothing)
    r = await FundamentalEconomicAgent(pg_sessionmaker).analyze("ZZZ.NS")
    assert r["status"] == "no_data" and (r["signal"], r["confidence"]) == (0.0, 0.0)


async def test_every_call_is_logged(pg_sessionmaker, no_network):
    await seed_fundamentals(pg_sessionmaker)
    await FundamentalEconomicAgent(pg_sessionmaker).analyze("HDFCBANK.NS")
    async with pg_sessionmaker() as db:
        log = await db.scalar(select(AgentLog))
    out = json.loads(log.output_summary)
    assert log.agent_name == "fundamental_economic_agent" and out["sector"] == "Financial Services"


def test_permissions():
    for method in (FundamentalEconomicAgent._fundamentals, FundamentalEconomicAgent._macro_news):
        assert hasattr(method, "__wrapped__")
    assert check_permission("fundamental_economic_agent", "read", "company_fundamentals")
    for table in ("company_fundamentals", "news_events", "recommendations"):
        assert not check_permission("fundamental_economic_agent", "write", table)
    for table in ("portfolio_holdings", "transactions", "user_profiles"):
        assert not check_permission("fundamental_economic_agent", "read", table)
    assert fea.HEADLINES_SHOWN == 8
