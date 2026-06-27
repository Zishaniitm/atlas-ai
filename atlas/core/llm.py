"""
LLM client abstraction — GPT-4o, Claude Sonnet, Ollama.
SRS: NFR-026 (provider swappable via config), NFR-015 (keys from keychain)
"""
from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator
from atlas.core.config import get_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class LLMClient(ABC):
    @abstractmethod
    async def complete(self, messages: list[dict[str, str]],
                       tools: list[dict[str, Any]] | None = None) -> dict[str, Any]: ...
    @abstractmethod
    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        yield ""  # pragma: no cover


class OpenAIClient(LLMClient):
    def __init__(self, api_key: str, model: str = "gpt-4o") -> None:
        self._key, self._model = api_key, model

    async def complete(self, messages: list[dict[str, str]],
                       tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        from openai import AsyncOpenAI  # type: ignore[import]
        c = AsyncOpenAI(api_key=self._key)
        cfg = get_config().llm
        kw: dict[str, Any] = {"model": self._model, "messages": messages,
                               "temperature": cfg.temperature, "max_tokens": cfg.max_tokens}
        if tools:
            kw["tools"] = tools; kw["tool_choice"] = "auto"
        try:
            r = await c.chat.completions.create(**kw)
            msg = r.choices[0].message
            return {"content": msg.content or "", "tool_calls": msg.tool_calls}
        except Exception as exc:
            logger.error("openai_failed", exc_info=exc)
            raise RuntimeError("GPT-4o request failed.") from exc

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        from openai import AsyncOpenAI  # type: ignore[import]
        c = AsyncOpenAI(api_key=self._key)
        cfg = get_config().llm
        try:
            async with c.chat.completions.stream(model=self._model, messages=messages,
                                                  temperature=cfg.temperature,
                                                  max_tokens=cfg.max_tokens) as s:
                async for ev in s:
                    delta = ev.choices[0].delta.content if ev.choices else None
                    if delta:
                        yield delta
        except Exception as exc:
            logger.error("openai_stream_failed", exc_info=exc)
            raise RuntimeError("GPT-4o stream failed.") from exc


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        self._key, self._model = api_key, model

    async def complete(self, messages: list[dict[str, str]],
                       tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        from anthropic import AsyncAnthropic  # type: ignore[import]
        c = AsyncAnthropic(api_key=self._key)
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        try:
            r = await c.messages.create(model=self._model, system=system,
                                        messages=user_msgs,
                                        max_tokens=get_config().llm.max_tokens)
            return {"content": r.content[0].text if r.content else "", "tool_calls": None}
        except Exception as exc:
            logger.error("anthropic_failed", exc_info=exc)
            raise RuntimeError("Claude request failed.") from exc

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        from anthropic import AsyncAnthropic  # type: ignore[import]
        c = AsyncAnthropic(api_key=self._key)
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        async with c.messages.stream(model=self._model, system=system,
                                     messages=user_msgs,
                                     max_tokens=get_config().llm.max_tokens) as s:
            async for text in s.text_stream:
                yield text


class OllamaClient(LLMClient):
    def __init__(self, model: str = "mistral") -> None:
        self._model = model
        self._base  = "http://127.0.0.1:11434"

    async def complete(self, messages: list[dict[str, str]],
                       tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        import httpx  # type: ignore[import]
        try:
            async with httpx.AsyncClient(timeout=60.0) as c:
                r = await c.post(f"{self._base}/api/chat",
                                 json={"model": self._model, "messages": messages, "stream": False})
                r.raise_for_status()
                return {"content": r.json().get("message", {}).get("content", ""),
                        "tool_calls": None}
        except Exception as exc:
            logger.error("ollama_failed", exc_info=exc)
            raise RuntimeError("Ollama request failed. Is the Ollama daemon running?") from exc

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        import httpx, json  # type: ignore[import]
        async with httpx.AsyncClient(timeout=120.0) as c:
            async with c.stream("POST", f"{self._base}/api/chat",
                                 json={"model": self._model, "messages": messages, "stream": True}) as r:
                async for line in r.aiter_lines():
                    if line:
                        token = json.loads(line).get("message", {}).get("content", "")
                        if token:
                            yield token


def build_llm_client(api_key: str | None = None) -> LLMClient:
    """SRS: NFR-026 (swappable), NFR-015 (api_key from keychain)"""
    cfg = get_config().llm
    if cfg.provider == "openai":
        if not api_key:
            raise RuntimeError("OpenAI API key not in keychain. Run 'atlas setup'.")
        return OpenAIClient(api_key=api_key, model=cfg.model)
    if cfg.provider == "anthropic":
        if not api_key:
            raise RuntimeError("Anthropic API key not in keychain.")
        return AnthropicClient(api_key=api_key, model=cfg.model)
    if cfg.provider == "ollama":
        return OllamaClient(model=cfg.model)
    raise ValueError(f"Unknown LLM provider: '{cfg.provider}'")
