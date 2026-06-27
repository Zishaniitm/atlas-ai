"""Screenshot + OCR skill. SRS: FR-031, SRS Appendix 14.1"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Any, ClassVar
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class ScreenshotOCRSkill(BaseSkill):
    name: ClassVar[str] = "capture_screen"
    description: ClassVar[str] = (
        "Capture the full screen or a region and optionally extract text via OCR."
    )
    parameters: ClassVar[dict[str, dict[str, Any]]] = {
        "region": {"type": "object",  "required": False},   # {x, y, width, height}
        "ocr":    {"type": "boolean", "required": False, "default": False},
    }
    permissions: ClassVar[list[str]] = ["screen.capture", "filesystem.write"]
    risk_level: ClassVar[str] = "medium"

    async def execute(
        self,
        region: dict[str, int] | None = None,
        ocr: bool = False,
    ) -> SkillResult:
        """SRS: FR-031"""
        try:
            import pyautogui  # type: ignore[import]
            from PIL import Image  # type: ignore[import]

            save_dir = Path("~/.atlas/screenshots").expanduser()
            save_dir.mkdir(parents=True, exist_ok=True)
            filename = f"screenshot_{int(time.time())}.png"
            save_path = save_dir / filename

            if region:
                x, y = region.get("x", 0), region.get("y", 0)
                w, h = region.get("width", 800), region.get("height", 600)
                img = pyautogui.screenshot(region=(x, y, w, h))
            else:
                img = pyautogui.screenshot()

            img.save(str(save_path))
            result_data: dict[str, Any] = {"image_path": str(save_path)}

            if ocr:
                import pytesseract  # type: ignore[import]
                extracted_text = pytesseract.image_to_string(img).strip()
                result_data["extracted_text"] = extracted_text
                result_data["word_count"]     = len(extracted_text.split())
                return SkillResult(
                    success=True, data=result_data,
                    speak=f"Screenshot captured. Found {result_data['word_count']} words of text.",
                )

            return SkillResult(
                success=True, data=result_data,
                speak="Screenshot saved.",
            )

        except Exception as exc:
            logger.error("screenshot_failed", exc_info=exc)
            return SkillResult(success=False, error=f"Screenshot failed: {exc}")
