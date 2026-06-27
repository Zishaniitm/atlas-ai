"""
ATLAS async event bus. SRS: SRS Section 4.2.4, NFR-032 (fault isolation)
"""
from __future__ import annotations
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any, Callable, Coroutine

from atlas.utils.logging import get_logger
logger = get_logger(__name__)

AsyncHandler = Callable[["AtlasEvent"], Coroutine[Any, Any, None]]


class EventType(StrEnum):
    WAKE_WORD_DETECTED   = auto()
    STT_TRANSCRIPT_READY = auto()
    TTS_STARTED          = auto()
    TTS_FINISHED         = auto()
    AUDIO_LEVEL_UPDATE   = auto()
    LLM_TOKEN_RECEIVED   = auto()
    LLM_RESPONSE_READY   = auto()
    TOOL_CALL_STARTED    = auto()
    TOOL_CALL_FINISHED   = auto()
    AUTH_SUCCESS         = auto()
    AUTH_FAILED          = auto()
    AUTH_LOCKED          = auto()
    SESSION_LOCKED       = auto()
    MEMORY_WRITE_REQUEST = auto()   # BUG-09: fired AFTER TTS
    MEMORY_WRITE_DONE    = auto()
    ATLAS_READY          = auto()
    ATLAS_SHUTDOWN       = auto()
    CONFIG_RELOADED      = auto()
    NOTIFICATION_REQUEST = auto()


@dataclass
class AtlasEvent:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"


class EventBus:
    """Async pub/sub bus. SRS: NFR-032 (one crashed handler never stops others)"""

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[AsyncHandler]] = defaultdict(list)

    def subscribe(self, event_type: EventType, handler: AsyncHandler) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: AsyncHandler) -> None:
        try:
            self._handlers[event_type].remove(handler)
        except ValueError:
            logger.warning("unsubscribe_not_found", event=event_type)

    async def emit(self, event: AtlasEvent) -> None:
        handlers = list(self._handlers.get(event.type, []))
        if not handlers:
            return
        results = await asyncio.gather(*[h(event) for h in handlers], return_exceptions=True)
        for h, r in zip(handlers, results):
            if isinstance(r, BaseException):
                logger.error("handler_error", event=event.type,
                             handler=h.__qualname__, exc_info=r)

    def emit_nowait(self, event: AtlasEvent) -> None:
        """Fire-and-forget from sync code. SRS: BUG-09"""
        asyncio.get_event_loop().create_task(self.emit(event))


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
