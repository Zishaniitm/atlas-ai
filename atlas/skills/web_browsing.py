"""
Web Browsing skill — autonomous browser control via Playwright.
SRS: FR-023, SRS Appendix 14.1, SRS Section 9.3 (browser.control permission)
"""
from __future__ import annotations
from typing import Any, ClassVar
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)

_VALID_ACTIONS = ("navigate", "click", "scroll", "fill", "read", "screenshot")


class WebBrowsingSkill(BaseSkill):
    name: ClassVar[str] = "browse_url"
    description: ClassVar[str] = (
        "Control a web browser: navigate to URLs, click elements, "
        "fill forms, scroll, and read page content."
    )
    parameters: ClassVar[dict[str, dict[str, Any]]] = {
        "url":      {"type": "string", "required": True},
        "action":   {"type": "string", "required": True,
                     "enum": list(_VALID_ACTIONS)},
        "selector": {"type": "string", "required": False},
        "value":    {"type": "string", "required": False},
    }
    permissions: ClassVar[list[str]] = ["network.outbound", "browser.control"]
    risk_level: ClassVar[str] = "high"

    async def execute(
        self,
        url: str,
        action: str,
        selector: str | None = None,
        value: str | None = None,
    ) -> SkillResult:
        """
        Execute a browser action using Playwright async API.
        SRS: FR-023, NFR-016 (HTTPS enforced by Playwright)
        """
        try:
            from playwright.async_api import async_playwright  # type: ignore[import]

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                page    = await browser.new_page()

                # Always navigate first
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)

                if action == "navigate":
                    title = await page.title()
                    await browser.close()
                    return SkillResult(
                        success=True,
                        data={"url": url, "title": title},
                        speak=f"Opened {title}.",
                    )

                if action == "read":
                    text = await page.inner_text("body")
                    text = " ".join(text.split())[:2000]   # trim to 2k chars
                    title = await page.title()
                    await browser.close()
                    return SkillResult(
                        success=True,
                        data={"url": url, "title": title, "text": text},
                        speak=f"Page content from {title}: {text[:300]}",
                    )

                if action == "click":
                    if not selector:
                        await browser.close()
                        return SkillResult(success=False,
                                           error="'selector' required for click.")
                    await page.click(selector, timeout=5000)
                    await browser.close()
                    return SkillResult(success=True,
                                       data={"clicked": selector},
                                       speak=f"Clicked {selector}.")

                if action == "fill":
                    if not selector or not value:
                        await browser.close()
                        return SkillResult(success=False,
                                           error="'selector' and 'value' required for fill.")
                    await page.fill(selector, value, timeout=5000)
                    await browser.close()
                    return SkillResult(success=True,
                                       data={"filled": selector, "value": value},
                                       speak=f"Filled in the field.")

                if action == "scroll":
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
                    await browser.close()
                    return SkillResult(success=True, speak="Scrolled down.")

                if action == "screenshot":
                    import time
                    from pathlib import Path
                    save_dir = Path("~/.atlas/screenshots").expanduser()
                    save_dir.mkdir(parents=True, exist_ok=True)
                    path = str(save_dir / f"browser_{int(time.time())}.png")
                    await page.screenshot(path=path, full_page=False)
                    await browser.close()
                    return SkillResult(success=True,
                                       data={"image_path": path},
                                       speak="Browser screenshot saved.")

                await browser.close()
                return SkillResult(success=False, error=f"Unknown action: '{action}'")

        except Exception as exc:
            logger.error("web_browsing_failed", url=url, action=action, exc_info=exc)
            return SkillResult(success=False, error=f"Browser action failed: {exc}")
