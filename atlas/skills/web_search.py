"""Web Search skill — DuckDuckGo (no API key needed). SRS: FR-022"""
from __future__ import annotations
from typing import Any, ClassVar
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class WebSearchSkill(BaseSkill):
    name: ClassVar[str] = "search_web"
    description: ClassVar[str] = (
        "Search the web and return summarised top results with titles and URLs."
    )
    parameters: ClassVar[dict[str, dict[str, Any]]] = {
        "query":       {"type": "string",  "required": True},
        "num_results": {"type": "integer", "required": False, "default": 5},
    }
    permissions: ClassVar[list[str]] = ["network.outbound"]
    risk_level: ClassVar[str] = "low"

    async def execute(self, query: str, num_results: int = 5) -> SkillResult:
        """
        Search DuckDuckGo Instant Answer API and return top results.
        SRS: FR-022, SRS Appendix 14.1
        """
        try:
            import httpx  # type: ignore[import]
            num_results = max(1, min(num_results, 10))

            # DuckDuckGo Instant Answer API — free, no key required
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_redirect": "1", "no_html": "1"},
                )
                resp.raise_for_status()
                data = resp.json()

            results: list[dict[str, str]] = []

            # Abstract answer (instant answer)
            if data.get("Abstract"):
                results.append({
                    "title": data.get("Heading", "Answer"),
                    "url":   data.get("AbstractURL", ""),
                    "snippet": data.get("Abstract", ""),
                })

            # Related topics
            for topic in data.get("RelatedTopics", []):
                if len(results) >= num_results:
                    break
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({
                        "title":   topic.get("Text", "")[:80],
                        "url":     topic.get("FirstURL", ""),
                        "snippet": topic.get("Text", ""),
                    })

            if not results:
                return SkillResult(
                    success=True,
                    data={"results": [], "query": query},
                    speak=f"I couldn't find specific results for '{query}'. Try rephrasing.",
                )

            speak_summary = f"Here are the top results for '{query}'. " + results[0]["snippet"][:200]
            return SkillResult(
                success=True,
                data={"results": results, "query": query, "count": len(results)},
                speak=speak_summary,
            )

        except Exception as exc:
            logger.error("web_search_failed", query=query, exc_info=exc)
            return SkillResult(success=False, error=f"Web search failed: {exc}")
