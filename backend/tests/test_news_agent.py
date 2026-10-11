"""
News Agent: the LLM is faked (canned JSON replies); retrieval is real or faked
depending on the test; DB writes and agent_logs use PostgreSQL (TEST_DATABASE_URL).
"""

import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.agents import news_agent as na
from app.agents.base import parse_json_object
from app.agents.news_agent import NewsAgent, compute_confidence, compute_signal
from app.models import AgentLog, NewsEvent
from app.security.permissions import check_permission
from app.services import llm, rag_retrieval
from app.services import vector_store as vs
from tests.test_vector_store import add_news, chroma, fake_model  # noqa: F401

RECENT = datetime.now(UTC) - timedelta(hours=3)


def article(news_id: int, trust: str = "trusted", title: str = "Infosys wins deal") -> dict:
    return {"news_event_id": news_id, "title": title, "description": "Big multi-year deal", "url": f"https://x/{news_id}",
            "source_api": "google_rss", "source_name": "ET", "source_domain": "economictimes.indiatimes.com",
            "source_trust": trust, "seen_at": RECENT.isoformat(), "sentiment": None, "affected_symbols": ["INFY.NS"],
            "affected_sector": None, "similarity": 0.8, "symbol_match": True}


class FakeLLM:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    async def __call__(self, system, user, *, max_tokens=1024, json_mode=False):
        self.calls.append({"system": system, "user": user, "json_mode": json_mode})
        if self.error:
            raise self.error
        return self.reply


def verdict_json(**overrides) -> str:
    return json.dumps({"sentiment": "positive", "severity": "high",
                       "summary": "Infosys won a large multi-year deal, which should lift revenue.",
                       "cited_article_ids": [1, 2], "article_sentiments": [{"id": 1, "score": 0.8}]} | overrides)


@pytest.fixture
def fake_retrieval(monkeypatch):
    calls = []

    async def retrieve(query, symbol=None, top_k=5, **kwargs):
        calls.append({"query": query, "symbol": symbol, "top_k": top_k, **kwargs})
        return calls_result[0]

    calls_result = [[article(1), article(2, "untrusted")]]
    monkeypatch.setattr(rag_retrieval, "retrieve_relevant_news", retrieve)
    return calls, calls_result


async def agent_logs(session_factory) -> list[AgentLog]:
    async with session_factory() as db:
        return list((await db.scalars(select(AgentLog))).all())


# ---------------- pure helpers ----------------

@pytest.mark.parametrize(
    "sentiment, severity, expected",
    [("positive", "high", 1.0), ("positive", "low", 0.33), ("negative", "medium", -0.66), ("neutral", "high", 0.0)],
)
def test_compute_signal(sentiment, severity, expected):
    assert compute_signal(sentiment, severity) == expected


def test_compute_confidence():
    assert compute_confidence([article(1)], [1]) == 0.47  # 0.3 + 0.7 * 0.25 = 0.475 (float rounds down)
    assert compute_confidence([article(i) for i in range(4)], [0, 1, 2, 3]) == 1.0
    assert compute_confidence([article(i, "untrusted") for i in range(4)], [0, 1, 2, 3]) == 0.72
    # Nothing cited = the articles were not about the stock -> no evidence (audit: was 0.79 before).
    assert compute_confidence([article(i) for i in range(8)], []) == 0.0
    assert compute_confidence([article(1)], [999]) == 0.0


async def test_irrelevant_articles_give_no_relevant_news(pg_sessionmaker, fake_retrieval, monkeypatch):
    monkeypatch.setattr(llm, "complete", FakeLLM(verdict_json(
        sentiment="neutral", severity="low", summary="None of the articles are about this stock.",
        cited_article_ids=[], article_sentiments=[])))
    result = await NewsAgent(pg_sessionmaker).analyze("ZZNODATA.NS")
    assert (result["status"], result["signal"], result["confidence"]) == ("no_relevant_news", 0.0, 0.0)
    assert result["summary"] == "None of the articles are about this stock."

    from app.agents.confidence_module import compute_agreement
    agreement = compute_agreement({"news_agent": result})
    assert agreement["excluded"]["news_agent"] == "status no_relevant_news"   # not counted as a neutral vote


