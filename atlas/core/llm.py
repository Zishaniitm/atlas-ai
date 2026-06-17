"""
LLM client abstraction for ATLAS.

Wraps GPT-4o, Claude Sonnet, and Ollama behind one interface.
Provider is config-switchable — no code change needed (NFR-026).
API keys come from OS keychain only (NFR-015).

SRS: FR-113–115 (skill chaining, error handling, iteration cap),
     NFR-026 (provider swappable via config), NFR-015 (keys from keychain),
     NFR-016 (TLS enforced by SDK)
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from atlas.core.config import get_config
from atlas.core.events import AtlasEvent, EventType, get_event_bus
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


# ── Abstract interface ────────────────────────────────────────

class LLMClient(ABC):
    """
    Base class all LLM provider clients implement.

    SRS: NFR-026 (providers swappable — all share this interface)
    """

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Send messages and return the model's response dict.

        SRS: FR-113 (tool-calling for skill chaining)

        Args:
            messages: OpenAI-format message list.
            tools: LangChain-format tool schemas (optional).

        Returns:
            Dict with keys: 'content' (str), 'tool_calls' (list | None).
        """

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        """
        Stream response tokens.

        SRS: FR-009 (token streaming to HUD via WebSocket)
        """
        yield ""  # pragma: no cover


# ── OpenAI GPT-4o ────────────────────────────────────────────

class OpenAIClient(LLMClient):
    """
    GPT-4o client via openai SDK.

    SRS: NFR-015 (API key from keychain), NFR-016 (HTTPS enforced by SDK),
         NFR-026 (swappable)
    """

    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        self._model = model
        self._api_key = api_key

    async def complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Call GPT-4o chat completions API.

        SRS: FR-113 (tool-calls returned for skill dispatch)

        Raises:
            RuntimeError: On API failure after logging.
        """
        from openai import AsyncOpenAI  # type: ignore[import]
        client = AsyncOpenAI(api_key=self._api_key)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": get_config().llm.temperature,
            "max_tokens": get_config().llm.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            resp = await client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message
            return {
                "content": msg.content or "",
                "tool_calls": msg.tool_calls,
            }
        except Exception as exc:
            logger.error("openai_complete_failed", exc_info=exc)
            raise RuntimeError("GPT-4o request failed.") from exc

    async def stream(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        """
        Stream GPT-4o tokens.

        SRS: FR-009, SRS 4.2.6 (/ws/conversation token streaming)
        """
        from openai import AsyncOpenAI  # type: ignore[import]
        client = AsyncOpenAI(api_key=self._api_key)

        try:
            async with client.chat.completions.stream(
                model=self._model,
                messages=messages,
                temperature=get_config().llm.temperature,
                max_tokens=get_config().llm.max_tokens,
            ) as stream_ctx:
                async for event in stream_ctx:
                    delta = (
                        event.choices[0].delta.content
                        if event.choices and event.choices[0].delta.content
                        else None
                    )
                    if delta:
                        yield delta
        except Exception as exc:
            logger.error("openai_stream_failed", exc_info=exc)
            raise RuntimeError("GPT-4o stream failed.") from exc


# ── Anthropic Claude ─────────────────────────────────────────

class AnthropicClient(LLMClient):
    """
    Claude Sonnet client via anthropic SDK.

    SRS: NFR-015 (API key from keychain), NFR-026 (swappable)
    """

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        self._model = model
        self._api_key = api_key

    async def complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Call Claude Messages API.

        SRS: FR-113, NFR-026

        Raises:
            RuntimeError: On API failure.
        """
        from anthropic import AsyncAnthropic  # type: ignore[import]
        client = AsyncAnthropic(api_key=self._api_key)

        system = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        user_msgs = [m for m in messages if m["role"] != "system"]

        try:
            resp = await client.messages.create(
                model=self._model,
                system=system,
                messages=user_msgs,
                max_tokens=get_config().llm.max_tokens,
            )
            content = resp.content[0].text if resp.content else ""
            return {"content": content, "tool_calls": None}
        except Exception as exc:
            logger.error("anthropic_complete_failed", exc_info=exc)
            raise RuntimeError("Claude request failed.") from exc

    async def stream(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        """Stream Claude tokens. SRS: FR-009"""
        from anthropic import AsyncAnthropic  # type: ignore[import]
        client = AsyncAnthropic(api_key=self._api_key)

        system = next(
            (m["content"] for m in messages if m["role"] == "system"), ""
        )
        user_msgs = [m for m in messages if m["role"] != "system"]

        try:
            async with client.messages.stream(
                model=self._model,
                system=system,
                messages=user_msgs,
                max_tokens=get_config().llm.max_tokens,
            ) as stream_ctx:
                async for text in stream_ctx.text_stream:
                    yield text
        except Exception as exc:
            logger.error("anthropic_stream_failed", exc_info=exc)
            raise RuntimeError("Claude stream failed.") from exc


# ── Ollama (local LLM) ────────────────────────────────────────

class OllamaClient(LLMClient):
    """
    Ollama client for local LLM inference.

    No API key needed — communicates with local Ollama daemon.

    SRS: NFR-017 (data stays local in offline mode),
         NFR-026 (swappable via config)
    """

    def __init__(self, model: str = "mistral") -> None:
        self._model = model
        self._base_url = "http://127.0.0.1:11434"

    async def complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Call local Ollama chat API.

        SRS: NFR-017, NFR-026

        Raises:
            RuntimeError: If Ollama daemon is not running.
        """
        import httpx  # type: ignore[import]

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self._base_url}/api/chat",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                content: str = data.get("message", {}).get("content", "")
                return {"content": content, "tool_calls": None}
        except Exception as exc:
            logger.error("ollama_complete_failed", exc_info=exc)
            raise RuntimeError(
                "Ollama request failed. Is the Ollama daemon running?"
            ) from exc

    async def stream(
        self,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[str]:
        """Stream Ollama tokens. SRS: FR-009"""
        import httpx  # type: ignore[import]

        payload = {"model": self._model, "messages": messages, "stream": True}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST", f"{self._base_url}/api/chat", json=payload
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line:
                            import json
                            data = json.loads(line)
                            token: str = data.get("message", {}).get("content", "")
                            if token:
                                yield token
        except Exception as exc:
            logger.error("ollama_stream_failed", exc_info=exc)
            raise RuntimeError("Ollama stream failed.") from exc


# ── Factory ───────────────────────────────────────────────────

def build_llm_client(api_key: str | None = None) -> LLMClient:
    """
    Build the LLM client from config.

    SRS: NFR-026 (provider swappable via config — no code change)
         NFR-015 (api_key passed from keychain, never read from config)

    Args:
        api_key: API key from OS keychain. None for Ollama.

    Returns:
        Configured LLMClient instance.

    Raises:
        ValueError: For unknown provider.
        RuntimeError: If cloud provider selected but no API key provided.
    """
    cfg = get_config().llm
    provider = cfg.provider

    if provider == "openai":
        if not api_key:
            raise RuntimeError(
                "OpenAI API key not found in OS keychain. "
                "Run 'atlas setup' to configure."
            )
        return OpenAIClient(api_key=api_key, model=cfg.model)

    if provider == "anthropic":
        if not api_key:
            raise RuntimeError(
                "Anthropic API key not found in OS keychain."
            )
        return AnthropicClient(api_key=api_key, model=cfg.model)

    if provider == "ollama":
        return OllamaClient(model=cfg.model)

    raise ValueError(
        f"Unknown LLM provider: '{provider}'. "
        "Valid options: openai, anthropic, ollama"
    )
