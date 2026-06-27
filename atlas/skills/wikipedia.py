"""Wikipedia skill. SRS: FR-027, SRS Appendix 14.1"""
from __future__ import annotations
from typing import Any, ClassVar
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class WikipediaSkill(BaseSkill):
    name: ClassVar[str] = "search_wikipedia"
    description: ClassVar[str] = "Retrieve and summarise a Wikipedia article by topic."
    parameters: ClassVar[dict[str, dict[str, Any]]] = {
        "query":     {"type": "string",  "required": True},
        "sentences": {"type": "integer", "required": False, "default": 3},
    }
    permissions: ClassVar[list[str]] = ["network.outbound"]
    risk_level: ClassVar[str] = "low"

    async def execute(self, query: str, sentences: int = 3) -> SkillResult:
        """SRS: FR-027"""
        try:
            import asyncio
            import httpx  # type: ignore[import]

            sentences = max(1, min(sentences, 10))

            async with httpx.AsyncClient(timeout=10.0) as client:
                # Step 1: search for page title
                search_resp = await client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "query", "list": "search",
                        "srsearch": query, "format": "json", "srlimit": 1,
                    },
                )
                search_resp.raise_for_status()
                search_data = search_resp.json()
                search_results = search_data.get("query", {}).get("search", [])

                if not search_results:
                    return SkillResult(
                        success=False,
                        error=f"No Wikipedia article found for '{query}'.",
                    )

                page_title = search_results[0]["title"]

                # Step 2: fetch extract (plain text summary)
                extract_resp = await client.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "query", "prop": "extracts",
                        "exintro": True, "explaintext": True,
                        "redirects": True, "titles": page_title,
                        "format": "json",
                    },
                )
                extract_resp.raise_for_status()
                extract_data = extract_resp.json()

            pages = extract_data.get("query", {}).get("pages", {})
            page = next(iter(pages.values()))
            extract: str = page.get("extract", "")

            if not extract:
                return SkillResult(success=False,
                                   error=f"Could not get content for '{page_title}'.")

            # Trim to requested sentence count
            all_sentences = [s.strip() for s in extract.split(".") if s.strip()]
            summary = ". ".join(all_sentences[:sentences]) + "."
            page_url = f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}"

            return SkillResult(
                success=True,
                data={"summary": summary, "title": page_title, "url": page_url},
                speak=summary,
            )

        except Exception as exc:
            logger.error("wikipedia_failed", query=query, exc_info=exc)
            return SkillResult(success=False, error=f"Wikipedia lookup failed: {exc}")
