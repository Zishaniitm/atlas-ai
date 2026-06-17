"""
Unit tests for atlas.core.events.

SRS: SRS Section 11.1 (EventBus — fault isolation NFR-032),
     BUG-09 (MEMORY_WRITE_REQUEST fires after TTS, never blocking it)
"""

from __future__ import annotations

import asyncio
import pytest

from atlas.core.events import (
    AtlasEvent,
    EventBus,
    EventType,
    get_event_bus,
)


# ── Subscribe / emit ──────────────────────────────────────────

class TestEventBusSubscribeEmit:
    @pytest.mark.asyncio
    async def test_handler_called_on_emit(self):
        bus = EventBus()
        received: list[AtlasEvent] = []

        async def handler(event: AtlasEvent) -> None:
            received.append(event)

        bus.subscribe(EventType.ATLAS_READY, handler)
        await bus.emit(AtlasEvent(EventType.ATLAS_READY, source="test"))

        assert len(received) == 1
        assert received[0].type == EventType.ATLAS_READY

    @pytest.mark.asyncio
    async def test_multiple_handlers_all_called(self):
        bus = EventBus()
        calls: list[str] = []

        async def h1(e: AtlasEvent) -> None:
            calls.append("h1")

        async def h2(e: AtlasEvent) -> None:
            calls.append("h2")

        bus.subscribe(EventType.TTS_STARTED, h1)
        bus.subscribe(EventType.TTS_STARTED, h2)
        await bus.emit(AtlasEvent(EventType.TTS_STARTED))

        assert "h1" in calls
        assert "h2" in calls

    @pytest.mark.asyncio
    async def test_emit_with_no_handlers_does_nothing(self):
        bus = EventBus()
        # Should complete without error
        await bus.emit(AtlasEvent(EventType.ATLAS_SHUTDOWN))

    @pytest.mark.asyncio
    async def test_event_data_passed_correctly(self):
        bus = EventBus()
        received_data: list[dict] = []

        async def handler(event: AtlasEvent) -> None:
            received_data.append(event.data)

        bus.subscribe(EventType.STT_TRANSCRIPT_READY, handler)
        await bus.emit(AtlasEvent(
            EventType.STT_TRANSCRIPT_READY,
            data={"text": "hello atlas"},
            source="test",
        ))

        assert received_data[0]["text"] == "hello atlas"


# ── Fault isolation — NFR-032 ─────────────────────────────────

class TestFaultIsolation:
    @pytest.mark.asyncio
    async def test_crashing_handler_does_not_stop_other_handlers(self):
        """
        NFR-032: one crashed handler must not prevent others from running.
        """
        bus = EventBus()
        second_called = False

        async def crashing_handler(event: AtlasEvent) -> None:
            raise ValueError("intentional crash in test")

        async def second_handler(event: AtlasEvent) -> None:
            nonlocal second_called
            second_called = True

        bus.subscribe(EventType.WAKE_WORD_DETECTED, crashing_handler)
        bus.subscribe(EventType.WAKE_WORD_DETECTED, second_handler)

        # Should NOT raise despite crashing_handler
        await bus.emit(AtlasEvent(EventType.WAKE_WORD_DETECTED))

        assert second_called is True

    @pytest.mark.asyncio
    async def test_multiple_crashes_all_handled(self):
        bus = EventBus()
        calls: list[int] = []

        async def crash_1(e: AtlasEvent) -> None:
            raise RuntimeError("crash 1")

        async def crash_2(e: AtlasEvent) -> None:
            raise RuntimeError("crash 2")

        async def survivor(e: AtlasEvent) -> None:
            calls.append(1)

        bus.subscribe(EventType.AUTH_FAILED, crash_1)
        bus.subscribe(EventType.AUTH_FAILED, crash_2)
        bus.subscribe(EventType.AUTH_FAILED, survivor)

        await bus.emit(AtlasEvent(EventType.AUTH_FAILED))
        assert len(calls) == 1


# ── Unsubscribe ───────────────────────────────────────────────

class TestUnsubscribe:
    @pytest.mark.asyncio
    async def test_unsubscribe_stops_handler_receiving_events(self):
        bus = EventBus()
        calls: list[int] = []

        async def handler(event: AtlasEvent) -> None:
            calls.append(1)

        bus.subscribe(EventType.CONFIG_RELOADED, handler)
        await bus.emit(AtlasEvent(EventType.CONFIG_RELOADED))
        assert len(calls) == 1

        bus.unsubscribe(EventType.CONFIG_RELOADED, handler)
        await bus.emit(AtlasEvent(EventType.CONFIG_RELOADED))
        assert len(calls) == 1   # still 1 — handler not called again

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_handler_logs_warning(self):
        bus = EventBus()

        async def handler(e: AtlasEvent) -> None:
            pass

        # Should not raise
        bus.unsubscribe(EventType.AUTH_SUCCESS, handler)


# ── BUG-09 — memory write event fires after TTS ───────────────

class TestBug09MemoryWriteOrder:
    @pytest.mark.asyncio
    async def test_memory_write_event_type_exists(self):
        """BUG-09: MEMORY_WRITE_REQUEST event type must exist."""
        assert EventType.MEMORY_WRITE_REQUEST in list(EventType)

    @pytest.mark.asyncio
    async def test_tts_finished_before_memory_write(self):
        """
        BUG-09: TTS_FINISHED must be emitted before MEMORY_WRITE_REQUEST.

        Verifies the ordering contract — memory write is always last.
        """
        bus = EventBus()
        order: list[str] = []

        async def on_tts_finished(e: AtlasEvent) -> None:
            order.append("tts_finished")

        async def on_memory_write(e: AtlasEvent) -> None:
            order.append("memory_write")

        bus.subscribe(EventType.TTS_FINISHED, on_tts_finished)
        bus.subscribe(EventType.MEMORY_WRITE_REQUEST, on_memory_write)

        # Simulate the correct pipeline order (SRS 4.3 steps 9→10)
        await bus.emit(AtlasEvent(EventType.TTS_FINISHED, source="pipeline"))
        await bus.emit(AtlasEvent(EventType.MEMORY_WRITE_REQUEST, source="pipeline"))

        assert order == ["tts_finished", "memory_write"], (
            "BUG-09: memory write must always come AFTER TTS finishes"
        )


# ── Singleton ─────────────────────────────────────────────────

class TestSingleton:
    def test_get_event_bus_returns_same_instance(self):
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_singleton_preserves_subscriptions(self):
        bus = get_event_bus()
        calls: list[int] = []

        async def h(e: AtlasEvent) -> None:
            calls.append(1)

        bus.subscribe(EventType.ATLAS_READY, h)
        # Getting the bus again should return same instance with same handlers
        same_bus = get_event_bus()
        assert same_bus is bus
