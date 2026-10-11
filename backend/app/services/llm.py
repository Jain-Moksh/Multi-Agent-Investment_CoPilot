"""
One small entry point for LLM calls: `await complete(system, user)`.

The rest of the app never imports a vendor SDK directly. LLM_PROVIDER in .env
selects Gemini (google-genai) or OpenAI, so switching provider is a config
change, not a code change. Clients are created lazily, once per key, and reused.

Fallback order: provider LLM_PROVIDER first, then (LLM_CROSS_PROVIDER_FALLBACK)
the other one; within a provider each model of GEMINI_MODEL / OPENAI_MODEL
(comma-separated) in order, and for each model every usable key in order.
- rate limit / quota -> that key rests for a while FOR THAT MODEL only (Gemini counts
  quota per key and model, so the same key is still tried on the next model);
  invalid key -> the key rests for every model (app/services/key_pool.py);
- server error (5xx) or timeout -> the model is overloaded or down, so the
  next MODEL is tried (other keys would hit the same overloaded model);
- empty reply / other errors -> next key.
Only when every attempt failed does the caller get an error.

Every failure (no key, timeout, rate limit, API error, empty answer) becomes
LLMError, so callers can decide how to fail safely. A semaphore caps
concurrent calls (free tiers allow only a few requests per minute).
"""

import asyncio
import logging
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.services import key_pool

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("gemini", "openai")


class LLMError(Exception):
    """Any problem getting an answer from the LLM."""


class LLMNotConfigured(LLMError):
    pass


_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.LLM_MAX_CONCURRENT_CALLS)
    return _semaphore


def provider() -> str:
    """The primary provider (LLM_PROVIDER), validated."""
    name = settings.LLM_PROVIDER.strip().lower()
    if name not in SUPPORTED_PROVIDERS:
        raise LLMNotConfigured(f"LLM_PROVIDER must be one of {SUPPORTED_PROVIDERS}, got {settings.LLM_PROVIDER!r}")
    return name


def provider_order() -> list[str]:
    primary = provider()
    if not settings.LLM_CROSS_PROVIDER_FALLBACK:
        return [primary]
    return [primary] + [name for name in SUPPORTED_PROVIDERS if name != primary]


def models(name: str) -> list[str]:
    """Models to try for a provider, in order (GEMINI_MODEL / OPENAI_MODEL may be comma-separated)."""
    raw = settings.GEMINI_MODEL if name == "gemini" else settings.OPENAI_MODEL
    return [model.strip() for model in raw.split(",") if model.strip()]


def model_name(name: str | None = None) -> str:
    """The first-choice model of `name` (default: the primary provider)."""
    return models(name or provider())[0]


# ---------------- vendor clients (lazy, cached per key) ----------------

@lru_cache
def _gemini_client(key: str) -> Any:
    from google import genai

    return genai.Client(api_key=key)


@lru_cache
def _openai_client(key: str) -> Any:
    from openai import AsyncOpenAI

    # No SDK retries: on failure we move straight on to the next key.
    return AsyncOpenAI(api_key=key, max_retries=0)


def _gemini_thinking(types: Any, model: str) -> tuple[Any, int]:
    """(thinking_config, extra output tokens to allow for thinking) for a Gemini model."""
    model = model.lower()
    if model.startswith("gemini-2.5-flash"):
        return types.ThinkingConfig(thinking_budget=0), 0          # 2.5 Flash can switch thinking off
    level = settings.GEMINI_THINKING_LEVEL.strip().upper()
    if level and not model.startswith(("gemini-1", "gemini-2")):
        return types.ThinkingConfig(thinking_level=level), settings.GEMINI_THINKING_TOKENS
    return None, settings.GEMINI_THINKING_TOKENS


async def _complete_gemini(key: str, model: str, system: str, user: str, max_tokens: int, json_mode: bool) -> str:
    from google.genai import types

    thinking, thinking_tokens = _gemini_thinking(types, model)
    response = await _gemini_client(key).aio.models.generate_content(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.0,
            # Thinking tokens count against this limit, so leave room for them.
            max_output_tokens=max_tokens + thinking_tokens,
            thinking_config=thinking,
            response_mime_type="application/json" if json_mode else None,
            # We never pass tools; turning this off also silences an SDK warning on every call.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    return response.text or ""


async def _complete_openai(key: str, model: str, system: str, user: str, max_tokens: int, json_mode: bool) -> str:
    extra: dict[str, Any] = {"response_format": {"type": "json_object"}} if json_mode else {}
    response = await _openai_client(key).chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_completion_tokens=max_tokens,
        **extra,
    )
    return response.choices[0].message.content or ""


def _status_code(exc: Exception) -> int | None:
    """HTTP status of an SDK error: google-genai uses .code, openai uses .status_code."""
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


# ---------------- public API ----------------

async def complete(system: str, user: str, *, max_tokens: int = 1024, json_mode: bool = False) -> str:
    """
    Send one system + user message and return the reply text.
    json_mode=True asks the provider for a JSON-only reply (the prompt should
    still describe the expected keys; callers must validate the result).
    Tries every usable key in order (see module docstring).
    Raises LLMError (or LLMNotConfigured) when no key gave an answer; never returns "".
    """
    order = provider_order()
    if not any(settings.api_keys(name) for name in order):
        primary = order[0].upper()
        raise LLMNotConfigured(f"{primary}_API_KEY is not set in backend/.env (or list keys in {primary}_API_KEYS)")

    failures: list[str] = []
    async with _get_semaphore():
        for name in order:
            call = _complete_gemini if name == "gemini" else _complete_openai
            for model in models(name):
                for key in key_pool.usable_keys(name, scope=model):
                    label = f"{name} {model} key {key_pool.mask(key)}"
                    model_down = False
                    try:
                        text = await asyncio.wait_for(
                            call(key, model, system, user, max_tokens, json_mode), timeout=settings.LLM_TIMEOUT_SECONDS
                        )
                    except TimeoutError:
                        error = f"{label} timed out after {settings.LLM_TIMEOUT_SECONDS:.0f}s"
                        kind, model_down = key_pool.Failure.OTHER, True
                    except Exception as exc:  # SDK errors: auth, rate limit (429), server errors, network
                        error = f"{label} call failed: {type(exc).__name__}: {str(exc)[:200]}"
                        status = _status_code(exc)
                        kind = key_pool.classify(status, str(exc))
                        model_down = status is not None and status >= 500
                    else:
                        if text.strip():
                            key_pool.report_success(name, key, scope=model)
                            if failures:
                                logger.info("[llm] answered by %s after %d failed attempt(s)", label, len(failures))
                            return text.strip()
                        error, kind = f"{label} returned an empty response", key_pool.Failure.OTHER
                    key_pool.report_failure(name, key, kind, error, scope=model)
                    failures.append(error)
                    if model_down:
                        # Overloaded / down / too slow: the same model on another key would fail
                        # the same way, so go straight to the next model.
                        break

    if not failures:
        raise LLMError("every LLM key is resting after rate-limit / quota / auth errors; try again later")
    raise LLMError("all LLM keys failed: " + " | ".join(failures))
