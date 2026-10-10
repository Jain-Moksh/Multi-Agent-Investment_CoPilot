"""
app/services/llm.py: provider selection, ordered key fallback and error handling. The
vendor SDK clients are replaced with fakes; no network access or real API key is used.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import key_pool, llm


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")          # no cross-provider fallback unless a test sets one
    monkeypatch.setattr(settings, "OPENAI_API_KEYS", "")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-3.8-flash")
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
    def __init__(self, text="BLOCKED - bad", error=None):
        self.text, self.error, self.requests = text, error, []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.text))])


class APIError(Exception):
    """Looks like an SDK error: google-genai sets .code, openai sets .status_code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def per_key(monkeypatch, gemini=None, openai=None):
    """Use a different fake client per key: {key: fake}."""
    if gemini is not None:
        monkeypatch.setattr(llm, "_gemini_client", lambda key: gemini[key])
    if openai is not None:
        monkeypatch.setattr(llm, "_openai_client", lambda key: openai[key])


async def test_gemini_request_shape(monkeypatch):
    fake = FakeGemini()
    monkeypatch.setattr(llm, "_gemini_client", lambda key: fake)
    assert await llm.complete("system rules", "user text", max_tokens=50) == "SAFE - fine"
    request = fake.requests[0]
    assert request["model"] == settings.GEMINI_MODEL and request["contents"] == "user text"
    config = request["config"]
    assert config.system_instruction == "system rules" and config.temperature == 0.0
    assert config.max_output_tokens == 50 + settings.GEMINI_THINKING_TOKENS    # room for thinking
    assert config.thinking_config.thinking_level.value == settings.GEMINI_THINKING_LEVEL.upper()