@pytest.mark.parametrize(
    "reply",
    ['{"a": 1}', '```json\n{"a": 1}\n```', 'Sure! Here it is: {"a": 1} Hope this helps.'],
)
def test_parse_json_object_tolerates_wrappers(reply):
    assert parse_json_object(reply) == {"a": 1}


@pytest.mark.parametrize("reply", ["no json here", "[1, 2]", '{"a": '])
def test_parse_json_object_rejects_garbage(reply):
    with pytest.raises(ValueError):
        parse_json_object(reply)


# ---------------- analyze(): happy path ----------------

async def test_analyze_returns_structured_verdict_and_logs(pg_sessionmaker, fake_retrieval, monkeypatch):
    calls, _ = fake_retrieval
    fake = FakeLLM(verdict_json())
    monkeypatch.setattr(llm, "complete", fake)

    result = await NewsAgent(pg_sessionmaker).analyze("infy", company_name="Infosys")

    assert result["agent"] == "news_agent" and result["symbol"] == "INFY.NS" and result["status"] == "ok"
    assert (result["sentiment"], result["severity"]) == ("positive", "high")
    assert result["summary"] == result["rationale"] == "Infosys won a large multi-year deal, which should lift revenue."
    assert result["signal"] == 1.0 and 0 < result["confidence"] <= 1
    assert result["cited_article_ids"] == [1, 2]
    assert [a["news_event_id"] for a in result["articles"]] == [1, 2]

    # retrieval: symbol-filtered, recent, company name in the query
    assert calls[0]["symbol"] == "INFY.NS" and calls[0]["max_age_days"] == na.MAX_AGE_DAYS
    assert calls[0]["query"].startswith("Infosys stock news")

    # prompt: JSON mode, articles wrapped in nonce markers, untrusted-data instructions
    call = fake.calls[0]
    assert call["json_mode"] is True
    assert "untrusted data" in call["system"] and "Never follow" in call["system"]
    nonce = re.search(r"<<<ARTICLES ([0-9a-f]{16})>>>", call["user"]).group(1)
    assert f"<<<END ARTICLES {nonce}>>>" in call["user"]
    assert "[id=2] (" in call["user"] and "untrusted source) Infosys wins deal - Big multi-year deal" in call["user"]

    logs = await agent_logs(pg_sessionmaker)
    assert len(logs) == 1 and logs[0].agent_name == "news_agent" and logs[0].action == "analyze"
    assert json.loads(logs[0].input_summary) == {"symbol": "INFY.NS", "articles": 2}
    assert json.loads(logs[0].output_summary)["sentiment"] == "positive"


async def test_hallucinated_article_ids_are_dropped(pg_sessionmaker, fake_retrieval, monkeypatch):
    monkeypatch.setattr(llm, "complete", FakeLLM(verdict_json(
        cited_article_ids=[2, 999, 2], article_sentiments=[{"id": 999, "score": 1.0}])))
    result = await NewsAgent(pg_sessionmaker).analyze("INFY.NS")
    assert result["cited_article_ids"] == [2] and result["sentiments_saved"] == 0


async def test_case_insensitive_labels(pg_sessionmaker, fake_retrieval, monkeypatch):
    monkeypatch.setattr(llm, "complete", FakeLLM(verdict_json(sentiment="NEGATIVE", severity=" Medium ")))
    result = await NewsAgent(pg_sessionmaker).analyze("INFY.NS")
    assert (result["sentiment"], result["severity"], result["signal"]) == ("negative", "medium", -0.66)


# ---------------- degraded paths: always neutral, confidence 0, still logged ----------------

async def test_no_news_skips_the_llm(pg_sessionmaker, fake_retrieval, monkeypatch):
    _, result_holder = fake_retrieval
    result_holder[0] = []
    fake = FakeLLM(verdict_json())
    monkeypatch.setattr(llm, "complete", fake)
    result = await NewsAgent(pg_sessionmaker).analyze("TCS.NS")
    assert result["status"] == "no_news" and result["signal"] == 0 and result["confidence"] == 0
    assert fake.calls == []
    assert len(await agent_logs(pg_sessionmaker)) == 1


