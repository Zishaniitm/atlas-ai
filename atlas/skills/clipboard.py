"""Clipboard Manager skill. SRS: FR-030, SRS Appendix 14.1"""
from __future__ import annotations
from typing import Any, ClassVar
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class ClipboardSkill(BaseSkill):
    name: ClassVar[str] = "clipboard_op"
    description: ClassVar[str] = "Read from or write text to the system clipboard."
    parameters: ClassVar[dict[str, dict[str, Any]]] = {
        "action": {"type": "string", "required": True, "enum": ["read", "write"]},
        "text":   {"type": "string", "required": False},
    }
    permissions: ClassVar[list[str]] = ["clipboard.read", "clipboard.write"]
    risk_level: ClassVar[str] = "low"

    async def execute(self, action: str, text: str | None = None) -> SkillResult:
        """SRS: FR-030"""
        try:
            import pyperclip  # type: ignore[import]
            if action == "read":
                content = pyperclip.paste()
                return SkillResult(
                    success=True,
                    data={"content": content},
                    speak=f"Clipboard contains: {content[:100]}" if content else "Clipboard is empty.",
                )
            if action == "write":
                if not text:
                    return SkillResult(success=False, error="'text' is required for write action.")
                pyperclip.copy(text)
                return SkillResult(success=True, data={"written": text},
                                   speak="Text copied to clipboard.")
            return SkillResult(success=False, error=f"Unknown action: '{action}'")
        except Exception as exc:
            logger.error("clipboard_failed", action=action, exc_info=exc)
            return SkillResult(success=False, error=f"Clipboard operation failed: {exc}")
