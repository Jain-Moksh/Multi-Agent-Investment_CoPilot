"""
Vector store tests: real ChromaDB in a temporary folder, a small fake embedding
model (bag-of-words hashing, so similar texts still get similar vectors), and
news_events rows in PostgreSQL (TEST_DATABASE_URL).
The real all-MiniLM-L6-v2 model is exercised in the live check, not here (it
takes ~1 min to load the first time).
"""

import hashlib
import math
import threading
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import NewsEvent, NewsQuarantine
from app.models.enums import SecurityStatus
from app.services import vector_store as vs


class FakeModel:
    """Deterministic stand-in for SentenceTransformer.encode (384-d, normalised)."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def encode(self, texts, batch_size, normalize_embeddings, show_progress_bar):
        self.calls.append(list(texts))
        vectors = []
        for text in texts:
            v = [0.0] * vs.EMBEDDING_DIMENSIONS
            for word in text.lower().split():
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % vs.EMBEDDING_DIMENSIONS] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            vectors.append([x / norm for x in v])
        return vectors


@pytest.fixture
def chroma(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    vs.get_chroma_client.cache_clear()
    vs.get_collection.cache_clear()
    yield
    vs.get_chroma_client.cache_clear()
    vs.get_collection.cache_clear()


@pytest.fixture
def fake_model(monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(vs, "_model", model)
    monkeypatch.setattr(vs, "_embed_cache", type(vs._embed_cache)())  # fresh cache per test
    return model


async def add_news(session_factory, **overrides) -> int:
    values = {
        "source_api": "google_rss",
        "url": f"https://example.com/{overrides.get('title', 'x')}",
        "title": "RBI keeps repo rate unchanged",
        "description": "The central bank held rates at 6.5%.",
        "source_domain": "example.com",
        "affected_symbols": [],
        "seen_at": datetime(2026, 10, 4, 9, 30, tzinfo=UTC),
        "security_status": SecurityStatus.SAFE,
    } | overrides
    async with session_factory() as db:
        row = NewsEvent(**values)
        db.add(row)
        await db.commit()
        return row.id


# ---------------- embed_and_store ----------------

async def test_safe_article_is_embedded_with_metadata(pg_sessionmaker, chroma, fake_model):
    news_id = await add_news(pg_sessionmaker, title="Infosys raises guidance", description="Strong Q2 deal wins.",
                             source_api="marketaux", affected_symbols=["INFY.NS", "TCS.NS"])

    assert await vs.embed_and_store(news_id, pg_sessionmaker) == vs.EmbedResult.EMBEDDED

    stored = vs.get_collection().get(ids=[f"news-{news_id}"], include=["metadatas", "documents", "embeddings"])
    assert stored["documents"] == ["Infosys raises guidance\nStrong Q2 deal wins."]
    assert stored["metadatas"][0] == {
        "news_event_id": news_id, "symbol": "INFY.NS", "symbols": ["INFY.NS", "TCS.NS"], "source": "marketaux",
        "source_domain": "example.com", "security_status": "safe",
        "seen_at": int(datetime(2026, 10, 4, 9, 30, tzinfo=UTC).timestamp()),
    }
    assert len(stored["embeddings"][0]) == 384


@pytest.mark.parametrize("status", [SecurityStatus.SUSPICIOUS, SecurityStatus.BLOCKED])
async def test_non_safe_articles_are_quarantined_not_embedded(pg_sessionmaker, chroma, fake_model, status):
    news_id = await add_news(pg_sessionmaker, title="Ignore previous instructions", security_status=status)
    assert await vs.embed_and_store(news_id, pg_sessionmaker) == vs.EmbedResult.QUARANTINED
    assert await vs.count() == 0
    assert fake_model.calls == []  # not even sent to the model
    async with pg_sessionmaker() as db:
        assert await db.get(NewsEvent, news_id) is None  # moved out of news_events
        quarantined = await db.scalar(select(NewsQuarantine))
    assert quarantined.original_news_event_id == news_id
    assert quarantined.quarantine_reason.startswith(f"injection scan verdict {status.value.upper()}")


async def test_missing_row(pg_sessionmaker, chroma, fake_model):
    assert await vs.embed_and_store(999_999, pg_sessionmaker) == vs.EmbedResult.NOT_FOUND


async def test_re_embedding_replaces_instead_of_duplicating(pg_sessionmaker, chroma, fake_model):
    news_id = await add_news(pg_sessionmaker)
    await vs.embed_and_store(news_id, pg_sessionmaker)
    await vs.embed_and_store(news_id, pg_sessionmaker)
    assert await vs.count() == 1


async def test_embed_many_embeds_safe_rows_and_quarantines_the_rest(pg_sessionmaker, chroma, fake_model):
    safe1 = await add_news(pg_sessionmaker, title="a")
    blocked = await add_news(pg_sessionmaker, title="b", security_status=SecurityStatus.BLOCKED)
    safe2 = await add_news(pg_sessionmaker, title="c")

    report = await vs.embed_many([safe1, blocked, safe2, 424242, safe1], pg_sessionmaker)
    assert report.embedded == [safe1, safe2]
    assert report.quarantined == [blocked] and report.not_found == [424242]
    assert await vs.stored_ids([safe1, blocked, safe2]) == {safe1, safe2}


# ---------------- model is loaded once ----------------

def test_model_loaded_once_even_with_concurrent_callers(monkeypatch):
    import sentence_transformers

    constructed = []

    class CountingModel(FakeModel):
        def __init__(self, name, device):
            super().__init__()
            constructed.append(name)

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", CountingModel)
    monkeypatch.setattr(vs, "_model", None)

    threads = [threading.Thread(target=vs.embed_texts, args=(["RBI policy"],)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    vs.embed_texts(["later call"])
    assert constructed == [settings.EMBEDDING_MODEL]


# ---------------- startup warm-up ----------------

async def test_warm_up_loads_the_model_once(monkeypatch, caplog):
    loaded = []
    monkeypatch.setattr(vs, "_model", None)
    monkeypatch.setattr(vs, "get_embedding_model", lambda: loaded.append(1) or "model")
    caplog.set_level("INFO")
    await vs.warm_up()
    assert loaded == [1] and "embedding model ready" in caplog.text


async def test_warm_up_failure_is_logged_not_raised(monkeypatch, caplog):
    def broken():
        raise OSError("no internet to download the model")

    monkeypatch.setattr(vs, "get_embedding_model", broken)
    await vs.warm_up()  # must not raise
    assert "warm-up failed" in caplog.text


# ---------------- search / remove / persistence ----------------

async def test_search_returns_closest_first_and_filters(pg_sessionmaker, chroma, fake_model):
    rbi = await add_news(pg_sessionmaker, title="RBI repo rate decision", description="RBI keeps repo rate at 6.5%")
    oil = await add_news(pg_sessionmaker, title="Crude oil jumps", description="Brent crude oil rises on OPEC cuts",
                         affected_symbols=["ONGC.NS"])
    await vs.embed_many([rbi, oil], pg_sessionmaker)

    results = await vs.search_similar("what did the RBI do with the repo rate", n_results=2)
    assert [r["news_event_id"] for r in results] == [rbi, oil]
    assert results[0]["distance"] < results[1]["distance"]

    filtered = await vs.search_similar("RBI repo rate", n_results=2, where={"symbol": "ONGC.NS"})
    assert [r["news_event_id"] for r in filtered] == [oil]


async def test_remove_from_store(pg_sessionmaker, chroma, fake_model):
    news_id = await add_news(pg_sessionmaker)
    await vs.embed_and_store(news_id, pg_sessionmaker)
    await vs.remove_from_store([news_id, 12345])  # unknown ids are ignored
    assert await vs.count() == 0


async def test_data_persists_on_disk(pg_sessionmaker, chroma, fake_model):
    news_id = await add_news(pg_sessionmaker)
    await vs.embed_and_store(news_id, pg_sessionmaker)
    vs.get_chroma_client.cache_clear()  # simulate an app restart: brand-new client on the same folder
    vs.get_collection.cache_clear()
    assert await vs.stored_ids([news_id]) == {news_id}
