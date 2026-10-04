"""
One small entry point for LLM calls: `await complete(system, user)`.

The rest of the app never imports a vendor SDK directly. LLM_PROVIDER in .env
selects Gemini (google-genai) or OpenAI, so switching provider is a config
change, not a code change. Clients are created lazily, once, and reused.

Every failure (no key, timeout, rate limit, API error, empty answer) becomes
LLMError, so callers can decide how to fail safely. A semaphore caps
concurrent calls (free tiers allow only a few requests per minute).
"""

import asyncio
import logging
from functools import lru_cache
from typing import Any

from app.core.config import settings

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
    name = settings.LLM_PROVIDER.strip().lower()
    if name not in SUPPORTED_PROVIDERS:
        raise LLMNotConfigured(f"LLM_PROVIDER must be one of {SUPPORTED_PROVIDERS}, got {settings.LLM_PROVIDER!r}")
    key = settings.GEMINI_API_KEY if name == "gemini" else settings.OPENAI_API_KEY
    if not key:
        raise LLMNotConfigured(f"{name.upper()}_API_KEY is not set in backend/.env")
    return name


def model_name() -> str:
    return settings.GEMINI_MODEL if provider() == "gemini" else settings.OPENAI_MODEL


# ---------------- vendor clients (lazy, cached) ----------------

@lru_cache
def _gemini_client() -> Any:
    from google import genai

    return genai.Client(api_key=settings.GEMINI_API_KEY)


@lru_cache
def _openai_client() -> Any:
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY, max_retries=1)


async def _complete_gemini(system: str, user: str, max_tokens: int, json_mode: bool) -> str:
    from google.genai import types

    response = await _gemini_client().aio.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.0,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if json_mode else None,
            # We never pass tools; turning this off also silences an SDK warning on every call.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    return response.text or ""


async def _complete_openai(system: str, user: str, max_tokens: int, json_mode: bool) -> str:
    extra: dict[str, Any] = {"response_format": {"type": "json_object"}} if json_mode else {}
    response = await _openai_client().chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_completion_tokens=max_tokens,
        **extra,
    )
    return response.choices[0].message.content or ""


# ---------------- public API ----------------

async def complete(system: str, user: str, *, max_tokens: int = 1024, json_mode: bool = False) -> str:
    """
    Send one system + user message and return the reply text.
    json_mode=True asks the provider for a JSON-only reply (the prompt should
    still describe the expected keys; callers must validate the result).
    Raises LLMError (or LLMNotConfigured) on any failure; never returns "".
    """
    name = provider()
    call = _complete_gemini if name == "gemini" else _complete_openai
    async with _get_semaphore():
        try:
            text = await asyncio.wait_for(
                call(system, user, max_tokens, json_mode), timeout=settings.LLM_TIMEOUT_SECONDS
            )
        except TimeoutError:
            raise LLMError(f"{name} timed out after {settings.LLM_TIMEOUT_SECONDS:.0f}s") from None
        except LLMError:
            raise
        except Exception as exc:  # SDK errors: auth, rate limit (429), server errors, network
            raise LLMError(f"{name} call failed: {type(exc).__name__}: {str(exc)[:200]}") from exc
    if not text.strip():
        raise LLMError(f"{name} returned an empty response")
    return text.strip()
