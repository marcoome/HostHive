"""Unified AI client supporting OpenAI, Anthropic Claude, and local Ollama."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Any, AsyncGenerator, Optional

import httpx
import redis.asyncio as aioredis

from api.core.config import settings

logger = logging.getLogger("hosthive.ai")

SUPPORTED_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    "anthropic": ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001", "claude-opus-4-20250514"],
    "openrouter": ["openai/gpt-4o", "anthropic/claude-sonnet-4", "google/gemini-2.5-pro"],
    "ollama": ["llama3", "llama3.1", "mistral", "codellama", "phi3", "gemma2"],
}

# Cost per 1K tokens (input, output) in USD — rough estimates for tracking
_COST_PER_1K: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "claude-opus-4-20250514": (0.015, 0.075),
    "claude-sonnet-4-20250514": (0.003, 0.015),
    "claude-haiku-4-5-20251001": (0.001, 0.005),
    "llama3": (0.0, 0.0),
    "mistral": (0.0, 0.0),
    "codellama": (0.0, 0.0),
    "phi3": (0.0, 0.0),
}

# Patterns for sensitive data that must NEVER be sent to AI providers
_SENSITIVE_PATTERNS = [
    re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----.*?-----END\s+(RSA\s+)?PRIVATE\s+KEY-----", re.DOTALL),
    re.compile(r"-----BEGIN\s+CERTIFICATE-----.*?-----END\s+CERTIFICATE-----", re.DOTALL),
    re.compile(r"(?i)(password|passwd|api_key|secret_key|access_token|bearer)\s*[:=]\s*\S+"),
]

_REDIS_CACHE_PREFIX = "hosthive:ai:cache:"
_CACHE_TTL = 300  # 5 minutes
_MAX_RETRIES = 3
_TIMEOUT = 60.0


def _sanitize_content(text: str) -> str:
    """Strip passwords, API keys, SSL certs, and other secrets from text."""
    sanitized = text
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


def _cache_key(provider: str, model: str, messages: list[dict], system: str | None) -> str:
    """Deterministic cache key for a prompt."""
    blob = json.dumps({"p": provider, "m": model, "msgs": messages, "s": system}, sort_keys=True)
    return _REDIS_CACHE_PREFIX + hashlib.sha256(blob.encode()).hexdigest()


class AIClient:
    """Supports OpenAI, Anthropic Claude, and local Ollama."""

    def __init__(
        self,
        provider: str,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        if provider not in SUPPORTED_MODELS:
            raise ValueError(f"Unsupported provider: {provider}")
        self.provider = provider
        self.api_key = api_key
        self.model = model or SUPPORTED_MODELS[provider][0]
        self.base_url = base_url
        self._http = httpx.AsyncClient(timeout=_TIMEOUT)

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Token counting (approximate)
    # ------------------------------------------------------------------

    @staticmethod
    def count_tokens(text: str) -> int:
        """Approximate token count: ~4 chars per token."""
        return max(1, len(text) // 4)

    # ------------------------------------------------------------------
    # Cost tracking
    # ------------------------------------------------------------------

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float:
        rates = _COST_PER_1K.get(self.model, (0.0, 0.0))
        return (tokens_in / 1000) * rates[0] + (tokens_out / 1000) * rates[1]

    # ------------------------------------------------------------------
    # Main chat method
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        system: str | None = None,
        *,
        stream: bool = False,
        max_tokens: int = 1000,
        json_mode: bool = False,
    ) -> str | AsyncGenerator[str, None]:
        """Send a chat request.  Returns str or AsyncGenerator for streaming."""
        # Sanitize all message content
        safe_messages = [
            {**m, "content": _sanitize_content(m.get("content", ""))}
            for m in messages
        ]
        if system:
            system = _sanitize_content(system)

        # Check Redis cache for non-streaming requests
        if not stream:
            cached = await self._check_cache(safe_messages, system)
            if cached is not None:
                return cached

        # Retry with exponential backoff
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                if stream:
                    return self._stream_request(safe_messages, system, max_tokens, json_mode)
                else:
                    result = await self._single_request(safe_messages, system, max_tokens, json_mode)
                    await self._set_cache(safe_messages, system, result)
                    return result
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "AI request attempt %d failed (%s: %s), retrying in %ds",
                        attempt + 1, type(exc).__name__, exc, wait,
                    )
                    await asyncio.sleep(wait)

        raise RuntimeError(f"AI request failed after {_MAX_RETRIES} attempts: {last_exc}")

    # ------------------------------------------------------------------
    # Analyze helper — always returns parsed JSON
    # ------------------------------------------------------------------

    async def analyze(self, prompt: str) -> dict:
        """Send a prompt expecting a JSON response.  Always returns a dict."""
        raw = await self.chat(
            [{"role": "user", "content": prompt}],
            system="You are a server administration expert. Always respond with valid JSON.",
            json_mode=True,
        )
        assert isinstance(raw, str)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown fences
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            # Last resort: wrap in a result object
            return {"raw_response": raw, "parse_error": True}

    # ------------------------------------------------------------------
    # Provider-specific request builders
    # ------------------------------------------------------------------

    async def _single_request(
        self,
        messages: list[dict[str, str]],
        system: str | None,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        if self.provider in ("openai", "openrouter"):
            return await self._openai_request(messages, system, max_tokens, json_mode, stream=False)
        elif self.provider == "anthropic":
            return await self._anthropic_request(messages, system, max_tokens, json_mode, stream=False)
        elif self.provider == "ollama":
            return await self._ollama_request(messages, system, max_tokens, json_mode, stream=False)
        raise ValueError(f"Unknown provider: {self.provider}")

    async def _stream_request(
        self,
        messages: list[dict[str, str]],
        system: str | None,
        max_tokens: int,
        json_mode: bool,
    ) -> AsyncGenerator[str, None]:
        if self.provider in ("openai", "openrouter"):
            return self._openai_stream(messages, system, max_tokens, json_mode)
        elif self.provider == "anthropic":
            return self._anthropic_stream(messages, system, max_tokens, json_mode)
        elif self.provider == "ollama":
            return self._ollama_stream(messages, system, max_tokens, json_mode)
        raise ValueError(f"Unknown provider: {self.provider}")

    # ── OpenAI ────────────────────────────────────────────────────────

    def _openai_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _openai_body(
        self,
        messages: list[dict[str, str]],
        system: str | None,
        max_tokens: int,
        json_mode: bool,
        stream: bool,
    ) -> dict[str, Any]:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    async def _openai_request(
        self, messages, system, max_tokens, json_mode, stream,
    ) -> str:
        url = (self.base_url or "https://api.openai.com") + "/v1/chat/completions"
        body = self._openai_body(messages, system, max_tokens, json_mode, stream=False)
        resp = await self._http.post(url, json=body, headers=self._openai_headers())
        resp.raise_for_status()
        data = resp.json()
        tokens_in = data.get("usage", {}).get("prompt_tokens", 0)
        tokens_out = data.get("usage", {}).get("completion_tokens", 0)
        logger.info("OpenAI tokens: in=%d out=%d model=%s", tokens_in, tokens_out, self.model)
        return data["choices"][0]["message"]["content"]

    async def _openai_stream(
        self, messages, system, max_tokens, json_mode,
    ) -> AsyncGenerator[str, None]:
        url = (self.base_url or "https://api.openai.com") + "/v1/chat/completions"
        body = self._openai_body(messages, system, max_tokens, json_mode, stream=True)
        async with self._http.stream("POST", url, json=body, headers=self._openai_headers()) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunk = json.loads(line[6:])
                    delta = chunk["choices"][0].get("delta", {}).get("content", "")
                    if delta:
                        yield delta

    # ── Anthropic ─────────────────────────────────────────────────────

    def _anthropic_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _anthropic_body(
        self,
        messages: list[dict[str, str]],
        system: str | None,
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if system:
            body["system"] = system
        return body

    async def _anthropic_request(
        self, messages, system, max_tokens, json_mode, stream,
    ) -> str:
        url = (self.base_url or "https://api.anthropic.com") + "/v1/messages"
        body = self._anthropic_body(messages, system, max_tokens, stream=False)
        resp = await self._http.post(url, json=body, headers=self._anthropic_headers())
        resp.raise_for_status()
        data = resp.json()
        tokens_in = data.get("usage", {}).get("input_tokens", 0)
        tokens_out = data.get("usage", {}).get("output_tokens", 0)
        logger.info("Anthropic tokens: in=%d out=%d model=%s", tokens_in, tokens_out, self.model)
        return data["content"][0]["text"]

    async def _anthropic_stream(
        self, messages, system, max_tokens, json_mode,
    ) -> AsyncGenerator[str, None]:
        url = (self.base_url or "https://api.anthropic.com") + "/v1/messages"
        body = self._anthropic_body(messages, system, max_tokens, stream=True)
        async with self._http.stream("POST", url, json=body, headers=self._anthropic_headers()) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    chunk = json.loads(line[6:])
                    if chunk.get("type") == "content_block_delta":
                        text = chunk.get("delta", {}).get("text", "")
                        if text:
                            yield text

    # ── Ollama ────────────────────────────────────────────────────────

    def _ollama_body(
        self,
        messages: list[dict[str, str]],
        system: str | None,
        stream: bool,
        json_mode: bool,
    ) -> dict[str, Any]:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": msgs,
            "stream": stream,
        }
        if json_mode:
            body["format"] = "json"
        return body

    async def _ollama_request(
        self, messages, system, max_tokens, json_mode, stream,
    ) -> str:
        url = (self.base_url or "http://localhost:11434") + "/api/chat"
        body = self._ollama_body(messages, system, stream=False, json_mode=json_mode)
        resp = await self._http.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        tokens_in = data.get("prompt_eval_count", 0)
        tokens_out = data.get("eval_count", 0)
        logger.info("Ollama tokens: in=%d out=%d model=%s", tokens_in, tokens_out, self.model)
        return content

    async def _ollama_stream(
        self, messages, system, max_tokens, json_mode,
    ) -> AsyncGenerator[str, None]:
        url = (self.base_url or "http://localhost:11434") + "/api/chat"
        body = self._ollama_body(messages, system, stream=True, json_mode=json_mode)
        async with self._http.stream("POST", url, json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.strip():
                    chunk = json.loads(line)
                    text = chunk.get("message", {}).get("content", "")
                    if text:
                        yield text

    # ------------------------------------------------------------------
    # Redis cache helpers
    # ------------------------------------------------------------------

    async def _get_redis(self) -> Optional[aioredis.Redis]:
        try:
            return aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        except Exception:
            return None

    async def _check_cache(
        self, messages: list[dict[str, str]], system: str | None,
    ) -> str | None:
        r = await self._get_redis()
        if r is None:
            return None
        try:
            key = _cache_key(self.provider, self.model, messages, system)
            val = await r.get(key)
            return val
        except Exception:
            return None
        finally:
            await r.aclose()

    async def _set_cache(
        self, messages: list[dict[str, str]], system: str | None, result: str,
    ) -> None:
        r = await self._get_redis()
        if r is None:
            return
        try:
            key = _cache_key(self.provider, self.model, messages, system)
            await r.setex(key, _CACHE_TTL, result)
        except Exception:
            pass
        finally:
            await r.aclose()


async def get_ai_client_from_settings(db_session) -> AIClient | None:
    """Build an AIClient from the AiSettings stored in the database.

    Returns None if AI is not enabled or not configured.
    """
    from api.models.ai import AiSettings
    from api.core.encryption import decrypt_value

    result = await db_session.execute(
        __import__("sqlalchemy").select(AiSettings).limit(1)
    )
    ai_settings = result.scalar_one_or_none()
    if ai_settings is None or not ai_settings.is_enabled:
        return None

    api_key = None
    if ai_settings.api_key_encrypted:
        try:
            api_key = decrypt_value(ai_settings.api_key_encrypted, settings.SECRET_KEY)
        except Exception:
            logger.error("Failed to decrypt AI API key")
            return None

    return AIClient(
        provider=ai_settings.provider,
        api_key=api_key,
        model=ai_settings.model,
        base_url=ai_settings.base_url,
    )