async def test_gemini_25_flash_turns_thinking_off(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
    fake = FakeGemini()
    monkeypatch.setattr(llm, "_gemini_client", lambda key: fake)
    await llm.complete("s", "u", max_tokens=50)
    config = fake.requests[0]["config"]
    assert config.thinking_config.thinking_budget == 0 and config.max_output_tokens == 50


async def test_json_mode(monkeypatch):
    gemini = FakeGemini(text='{"a": 1}')
    monkeypatch.setattr(llm, "_gemini_client", lambda key: gemini)
    await llm.complete("s", "u")
    await llm.complete("s", "u", json_mode=True)
    assert gemini.requests[0]["config"].response_mime_type is None
    assert gemini.requests[1]["config"].response_mime_type == "application/json"

    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-openai-key")
    openai = FakeOpenAI(text='{"a": 1}')
    monkeypatch.setattr(llm, "_openai_client", lambda key: openai)
    await llm.complete("s", "u", json_mode=True)
    assert openai.requests[0]["response_format"] == {"type": "json_object"}


async def test_openai_request_shape(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "OpenAI")  # case-insensitive
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-openai-key")
    fake = FakeOpenAI()
    monkeypatch.setattr(llm, "_openai_client", lambda key: fake)
    assert await llm.complete("system rules", "user text") == "BLOCKED - bad"
    assert fake.requests[0]["messages"] == [
        {"role": "system", "content": "system rules"},
        {"role": "user", "content": "user text"},
    ]
    assert fake.requests[0]["model"] == settings.OPENAI_MODEL


@pytest.mark.parametrize(
    "provider, message",
    [("gemini", "GEMINI_API_KEY is not set"),
     ("openai", "OPENAI_API_KEY is not set"),
     ("claude", "LLM_PROVIDER must be one of")],
)
async def test_not_configured(monkeypatch, provider, message):
    monkeypatch.setattr(settings, "LLM_PROVIDER", provider)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    with pytest.raises(llm.LLMNotConfigured, match=message):
        await llm.complete("s", "u")


async def test_timeout_becomes_llm_error(monkeypatch):
    monkeypatch.setattr(settings, "LLM_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(llm, "_gemini_client", lambda key: FakeGemini(delay=1))
    with pytest.raises(llm.LLMError, match="timed out"):
        await llm.complete("s", "u")


async def test_sdk_error_becomes_llm_error(monkeypatch):
    monkeypatch.setattr(llm, "_gemini_client", lambda key: FakeGemini(error=RuntimeError("429 RESOURCE_EXHAUSTED")))
    with pytest.raises(llm.LLMError, match="RESOURCE_EXHAUSTED"):
        await llm.complete("s", "u")


async def test_empty_reply_is_an_error(monkeypatch):
    monkeypatch.setattr(llm, "_gemini_client", lambda key: FakeGemini(text="   "))
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

    monkeypatch.setattr(llm, "_gemini_client", lambda key: Counting())
    await asyncio.gather(*(llm.complete("s", "u") for _ in range(6)))
    assert peak == 2


# ---------------- ordered key fallback ----------------

async def test_falls_back_to_the_next_key_in_order(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key-aaaa1,key-bbbb2,key-cccc3")
    fakes = {"key-aaaa1": FakeGemini(error=APIError(429, "429 RESOURCE_EXHAUSTED per minute")),
             "key-bbbb2": FakeGemini(text=""),
             "key-cccc3": FakeGemini(text="third key answered")}
    per_key(monkeypatch, gemini=fakes)

    assert await llm.complete("s", "u") == "third key answered"
    assert [len(f.requests) for f in fakes.values()] == [1, 1, 1]
    # The rate-limited key rests; the empty-reply one does not. Next call skips key 1, tries key 2 again.
    assert key_pool.usable_keys("gemini") == ["key-bbbb2", "key-cccc3"]
    fakes["key-bbbb2"].error = None
    fakes["key-bbbb2"].text = "second key is back"
    assert await llm.complete("s", "u") == "second key is back"
    assert len(fakes["key-aaaa1"].requests) == 1


async def test_overloaded_model_falls_back_to_the_next_model_not_the_next_key(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODEL", "model-a, model-b")
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key-bbbb2")
    calls = []

    class ByModel(FakeGemini):
        async def _generate(self, *, model, contents, config):
            calls.append((self.key, model))
            if model == "model-a":
                raise APIError(503, "503 UNAVAILABLE. This model is currently experiencing high demand.")
            return SimpleNamespace(text=f"{model} answered")

    def client(key):
        fake = ByModel()
        fake.key = key
        return fake

    monkeypatch.setattr(llm, "_gemini_client", client)
    assert await llm.complete("s", "u") == "model-b answered"
    assert calls == [("test-gemini-key", "model-a"), ("test-gemini-key", "model-b")]   # key 2 never wasted on A
    assert key_pool.usable_keys("gemini") == ["test-gemini-key", "key-bbbb2"]          # 503 is not the key's fault
    assert llm.model_name() == "model-a"


async def test_timeout_also_moves_to_the_next_model(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODEL", "slow-model,fast-model")
    monkeypatch.setattr(settings, "LLM_TIMEOUT_SECONDS", 0.05)

    class Slow(FakeGemini):
        async def _generate(self, *, model, contents, config):
            if model == "slow-model":
                await asyncio.sleep(1)
            return SimpleNamespace(text=model)

    monkeypatch.setattr(llm, "_gemini_client", lambda key: Slow())
    assert await llm.complete("s", "u") == "fast-model"


async def test_first_working_key_is_used_and_later_keys_are_not_touched(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key-bbbb2")
    fakes = {"test-gemini-key": FakeGemini(text="first"), "key-bbbb2": FakeGemini(text="second")}
    per_key(monkeypatch, gemini=fakes)
    assert await llm.complete("s", "u") == "first"
    assert fakes["key-bbbb2"].requests == []


async def test_falls_back_from_gemini_to_openai(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEYS", "sk-test-1111")
    per_key(monkeypatch,
            gemini={"test-gemini-key": FakeGemini(error=APIError(400, "API key not valid. API_KEY_INVALID"))},
            openai={"sk-test-1111": FakeOpenAI(text="openai answered")})
    assert await llm.complete("s", "u") == "openai answered"
    assert key_pool.usable_keys("gemini") == []                       # invalid key rests for hours


async def test_cross_provider_fallback_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(settings, "LLM_CROSS_PROVIDER_FALLBACK", False)
    monkeypatch.setattr(settings, "OPENAI_API_KEYS", "sk-test-1111")
    openai = FakeOpenAI()
    per_key(monkeypatch, gemini={"test-gemini-key": FakeGemini(error=APIError(503, "down"))},
            openai={"sk-test-1111": openai})
    with pytest.raises(llm.LLMError, match="all LLM keys failed"):
        await llm.complete("s", "u")
    assert openai.requests == []


async def test_all_keys_failing_lists_every_attempt(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key-bbbb2")
    monkeypatch.setattr(settings, "OPENAI_API_KEYS", "sk-test-1111")
    per_key(monkeypatch,
            gemini={"test-gemini-key": FakeGemini(error=APIError(429, "quota exceeded per minute")),
                    "key-bbbb2": FakeGemini(text="")},
            openai={"sk-test-1111": FakeOpenAI(error=APIError(429, "insufficient_quota: no credits"))})
    with pytest.raises(llm.LLMError) as info:
        await llm.complete("s", "u")
    message = str(info.value)
    assert "...-key" in message and "...bbb2" in message and "...1111" in message
    assert "test-gemini-key" not in message and "sk-test-1111" not in message   # keys are masked

    # Every key is resting now (only the empty-reply key is not): the next call tries just that one.
    assert key_pool.usable_keys("gemini") == ["key-bbbb2"] and key_pool.usable_keys("openai") == []


async def test_everything_resting_fails_fast_without_calls(monkeypatch):
    fake = FakeGemini()
    monkeypatch.setattr(llm, "_gemini_client", lambda key: fake)
    key_pool.report_failure("gemini", "test-gemini-key", key_pool.Failure.RATE_LIMIT)
    with pytest.raises(llm.LLMError, match="resting"):
        await llm.complete("s", "u")
    assert fake.requests == []
