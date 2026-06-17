"""
Mock LLM client for integration tests.

Returns pre-recorded canned responses for known prompts.
Never makes a real API call — tests are fully offline.

SRS: SRS Section 11.3 (mock LLM for integration tests),
     SRS Section 11.2 (CI must not need real API keys)
"""

from __future__ import annotations

from typing import AsyncIterator

from atlas.core.llm import LLMClient


# Pre-recorded responses for known inputs
_CANNED_RESPONSES: dict[str, str] = {
    "hello":           "Hello! I am ATLAS. How can I help you today?",
    "what time is it": "I'll check the current time for you.",
    "search for cats": "Searching the web for cats.",
    "open calculator": "Opening the calculator application.",
    "default":         "I understood your request and I'm processing it.",
}


class MockLLMClient(LLMClient):
    """
    Canned-response LLM for integration testing.

    Matches the last user message against known prompts.
    Returns the canned response or a default if no match.

    SRS: SRS 11.3 (never commits real biometric or API data)
    """

    def __init__(self, force_tool_call: dict | None = None) -> None:
        """
        Args:
            force_tool_call: If set, always return this as a tool call.
                             Used to test skill dispatch in the Orchestrator.
                             Example: {"name": "get_weather", "args": {"city": "Mumbai"}}
        """
        self._force_tool_call = force_tool_call
        self.call_count = 0
        self.last_messages: list[dict] = []

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> dict:
        """
        Return a canned response or forced tool call.

        Args:
            messages: Conversation history.
            tools: Available tools (ignored by mock).

        Returns:
            Response dict with 'content' and 'tool_calls'.
        """
        self.call_count += 1
        self.last_messages = messages

        if self._force_tool_call:
            return {
                "content": "",
                "tool_calls": [self._force_tool_call],
            }

        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user = msg.get("content", "").lower()
                break

        response = _CANNED_RESPONSES.get(last_user, _CANNED_RESPONSES["default"])
        return {"content": response, "tool_calls": None}

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """
        Stream the canned response token by token (word by word).

        SRS: FR-009 (token streaming tested even in mock)
        """
        result = await self.complete(messages)
        content: str = result.get("content", "")
        for word in content.split():
            yield word + " "


class MockLLMAlwaysFails(LLMClient):
    """
    LLM client that always raises — tests error handling paths.

    SRS: NFR-033 (crashed skill must not crash ATLAS process)
    """

    async def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        raise RuntimeError("MockLLMAlwaysFails: intentional failure for testing")

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        raise RuntimeError("MockLLMAlwaysFails: intentional stream failure")
        yield ""  # pragma: no cover
