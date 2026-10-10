"""
Ordered API-key fallback (app/services/key_pool.py) and its use by Alpha Vantage and
Marketaux. HTTP is faked with httpx.MockTransport; no real key or network is used.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import settings
from app.services import key_pool
from app.services import market_data as md
from app.services import news_ingestion as ni
from tests.test_market_data import RATE_LIMIT_JSON, RSI_JSON
from tests.test_news_ingestion import MARKETAUX_JSON

F = key_pool.Failure


# ---------------- settings.api_keys ----------------

def test_api_keys_merges_single_and_list_in_order(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "k1")
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", " k2 , k1,,k3 ")
    assert settings.api_keys("gemini") == ["k1", "k2", "k3"]
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "")
    assert settings.api_keys("gemini") == []


# ---------------- classification ----------------

@pytest.mark.parametrize(
    "status, message, kind",
    [
        (400, "API key not valid. Please pass a valid API key. API_KEY_INVALID", F.AUTH),   # Gemini bad key
        (401, "Incorrect API key provided", F.AUTH),                                      # OpenAI bad key
        (403, "PERMISSION_DENIED", F.AUTH),
        (429, "RESOURCE_EXHAUSTED. You exceeded your current quota, please check your plan and billing details. "
              "quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier", F.RATE_LIMIT),
        (429, "RESOURCE_EXHAUSTED quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier", F.QUOTA),
        (429, "You have no credits remaining. insufficient_quota", F.QUOTA),               # OpenAI no credits
        (402, "usage_limit_reached", F.QUOTA),                                             # Marketaux daily cap
        (429, "rate_limit_reached", F.RATE_LIMIT),                                         # Marketaux per minute
        (None, "Our standard API rate limit is 25 requests per day.", F.QUOTA),            # Alpha Vantage daily
        (None, "Please consider spreading out your free API requests (1 request per second).", F.OTHER),
        (503, "UNAVAILABLE", F.OTHER),
        (404, "model not found", F.OTHER),
        (None, "ReadTimeout", F.OTHER),
    ],
)
def test_classify(status, message, kind):
    assert key_pool.classify(status, message) is kind


def test_rest_times(monkeypatch):
    monkeypatch.setattr(settings, "MARKETAUX_API_KEYS", "a-111111,b-222222,c-333333")
    start = datetime.now(UTC)
    key_pool.report_failure("marketaux", "a-111111", F.RATE_LIMIT)
    key_pool.report_failure("marketaux", "b-222222", F.AUTH)
    key_pool.report_failure("marketaux", "c-333333", F.OTHER)                  # no rest
    assert key_pool.usable_keys("marketaux") == ["c-333333"]
    rest = key_pool._state[("marketaux", "a-111111")].resting_until - start
    assert timedelta(seconds=59) < rest <= timedelta(seconds=61)
    assert key_pool._state[("marketaux", "b-222222")].resting_until - start >= timedelta(hours=6) - timedelta(seconds=1)

    key_pool.report_failure("marketaux", "a-111111", F.RATE_LIMIT)            # repeat -> doubles
    assert key_pool._state[("marketaux", "a-111111")].strikes == 2
    assert key_pool._state[("marketaux", "a-111111")].resting_until - start > timedelta(seconds=119)
    key_pool.report_success("marketaux", "a-111111")
    assert key_pool.usable_keys("marketaux") == ["a-111111", "c-333333"]
    assert key_pool.next_free_at("marketaux") is not None


def test_rate_limit_rest_is_capped():
    for _ in range(20):
        key_pool.report_failure("x", "k-12345678", F.RATE_LIMIT)
    rest = key_pool._state[("x", "k-12345678")].resting_until - datetime.now(UTC)
    assert rest <= key_pool.RATE_LIMIT_MAX_REST


def test_mask():
    assert key_pool.mask("sk-proj-abcdefgh1234") == "...1234" and key_pool.mask("short") == "..."


# ---------------- Alpha Vantage rotation ----------------

@pytest.fixture
def two_av_keys(monkeypatch):
    monkeypatch.setattr(settings, "ALPHAVANTAGE_API_KEY", "")
    monkeypatch.setattr(settings, "ALPHAVANTAGE_API_KEYS", "av-key-one,av-key-two")
    monkeypatch.setattr(md, "_alphavantage_blocked_until", None)


def av_handler(limited_keys: set[str], seen: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.params["apikey"]
        seen.append(key)
        return httpx.Response(200, json=RATE_LIMIT_JSON if key in limited_keys else RSI_JSON)
    return handler


async def test_alphavantage_uses_second_key_when_first_is_limited(two_av_keys):
    seen: list[str] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(av_handler({"av-key-one"}, seen))) as client:
        payload = await md.alphavantage_query(client, {"function": "RSI"}, "TEST")
        assert payload == RSI_JSON and seen == ["av-key-one", "av-key-two"]
        # Key one now rests: the next request goes straight to key two.
        await md.alphavantage_query(client, {"function": "RSI"}, "TEST")
    assert seen == ["av-key-one", "av-key-two", "av-key-two"]
    assert md.alphavantage_available("test")


async def test_alphavantage_all_keys_limited_raises(two_av_keys):
    seen: list[str] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(av_handler({"av-key-one", "av-key-two"}, seen))) as c:
        with pytest.raises(md.AlphaVantageRateLimitError):
            await md.alphavantage_query(c, {"function": "RSI"}, "TEST")
    assert seen == ["av-key-one", "av-key-two"]
    assert not md.alphavantage_available("test")                    # both resting -> no more calls


# ---------------- Marketaux rotation ----------------

@pytest.fixture
def two_marketaux_keys(monkeypatch):
    monkeypatch.setattr(settings, "MARKETAUX_API_KEY", "")
    monkeypatch.setattr(settings, "MARKETAUX_API_KEYS", "mx-key-one,mx-key-two")
    monkeypatch.setattr(ni, "_marketaux_budget", ni._DailyBudget())


@pytest.mark.parametrize("status", [401, 402, 429])
async def test_marketaux_switches_key_on_key_errors(two_marketaux_keys, status):
    seen: list[str] = []

    def handler(request):
        key = request.url.params["api_token"]
        seen.append(key)
        if key == "mx-key-one":
            return httpx.Response(status, json={"error": {"code": "x", "message": "x"}})
        return httpx.Response(200, json=MARKETAUX_JSON)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        articles = await ni.fetch_marketaux("RELIANCE.NS", client)
    assert seen == ["mx-key-one", "mx-key-two"] and articles
    assert key_pool.usable_keys("marketaux") == ["mx-key-two"]


async def test_marketaux_server_error_does_not_burn_other_keys(two_marketaux_keys):
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.params["api_token"])
        return httpx.Response(500, text="oops")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await ni.fetch_marketaux("RELIANCE.NS", client) == []
    assert seen == ["mx-key-one"] and key_pool.usable_keys("marketaux") == ["mx-key-one", "mx-key-two"]


def test_marketaux_budget_scales_with_keys(two_marketaux_keys, monkeypatch):
    monkeypatch.setattr(ni, "MARKETAUX_DAILY_BUDGET", 2)
    budget = ni._DailyBudget()
    assert [budget.try_spend() for _ in range(5)] == [True, True, True, True, False]
