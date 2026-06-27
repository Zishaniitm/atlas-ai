"""Date & Time skill. SRS: FR-029, SRS Appendix 14.1"""
from __future__ import annotations
import asyncio
from datetime import datetime
from typing import Any, ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from atlas.core.events import AtlasEvent, EventType, get_event_bus
from atlas.skills.base import BaseSkill, SkillResult
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class DateTimeSkill(BaseSkill):
    name: ClassVar[str] = "get_datetime"
    description: ClassVar[str] = (
        "Get current date/time in any timezone, or set an alarm/countdown timer."
    )
    parameters: ClassVar[dict[str, dict[str, Any]]] = {
        "timezone":          {"type": "string",  "required": False},
        "set_alarm":         {"type": "boolean", "required": False, "default": False},
        "alarm_in_seconds":  {"type": "integer", "required": False},
    }
    permissions: ClassVar[list[str]] = []
    risk_level: ClassVar[str] = "low"

    async def execute(
        self,
        timezone: str | None = None,
        set_alarm: bool = False,
        alarm_in_seconds: int | None = None,
    ) -> SkillResult:
        """SRS: FR-029"""
        if set_alarm:
            return self._set_alarm(alarm_in_seconds)
        return self._get_datetime(timezone)

    def _get_datetime(self, timezone: str | None) -> SkillResult:
        try:
            tz = ZoneInfo(timezone) if timezone else None
        except ZoneInfoNotFoundError:
            return SkillResult(success=False, error=f"Unknown timezone: '{timezone}'")
        now = datetime.now(tz)
        formatted = now.strftime("%A, %B %d, %Y at %I:%M %p")
        return SkillResult(
            success=True,
            data={"iso": now.isoformat(), "timezone": timezone or "local"},
            speak=f"It's {formatted}" + (f" in {timezone}." if timezone else "."),
        )

    def _set_alarm(self, alarm_in_seconds: int | None) -> SkillResult:
        if not alarm_in_seconds or alarm_in_seconds <= 0:
            return SkillResult(success=False,
                               error="Please provide a positive number of seconds.")
        alarm_id = f"alarm_{int(datetime.now().timestamp())}"
        asyncio.create_task(self._fire_later(alarm_id, alarm_in_seconds))
        mins, secs = divmod(alarm_in_seconds, 60)
        human = f"{mins}m {secs}s" if mins else f"{secs}s"
        return SkillResult(success=True,
                           data={"alarm_id": alarm_id, "fires_in": alarm_in_seconds},
                           speak=f"Alarm set for {human} from now.")

    async def _fire_later(self, alarm_id: str, delay: int) -> None:
        """SRS: FR-098 (notification on alarm fire)"""
        await asyncio.sleep(delay)
        get_event_bus().emit_nowait(AtlasEvent(
            EventType.NOTIFICATION_REQUEST,
            data={"title": "ATLAS Alarm", "body": f"Alarm {alarm_id} is going off!"},
            source="datetime_skill",
        ))
        logger.info("alarm_fired", alarm_id=alarm_id)