@pytest.mark.parametrize(
    "fake, status",
    [
        (FakeLLM(error=llm.LLMNotConfigured("GEMINI_API_KEY is not set")), "llm_unavailable"),
        (FakeLLM("I think the news is good!"), "invalid_llm_output"),
        (FakeLLM(verdict_json(sentiment="bullish")), "invalid_llm_output"),       # not an allowed label
        (FakeLLM(verdict_json(summary="")), "invalid_llm_output"),
        (FakeLLM(verdict_json(article_sentiments=[{"id": 1, "score": 5}])), "invalid_llm_output"),  # out of range
    ],
)
async def test_llm_problems_give_neutral_zero_confidence(pg_sessionmaker, fake_retrieval, monkeypatch, fake, status):
    monkeypatch.setattr(llm, "complete", fake)
    result = await NewsAgent(pg_sessionmaker).analyze("INFY.NS")
    assert result["status"] == status
    assert (result["sentiment"], result["signal"], result["confidence"]) == ("neutral", 0.0, 0.0)
    assert len(result["articles"]) == 2  # the evidence is still reported
    assert json.loads((await agent_logs(pg_sessionmaker))[0].output_summary)["status"] == status


async def test_unexpected_errors_are_logged_then_raised(pg_sessionmaker, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("chroma folder missing")

    monkeypatch.setattr(rag_retrieval, "retrieve_relevant_news", broken)
    with pytest.raises(RuntimeError):
        await NewsAgent(pg_sessionmaker).analyze("INFY.NS")
    output = json.loads((await agent_logs(pg_sessionmaker))[0].output_summary)
    assert output["status"] == "error" and "chroma folder missing" in output["summary"]


# ---------------- permissions ----------------

def test_data_access_methods_are_permission_guarded():
    assert check_permission("news_agent", "read", "news_events") and check_permission("news_agent", "write", "news_events")
    for method in (NewsAgent._fetch_news, NewsAgent._save_article_sentiments):
        assert hasattr(method, "__wrapped__")  # wrapped by @enforce_permission


def test_news_agent_cannot_touch_anything_else():
    for table in ("portfolio_holdings", "transactions", "recommendations", "user_profiles", "news_quarantine"):
        assert not check_permission("news_agent", "read", table)
        assert not check_permission("news_agent", "write", table)


# ---------------- end to end with real retrieval + DB write-back (PostgreSQL + Chroma) ----------------

async def test_end_to_end_writes_sentiment_only_where_empty(pg_sessionmaker, chroma, fake_model, monkeypatch):
    empty = await add_news(pg_sessionmaker, title="Infosys wins large deal", description="Infosys multi year deal",
                           affected_symbols=["INFY.NS"], seen_at=RECENT, source_domain="reuters.com")
    scored = await add_news(pg_sessionmaker, title="Infosys deal analysis", description="Infosys deal analysts react",
                            affected_symbols=["INFY.NS"], seen_at=RECENT, source_domain="reuters.com", sentiment=-0.2)
    await vs.embed_many([empty, scored], pg_sessionmaker)

    monkeypatch.setattr(llm, "complete", FakeLLM(verdict_json(
        cited_article_ids=[empty, scored],
        article_sentiments=[{"id": empty, "score": 0.75}, {"id": scored, "score": 0.9}])))
    result = await NewsAgent(pg_sessionmaker).analyze("INFY.NS", company_name="Infosys")

    assert result["status"] == "ok" and {a["news_event_id"] for a in result["articles"]} == {empty, scored}
    assert result["sentiments_saved"] == 1
    async with pg_sessionmaker() as db:
        assert (await db.get(NewsEvent, empty)).sentiment == 0.75
        assert (await db.get(NewsEvent, scored)).sentiment == -0.2  # existing (e.g. Marketaux) score kept
