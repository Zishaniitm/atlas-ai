"""
ATLAS async event bus.

Lightweight pub/sub system connecting voice pipeline, LLM brain,
memory manager, and HUD without direct imports between them.
All handlers are async coroutines; the bus dispatches concurrently.

SRS: SRS Section 4.2.4 (internal API), NFR-032 (fault isolation —
     one crashed handler must not affect others)
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any, Callable, Coroutine

from atlas.utils.logging import get_logger

logger = get_logger(__name__)

# Async handler type: receives an event, returns nothing
AsyncHandler = Callable[["AtlasEvent"], Coroutine[Any, Any, None]]


class EventType(StrEnum):
    """All valid ATLAS event types. Add new events here only."""

    # Voice pipeline
    WAKE_WORD_DETECTED   = auto()
    STT_TRANSCRIPT_READY = auto()
    TTS_STARTED          = auto()
    TTS_FINISHED         = auto()
    AUDIO_LEVEL_UPDATE   = auto()

    # LLM / orchestrator
    LLM_TOKEN_RECEIVED   = auto()
    LLM_RESPONSE_READY   = auto()
    TOOL_CALL_STARTED    = auto()
    TOOL_CALL_FINISHED   = auto()

    # Auth
    AUTH_SUCCESS         = auto()
    AUTH_FAILED          = auto()
    AUTH_LOCKED          = auto()
    SESSION_LOCKED       = auto()

    # Memory (BUG-09: writes fired AFTER response, never blocking it)
    MEMORY_WRITE_REQUEST = auto()
    MEMORY_WRITE_DONE    = auto()

    # System
    ATLAS_READY          = auto()
    ATLAS_SHUTDOWN       = auto()
    CONFIG_RELOADED      = auto()
    NOTIFICATION_REQUEST = auto()


@dataclass
class AtlasEvent:
    """
    Immutable event payload passed to all subscribers.

    SRS: Section 4.2 (component communication via events)

    Attributes:
        type: The event type from EventType enum.
        data: Arbitrary payload dict — keep values serialisable.
        source: Name of the module that emitted the event.
    """

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"


class EventBus:
    """
    Central async pub/sub event bus for ATLAS.

    All ATLAS modules communicate through this bus rather than
    importing each other directly, keeping layers decoupled.

    SRS: NFR-032 (fault isolation), SRS Section 4.1 (layer decoupling)

    Usage:
        bus = get_event_bus()
        bus.subscribe(EventType.STT_TRANSCRIPT_READY, my_handler)
        await bus.emit(AtlasEvent(EventType.STT_TRANSCRIPT_READY, {"text": "hello"}))
    """

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[AsyncHandler]] = defaultdict(list)
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: EventType, handler: AsyncHandler) -> None:
        """
        Register an async handler for an event type.

        SRS: NFR-025 (skills can subscribe without core code changes)

        Args:
            event_type: The event to listen for.
            handler: Async coroutine called when the event fires.
        """
        self._handlers[event_type].append(handler)
        logger.debug("event_subscribed", event=event_type, handler=handler.__qualname__)

    def unsubscribe(self, event_type: EventType, handler: AsyncHandler) -> None:
        """
        Remove a previously registered handler.

        Args:
            event_type: The event type to unsubscribe from.
            handler: The exact handler function to remove.
        """
        handlers = self._handlers[event_type]
        try:
            handlers.remove(handler)
        except ValueError:
            logger.warning("unsubscribe_handler_not_found", event=event_type)

    async def emit(self, event: AtlasEvent) -> None:
        """
        Emit an event to all registered subscribers concurrently.

        A handler that raises an exception is logged but does NOT
        prevent other handlers from running (NFR-032 — fault isolation).

        SRS: NFR-032, BUG-09 (MEMORY_WRITE_REQUEST fired after TTS, never before)

        Args:
            event: The event to dispatch.
        """
        handlers = list(self._handlers.get(event.type, []))
        if not handlers:
            return

        logger.debug("event_emitted", event=event.type, source=event.source)

        results = await asyncio.gather(
            *[h(event) for h in handlers],
            return_exceptions=True,
        )

        for handler, result in zip(handlers, results):
            if isinstance(result, BaseException):
                logger.error(
                    "event_handler_error",
                    event=event.type,
                    handler=handler.__qualname__,
                    exc_info=result,
                )

    def emit_nowait(self, event: AtlasEvent) -> None:
        """
        Schedule an event emission without awaiting it.

        Use for fire-and-forget emissions from sync code (e.g. signal handlers).
        Requires a running event loop.

        SRS: BUG-09 — memory writes use this after TTS completes.

        Args:
            event: The event to dispatch asynchronously.
        """
        loop = asyncio.get_event_loop()
        loop.create_task(self.emit(event))


# ── Module-level singleton ────────────────────────────────────

_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """
    Return the global EventBus singleton.

    Creates the bus on first call. Safe to call from any module.

    SRS: Section 4.2.4
    """
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
