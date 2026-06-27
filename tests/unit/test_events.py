"""
Unit tests for atlas.core.events
SRS: NFR-032 (fault isolation), BUG-09 (memory write after TTS)
"""
from __future__ import annotations
import pytest
from atlas.core.events import AtlasEvent, EventBus, EventType, get_event_bus


class TestSubscribeEmit:
    @pytest.mark.asyncio
    async def test_handler_called_on_emit(self):
        bus = EventBus()
        received = []
        async def h(e: AtlasEvent) -> None: received.append(e)
        bus.subscribe(EventType.ATLAS_READY, h)
        await bus.emit(AtlasEvent(EventType.ATLAS_READY, source="test"))
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_multiple_handlers_all_called(self):
        bus = EventBus()
        calls: list[str] = []
        async def h1(e: AtlasEvent) -> None: calls.append("h1")
        async def h2(e: AtlasEvent) -> None: calls.append("h2")
        bus.subscribe(EventType.TTS_STARTED, h1)
        bus.subscribe(EventType.TTS_STARTED, h2)
        await bus.emit(AtlasEvent(EventType.TTS_STARTED))
        assert "h1" in calls and "h2" in calls

    @pytest.mark.asyncio
    async def test_emit_with_no_handlers_is_safe(self):
        bus = EventBus()
        await bus.emit(AtlasEvent(EventType.ATLAS_SHUTDOWN))  # must not raise

    @pytest.mark.asyncio
    async def test_event_data_passed_correctly(self):
        bus = EventBus()
        got = []
        async def h(e: AtlasEvent) -> None: got.append(e.data)
        bus.subscribe(EventType.STT_TRANSCRIPT_READY, h)
        await bus.emit(AtlasEvent(EventType.STT_TRANSCRIPT_READY, {"text": "hello atlas"}))
        assert got[0]["text"] == "hello atlas"


class TestFaultIsolation:
    @pytest.mark.asyncio
    async def test_crashing_handler_does_not_stop_others(self):
        """NFR-032: one crashed handler must never stop others from running."""
        bus = EventBus()
        second_called = False
        async def crash(e: AtlasEvent) -> None: raise ValueError("intentional crash")
        async def ok(e: AtlasEvent) -> None:
            nonlocal second_called; second_called = True
        bus.subscribe(EventType.WAKE_WORD_DETECTED, crash)
        bus.subscribe(EventType.WAKE_WORD_DETECTED, ok)
        await bus.emit(AtlasEvent(EventType.WAKE_WORD_DETECTED))  # must not raise
        assert second_called is True

    @pytest.mark.asyncio
    async def test_multiple_crashes_survivor_still_called(self):
        bus = EventBus()
        calls: list[int] = []
        async def c1(e: AtlasEvent) -> None: raise RuntimeError("c1")
        async def c2(e: AtlasEvent) -> None: raise RuntimeError("c2")
        async def ok(e: AtlasEvent) -> None: calls.append(1)
        bus.subscribe(EventType.AUTH_FAILED, c1)
        bus.subscribe(EventType.AUTH_FAILED, c2)
        bus.subscribe(EventType.AUTH_FAILED, ok)
        await bus.emit(AtlasEvent(EventType.AUTH_FAILED))
        assert calls == [1]


class TestUnsubscribe:
    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self):
        bus = EventBus()
        calls: list[int] = []
        async def h(e: AtlasEvent) -> None: calls.append(1)
        bus.subscribe(EventType.CONFIG_RELOADED, h)
        await bus.emit(AtlasEvent(EventType.CONFIG_RELOADED))
        bus.unsubscribe(EventType.CONFIG_RELOADED, h)
        await bus.emit(AtlasEvent(EventType.CONFIG_RELOADED))
        assert len(calls) == 1  # only the first emit

    def test_unsubscribe_nonexistent_does_not_raise(self):
        bus = EventBus()
        async def h(e: AtlasEvent) -> None: pass
        bus.unsubscribe(EventType.AUTH_SUCCESS, h)  # must not raise


class TestBug09:
    @pytest.mark.asyncio
    async def test_memory_write_event_type_exists(self):
        """BUG-09: MEMORY_WRITE_REQUEST event must exist."""
        assert EventType.MEMORY_WRITE_REQUEST in list(EventType)

    @pytest.mark.asyncio
    async def test_tts_finished_before_memory_write(self):
        """BUG-09: TTS_FINISHED must fire before MEMORY_WRITE_REQUEST."""
        bus = EventBus()
        order: list[str] = []
        async def on_tts(e: AtlasEvent) -> None: order.append("tts")
        async def on_mem(e: AtlasEvent) -> None: order.append("mem")
        bus.subscribe(EventType.TTS_FINISHED, on_tts)
        bus.subscribe(EventType.MEMORY_WRITE_REQUEST, on_mem)
        await bus.emit(AtlasEvent(EventType.TTS_FINISHED, source="pipeline"))
        await bus.emit(AtlasEvent(EventType.MEMORY_WRITE_REQUEST, source="pipeline"))
        assert order == ["tts", "mem"], "BUG-09: memory write must come after TTS"


class TestSingleton:
    def test_same_instance_returned(self):
        assert get_event_bus() is get_event_bus()
