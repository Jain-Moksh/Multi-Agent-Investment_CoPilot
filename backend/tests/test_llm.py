"""
app/services/llm.py: provider selection and error handling. The vendor SDK
clients are replaced with fakes; no network access or API key is used.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import llm


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(llm, "_semaphore", None)


class FakeGemini:
    def __init__(self, text="SAFE - fine", delay=0.0, error=None):
        self.text, self.delay, self.error, self.requests = text, delay, error, []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, *, model, contents, config):
        self.requests.append({"model": model, "contents": contents, "config": config})
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text)


class FakeOpenAI:
    def __init__(self, text="BLOCKED - bad"):
        self.text, self.requests = text, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.text))])


async def test_gemini_request_shape(monkeypatch):
    fake = FakeGemini()
    monkeypatch.setattr(llm, "_gemini_client", lambda: fake)
    assert await llm.complete("system rules", "user text", max_tokens=50) == "SAFE - fine"
    request = fake.requests[0]
    assert request["model"] == settings.GEMINI_MODEL and request["contents"] == "user text"
    assert request["config"].system_instruction == "system rules"
    assert request["config"].temperature == 0.0 and request["config"].max_output_tokens == 50


async def test_json_mode(monkeypatch):
    gemini = FakeGemini(text='{"a": 1}')
    monkeypatch.setattr(llm, "_gemini_client", lambda: gemini)
    await llm.complete("s", "u")
    await llm.complete("s", "u", json_mode=True)
    assert gemini.requests[0]["config"].response_mime_type is None
    assert gemini.requests[1]["config"].response_mime_type == "application/json"

    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    openai = FakeOpenAI(text='{"a": 1}')
    monkeypatch.setattr(llm, "_openai_client", lambda: openai)
    await llm.complete("s", "u", json_mode=True)
    assert openai.requests[0]["response_format"] == {"type": "json_object"}


async def test_openai_request_shape(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "OpenAI")  # case-insensitive
    fake = FakeOpenAI()
    monkeypatch.setattr(llm, "_openai_client", lambda: fake)
    assert await llm.complete("system rules", "user text") == "BLOCKED - bad"
    assert fake.requests[0]["messages"] == [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "user text"},
    ]
    assert fake.requests[0]["model"] == settings.OPENAI_MODEL


@pytest.mark.parametrize(
    "provider, key_field, message",
    [("gemini", "GEMINI_API_KEY", "GEMINI_API_KEY is not set"),
     ("openai", "OPENAI_API_KEY", "OPENAI_API_KEY is not set"),
     ("claude", None, "LLM_PROVIDER must be one of")],
)
async def test_not_configured(monkeypatch, provider, key_field, message):
    monkeypatch.setattr(settings, "LLM_PROVIDER", provider)
    if key_field:
        monkeypatch.setattr(settings, key_field, "")
    with pytest.raises(llm.LLMNotConfigured, match=message):
        await llm.complete("s", "u")


async def test_timeout_becomes_llm_error(monkeypatch):
    monkeypatch.setattr(settings, "LLM_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(llm, "_gemini_client", lambda: FakeGemini(delay=1))
    with pytest.raises(llm.LLMError, match="timed out"):
        await llm.complete("s", "u")


async def test_sdk_error_becomes_llm_error(monkeypatch):
    monkeypatch.setattr(llm, "_gemini_client", lambda: FakeGemini(error=RuntimeError("429 RESOURCE_EXHAUSTED")))
    with pytest.raises(llm.LLMError, match="RESOURCE_EXHAUSTED"):
        await llm.complete("s", "u")


async def test_empty_reply_is_an_error(monkeypatch):
    monkeypatch.setattr(llm, "_gemini_client", lambda: FakeGemini(text="   "))
    with pytest.raises(llm.LLMError, match="empty"):
        await llm.complete("s", "u")


async def test_concurrency_is_capped(monkeypatch):
    monkeypatch.setattr(settings, "LLM_MAX_CONCURRENT_CALLS", 2)
    running = peak = 0

    class Counting(FakeGemini):
        async def _generate(self, **kwargs):  # noqa: ARG002
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.02)
            running -= 1
            return SimpleNamespace(text="SAFE - ok")

    monkeypatch.setattr(llm, "_gemini_client", lambda: Counting())
    await asyncio.gather(*(llm.complete("s", "u") for _ in range(6)))
    assert peak == 2
