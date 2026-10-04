"""
News ingestion tests. All HTTP is faked with httpx.MockTransport, so no
network access or API keys are needed.

Run from backend/:  pytest tests/test_news_ingestion.py -v
"""

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models import NewsEvent
from app.models.enums import SecurityStatus
from app.services import news_ingestion as ni

# ---------------- canned API responses ----------------

GDELT_JSON = {
    "articles": [
        {
            "url": "https://example.com/infosys-q2",
            "title": "Infosys  beats   estimates ",
            "seendate": "20261001T194500Z",
            "domain": "example.com",
            "sourcecountry": "India",
        },
        {"url": "", "title": "missing url is skipped"},
    ]
}

GOOGLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Google News</title>
<item>
  <title>Infosys raises guidance - The Economic Times</title>
  <link>https://news.google.com/rss/articles/abc123</link>
  <pubDate>Thu, 01 Oct 2026 17:09:00 GMT</pubDate>
  <source url="https://economictimes.indiatimes.com">The Economic Times</source>
</item>
</channel></rss>"""

MARKETAUX_JSON = {
    "data": [
        {
            "title": "Infosys shares rally",
            "url": "https://www.livemint.com/infosys-rally",
            "description": "Shares rose 3%.",
            "published_at": "2026-10-01T12:00:00.000000Z",
            "source": "livemint.com",
            "entities": [
                {"symbol": "INFY.NS", "industry": "Technology", "sentiment_score": 0.6},
                {"symbol": "INFY.NS", "industry": "Technology", "sentiment_score": 0.4},
                {"symbol": "TCS.NS", "industry": "Technology", "sentiment_score": -0.9},
            ],
        }
    ]
}


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def happy_handler(request: httpx.Request) -> httpx.Response:
    if "gdeltproject" in request.url.host:
        return httpx.Response(200, json=GDELT_JSON)
    if "news.google.com" in request.url.host:
        return httpx.Response(200, text=GOOGLE_RSS)
    if "marketaux" in request.url.host:
        return httpx.Response(200, json=MARKETAUX_JSON)
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def fast_and_keyed(monkeypatch):
    monkeypatch.setattr(ni, "GDELT_MIN_INTERVAL", 0)           # no real waits in tests
    monkeypatch.setattr(ni, "GDELT_RETRY_BACKOFF", 0)
    monkeypatch.setattr(settings, "MARKETAUX_API_KEY", "test-key")
    # Fresh Marketaux rationing state per test, with no per-ticker wait.
    monkeypatch.setattr(ni, "_marketaux_budget", ni._DailyBudget())
    monkeypatch.setattr(ni, "_marketaux_last_fetch", {})
    monkeypatch.setattr(ni, "MARKETAUX_SYMBOL_REFRESH", timedelta(0))


# ---------------- GDELT batching ----------------

@pytest.mark.parametrize(
    "keywords, expected",
    [
        (["war"], "war"),                                            # single term: no parentheses
        (["war", "crude oil", "RELIANCE"], '(war OR "crude oil" OR RELIANCE)'),
        (["war", "war"], "war"),                                     # de-duplicated
        (["LT", "war", "M&M"], "war"),                               # too short / '&' dropped
        (["LT"], None),
    ],
)
def test_build_gdelt_query(keywords, expected):
    assert ni.build_gdelt_query(keywords) == expected


async def test_ingest_batches_gdelt_keywords(pg_sessionmaker, monkeypatch):
    monkeypatch.setattr(ni, "GDELT_BATCH_SIZE", 2)
    gdelt_queries = []

    def handler(request):
        if "gdeltproject" in request.url.host:
            gdelt_queries.append(request.url.params["query"])
            return httpx.Response(200, json={})
        return httpx.Response(200, text=GOOGLE_RSS) if "google" in request.url.host else httpx.Response(404)

    async with mock_client(handler) as client:
        await ni.ingest_news_for_watchlist(["war", "recession", "crude oil"], pg_sessionmaker, client)
    assert gdelt_queries == ["(war OR recession) sourcelang:english", '"crude oil" sourcelang:english']


# ---------------- Marketaux rationing ----------------

async def test_marketaux_daily_budget(monkeypatch):
    monkeypatch.setattr(ni, "MARKETAUX_DAILY_BUDGET", 2)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=MARKETAUX_JSON)

    async with mock_client(handler) as client:
        for _ in range(3):
            await ni.fetch_marketaux("INFY.NS", client=client)
    assert len(calls) == 2  # third request refused locally


def test_marketaux_budget_resets_next_day():
    budget = ni._DailyBudget()
    budget.used, budget.day = ni.MARKETAUX_DAILY_BUDGET, date(2000, 1, 1)  # exhausted, but on an old day
    assert budget.try_spend() and budget.used == 1


def test_marketaux_symbol_refresh_interval(monkeypatch):
    monkeypatch.setattr(ni, "MARKETAUX_SYMBOL_REFRESH", timedelta(hours=4))
    assert ni._marketaux_due("INFY.NS") is True
    assert ni._marketaux_due("INFY.NS") is False   # asked again too soon
    assert ni._marketaux_due("TCS.NS") is True     # other tickers unaffected


# ---------------- individual fetchers: happy path ----------------

async def test_fetch_gdelt_parses_articles():
    async with mock_client(happy_handler) as client:
        articles = await ni.fetch_gdelt("Infosys", client=client)
    assert articles == [
        {
            "title": "Infosys beats estimates",  # whitespace cleaned
            "url": "https://example.com/infosys-q2",
            "seendate": datetime(2026, 10, 1, 19, 45, tzinfo=UTC),
            "domain": "example.com",
            "sourcecountry": "India",
        }
    ]


async def test_fetch_gdelt_quotes_multi_word_keywords():
    seen = {}

    def handler(request):
        seen["query"] = request.url.params["query"]
        return httpx.Response(200, json={})

    async with mock_client(handler) as client:
        assert await ni.fetch_gdelt("Reliance Industries", client=client) == []
    assert seen["query"] == '"Reliance Industries" sourcelang:english'


async def test_fetch_google_news_rss_parses_feed():
    async with mock_client(happy_handler) as client:
        articles = await ni.fetch_google_news_rss("Infosys", client=client)
    assert len(articles) == 1
    a = articles[0]
    assert a["title"] == "Infosys raises guidance"  # " - Publisher" suffix removed
    assert a["source"] == "The Economic Times"
    assert a["source_url"] == "https://economictimes.indiatimes.com"
    assert a["published"] == datetime(2026, 10, 1, 17, 9, tzinfo=UTC)


async def test_fetch_marketaux_averages_sentiment_for_requested_symbol():
    async with mock_client(happy_handler) as client:
        articles = await ni.fetch_marketaux("INFY.NS", client=client)
    a = articles[0]
    assert a["sentiment_score"] == 0.5  # mean of INFY's 0.6 and 0.4; TCS's -0.9 ignored
    assert a["symbols"] == ["INFY.NS", "TCS.NS"]
    assert a["industry"] == "Technology"


async def test_fetch_marketaux_without_key_makes_no_request(monkeypatch):
    monkeypatch.setattr(settings, "MARKETAUX_API_KEY", "")

    def handler(request):
        raise AssertionError("no HTTP call expected")

    async with mock_client(handler) as client:
        assert await ni.fetch_marketaux("INFY.NS", client=client) == []


# ---------------- GDELT rate limiting ----------------

async def test_gdelt_retries_after_429():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, text="Please limit requests to one every 5 seconds")
        return httpx.Response(200, json=GDELT_JSON)

    async with mock_client(handler) as client:
        articles = await ni.fetch_gdelt("Infosys", client=client)
    assert len(calls) == 2 and len(articles) == 1


async def test_gdelt_gives_up_after_max_retries(caplog):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, text="Please limit requests")

    async with mock_client(handler) as client:
        assert await ni.fetch_gdelt("Infosys", client=client) == []
    assert len(calls) == ni.GDELT_RETRIES_ON_429 + 1
    assert "HTTP 429" in caplog.text


# ---------------- failures are logged, never raised ----------------

def timeout_handler(request):
    raise httpx.ReadTimeout("timed out", request=request)


def error_500_handler(request):
    return httpx.Response(500, text="Internal Server Error")


def garbage_handler(request):
    return httpx.Response(200, text="Please limit requests to one every 5 seconds")


@pytest.mark.parametrize("handler", [timeout_handler, error_500_handler, garbage_handler])
@pytest.mark.parametrize(
    "fetch",
    [ni.fetch_gdelt, ni.fetch_google_news_rss, ni.fetch_marketaux],
    ids=["gdelt", "google_rss", "marketaux"],
)
async def test_fetchers_return_empty_list_on_failure(fetch, handler, caplog):
    async with mock_client(handler) as client:
        assert await fetch("INFY.NS", client=client) == []
    assert any(r.levelname == "ERROR" for r in caplog.records)


async def test_api_key_never_logged(caplog):
    def handler(request):
        return httpx.Response(401, json={"error": {"code": "invalid_api_token"}})

    async with mock_client(handler) as client:
        await ni.fetch_marketaux("INFY.NS", client=client)
    assert "test-key" not in caplog.text


# ---------------- watchlist parsing ----------------

@pytest.mark.parametrize(
    "item, expected",
    [
        ("RELIANCE.NS", ("RELIANCE", "RELIANCE.NS")),
        ("M&M.BO", ("M&M", "M&M.BO")),
        ("RBI repo rate", ("RBI repo rate", None)),
        ("reliance.ns", ("reliance.ns", None)),  # tickers must be upper-case
    ],
)
def test_split_watchlist_item(item, expected):
    assert ni._split_watchlist_item(item) == expected


# ---------------- end-to-end insert (needs real PostgreSQL) ----------------

async def test_ingest_inserts_rows_and_skips_duplicates(pg_sessionmaker):
    async with mock_client(happy_handler) as client:
        first = await ni.ingest_news_for_watchlist(["INFY.NS"], pg_sessionmaker, client)
        second = await ni.ingest_news_for_watchlist(["INFY.NS"], pg_sessionmaker, client)

    assert first.fetched == {"gdelt": 1, "google_rss": 1, "marketaux": 1}
    assert first.inserted == 3
    assert second.inserted == 0 and second.duplicates == 3  # URL unique constraint

    async with pg_sessionmaker() as db:
        rows = {r.source_api: r for r in (await db.scalars(select(NewsEvent))).all()}
        assert await db.scalar(select(func.count()).select_from(NewsEvent)) == 3

    assert all(r.security_status == SecurityStatus.SAFE for r in rows.values())  # scanned: clean news
    assert first.security == {"safe": 3, "suspicious": 0, "blocked": 0}
    assert second.security == {"safe": 0, "suspicious": 0, "blocked": 0}  # stored URLs not re-scanned
    mx = rows["marketaux"]
    assert mx.sentiment == 0.5 and mx.affected_symbols == ["INFY.NS", "TCS.NS"]
    assert mx.source_domain == "livemint.com"
    assert rows["google_rss"].source_domain == "economictimes.indiatimes.com"
    assert rows["google_rss"].affected_symbols == ["INFY.NS"]  # tagged with the ticker that found it
    assert rows["gdelt"].affected_symbols == []                  # batched query: can't tell which keyword matched
    assert rows["gdelt"].seen_at == datetime(2026, 10, 1, 19, 45, tzinfo=UTC)


async def test_ingest_survives_one_source_failing(pg_sessionmaker):
    def handler(request):
        if "gdeltproject" in request.url.host:
            raise httpx.ConnectError("down", request=request)
        return happy_handler(request)

    async with mock_client(handler) as client:
        report = await ni.ingest_news_for_watchlist(["INFY.NS", "RBI repo rate"], pg_sessionmaker, client)

    assert report.fetched["gdelt"] == 0
    assert report.fetched["marketaux"] == 1  # only the ticker hits Marketaux
    assert report.inserted == 2              # Google's same URL for both keywords counted once
