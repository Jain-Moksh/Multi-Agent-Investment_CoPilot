"""
retrieve_relevant_news(): real ChromaDB (temp folder) + fake bag-of-words
embedding model + PostgreSQL rows (TEST_DATABASE_URL).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, update

from app.models import NewsEvent
from app.models.enums import SecurityStatus
from app.services import vector_store as vs
from app.services.rag_retrieval import build_where, retrieve_relevant_news
from tests.test_vector_store import add_news, chroma, fake_model  # noqa: F401  (fixtures + helper)

RECENT = datetime.now(UTC) - timedelta(hours=2)


async def seed(session_factory) -> dict[str, int]:
    """A small, varied news set, embedded through the real pipeline (trusted domain)."""
    articles = {
        "infy_deal": dict(title="Infosys wins large deal", description="Infosys signs a multi year IT services deal",
                          affected_symbols=["INFY.NS"]),
        "it_sector": dict(title="IT stocks rally", description="TCS and Infosys lead IT sector gains on deal wins",
                          affected_symbols=["TCS.NS", "INFY.NS"]),   # INFY is the SECOND symbol here
        "rbi": dict(title="RBI holds repo rate", description="The RBI kept the repo rate at 6.5 percent",
                    affected_symbols=[]),
        "crude": dict(title="Crude oil jumps", description="Brent crude oil rises on supply cuts",
                      affected_symbols=["ONGC.NS"]),
        "old_infy": dict(title="Infosys deal news from last year", description="Infosys deal signed",
                         affected_symbols=["INFY.NS"], seen_at=datetime.now(UTC) - timedelta(days=400)),
    }
    ids = {}
    for key, values in articles.items():
        ids[key] = await add_news(session_factory, **({"seen_at": RECENT, "source_domain": "reuters.com"} | values))
    report = await vs.embed_many(list(ids.values()), session_factory)
    assert sorted(report.embedded) == sorted(ids.values())
    return ids


async def test_returns_most_relevant_rows_first(pg_sessionmaker, chroma, fake_model):
    ids = await seed(pg_sessionmaker)
    results = await retrieve_relevant_news("what did the RBI do with the repo rate", top_k=2,
                                           session_factory=pg_sessionmaker)
    assert [r["news_event_id"] for r in results][0] == ids["rbi"]
    assert len(results) == 2
    top = results[0]
    assert top["title"] == "RBI holds repo rate" and top["source_trust"] == "trusted"
    assert top["url"].startswith("https://example.com/") and top["seen_at"].startswith(RECENT.date().isoformat())
    assert 0 < results[1]["similarity"] < top["similarity"] <= 1


async def test_symbol_filter_includes_articles_where_symbol_is_not_first(pg_sessionmaker, chroma, fake_model):
    ids = await seed(pg_sessionmaker)
    results = await retrieve_relevant_news("deal wins", symbol="infy", top_k=10, symbol_fallback=False,
                                           session_factory=pg_sessionmaker)
    assert {r["news_event_id"] for r in results} == {ids["infy_deal"], ids["it_sector"], ids["old_infy"]}
    assert all("INFY.NS" in r["affected_symbols"] and r["symbol_match"] for r in results)


async def test_symbol_fallback_fills_with_untagged_articles_after_tagged_ones(pg_sessionmaker, chroma, fake_model):
    ids = await seed(pg_sessionmaker)
    results = await retrieve_relevant_news("deal wins", symbol="INFY.NS", top_k=5, session_factory=pg_sessionmaker)
    assert len(results) == 5
    flags = [r["symbol_match"] for r in results]
    assert flags == [True, True, True, False, False]  # tagged matches first
    assert {r["news_event_id"] for r in results[3:]} == {ids["rbi"], ids["crude"]}


async def test_same_story_twice_is_returned_once_preferring_trusted_copy(pg_sessionmaker, chroma, fake_model):
    title = "Iraq shifts oil strategy by arranging tanker"
    yahoo = await add_news(pg_sessionmaker, title=title, description="Iraq oil tanker plan", seen_at=RECENT,
                           source_domain="uk.finance.yahoo.com")
    bloomberg = await add_news(pg_sessionmaker, title=title + "!", description="Iraq oil tanker plan details",
                               seen_at=RECENT, source_domain="bloomberg.com")
    await vs.embed_many([yahoo, bloomberg], pg_sessionmaker)

    results = await retrieve_relevant_news("Iraq oil tanker plan", top_k=5, session_factory=pg_sessionmaker)
    assert [r["news_event_id"] for r in results] == [bloomberg]
    assert results[0]["source_trust"] == "trusted"


# ---------------- embedding cache (used by the RAG-poisoning check) ----------------

def test_embed_cache_only_sends_new_texts_to_the_model(fake_model):
    first = vs.embed_texts_cached(["a b", "c d"])
    second = vs.embed_texts_cached(["c d", "e f", "a b"])
    assert fake_model.calls == [["a b", "c d"], ["e f"]]
    assert second[0] == first[1] and second[2] == first[0]


def test_embed_cache_is_bounded(fake_model, monkeypatch):
    monkeypatch.setattr(vs, "EMBED_CACHE_SIZE", 2)
    vs.embed_texts_cached(["one", "two", "three"])
    assert list(vs._embed_cache) == ["two", "three"]  # oldest evicted


async def test_recency_filter(pg_sessionmaker, chroma, fake_model):
    ids = await seed(pg_sessionmaker)
    results = await retrieve_relevant_news("Infosys deal", symbol="INFY.NS", top_k=10, max_age_days=30,
                                           session_factory=pg_sessionmaker)
    assert ids["old_infy"] not in {r["news_event_id"] for r in results}


async def test_min_similarity_drops_weak_matches(pg_sessionmaker, chroma, fake_model):
    await seed(pg_sessionmaker)
    results = await retrieve_relevant_news("crude oil supply", top_k=5, min_similarity=0.3,
                                           session_factory=pg_sessionmaker)
    assert [r["title"] for r in results] == ["Crude oil jumps"]


async def test_stale_or_reflagged_vectors_are_skipped_and_cleaned_up(pg_sessionmaker, chroma, fake_model):
    ids = await seed(pg_sessionmaker)
    async with pg_sessionmaker() as db:
        # one row deleted behind the vector store's back, one re-flagged as unsafe
        await db.execute(delete(NewsEvent).where(NewsEvent.id == ids["infy_deal"]))
        await db.execute(update(NewsEvent).where(NewsEvent.id == ids["it_sector"])
                         .values(security_status=SecurityStatus.SUSPICIOUS))
        await db.commit()

    results = await retrieve_relevant_news("Infosys deal wins", top_k=3, session_factory=pg_sessionmaker)
    returned = {r["news_event_id"] for r in results}
    assert ids["infy_deal"] not in returned and ids["it_sector"] not in returned
    assert len(results) == 3  # extra candidates fill the gap
    assert await vs.stored_ids([ids["infy_deal"], ids["it_sector"]]) == set()  # removed from Chroma


@pytest.mark.parametrize("query", ["", "   ", None])
async def test_empty_query(pg_sessionmaker, chroma, fake_model, query):
    assert await retrieve_relevant_news(query, session_factory=pg_sessionmaker) == []


async def test_empty_store(pg_sessionmaker, chroma, fake_model):
    assert await retrieve_relevant_news("anything", session_factory=pg_sessionmaker) == []


async def test_top_k_is_clamped(pg_sessionmaker, chroma, fake_model):
    await seed(pg_sessionmaker)
    assert len(await retrieve_relevant_news("news", top_k=0, session_factory=pg_sessionmaker)) == 1
    assert len(await retrieve_relevant_news("news", top_k=10_000, session_factory=pg_sessionmaker)) == 5


def test_build_where():
    assert build_where(None, None) is None
    assert build_where("INFY.NS", None) == {"symbols": {"$contains": "INFY.NS"}}
    where = build_where("INFY.NS", 7)
    assert where["$and"][0] == {"symbols": {"$contains": "INFY.NS"}}
    assert where["$and"][1]["seen_at"]["$gte"] <= int(datetime.now(UTC).timestamp()) - 7 * 86400 + 5
