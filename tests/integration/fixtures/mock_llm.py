"""
Mock LLM for integration tests — never makes a real API call.
SRS: Section 11.3, Section 11.2 (CI must not need real API keys)
"""
from __future__ import annotations
from typing import Any, AsyncIterator
from atlas.core.llm import LLMClient

_CANNED: dict[str, str] = {
    "hello":           "Hello! I am ATLAS. How can I help you today?",
    "what time is it": "Let me check the current time for you.",
    "search for cats": "Searching the web for cats.",
    "open calculator": "Opening the calculator application.",
    "default":         "I understood your request and am processing it.",
}


class MockLLMClient(LLMClient):
    """
    Returns pre-recorded responses for known inputs.
    Optionally forces a tool call for testing Orchestrator dispatch.
    SRS: Section 11.3
    """

    def __init__(self, force_tool_call: dict[str, Any] | None = None) -> None:
        self.force_tool_call = force_tool_call
        self.call_count      = 0
        self.last_messages: list[dict[str, str]] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.call_count += 1
        self.last_messages = messages
        if self.force_tool_call:
            return {"content": "", "tool_calls": [self.force_tool_call]}
        last = next(
            (m["content"].lower() for m in reversed(messages) if m["role"] == "user"), ""
        )
        content = _CANNED.get(last, _CANNED["default"])
        return {"content": content, "tool_calls": None}

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        result = await self.complete(messages)
        for word in result.get("content", "").split():
            yield word + " "

    async def process(self, text: str) -> str:
        """Convenience wrapper matching the pipeline's llm_handler interface."""
        result = await self.complete([{"role": "user", "content": text}])
        return result.get("content", "")


class MockLLMAlwaysFails(LLMClient):
    """Tests error-handling paths. SRS: NFR-033"""
    async def complete(self, messages: list[dict[str, str]],
                       tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        raise RuntimeError("MockLLMAlwaysFails: intentional failure")

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        raise RuntimeError("MockLLMAlwaysFails: intentional stream failure")
        yield ""  # pragma: no cover
