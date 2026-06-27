"""
Async voice pipeline. Wake word → STT → LLM → TTS → memory (async).
SRS: FR-001–009, NFR-001, BUG-09 (memory after TTS), SRS 4.3
"""
from __future__ import annotations
import asyncio
import time
from enum import StrEnum, auto
import numpy as np
from atlas.core.config import get_config
from atlas.core.events import AtlasEvent, EventType, get_event_bus
from atlas.utils.logging import get_logger
from atlas.voice.stt import WhisperSTT
from atlas.voice.tts import TTSEngine, build_tts_engine
from atlas.voice.wake_word import WakeWordDetector

logger = get_logger(__name__)
_SR      = 16000
_CHUNK   = 1024
_SIL_SEC = 1.2
_SIL_THR = 0.01


class PipelineState(StrEnum):
    LOCKED    = auto()
    IDLE      = auto()
    LISTENING = auto()
    THINKING  = auto()
    SPEAKING  = auto()


class VoicePipeline:
    """SRS: FR-001–009, SRS 4.2.1, NFR-001"""

    def __init__(self) -> None:
        cfg = get_config()
        self._stt   = WhisperSTT()
        self._tts   = build_tts_engine(cfg.voice.tts_engine, cfg.voice.persona)
        self._wake  = WakeWordDetector(on_detected=self._wake_sync)
        self._state = PipelineState.LOCKED
        self._llm: object | None = None
        try:
            import pyaudio  # type: ignore[import]
            self._pa = pyaudio.PyAudio()
        except Exception:
            self._pa = None

    async def start(self, llm_handler: object) -> None:
        """SRS: NFR-010"""
        self._llm = llm_handler
        await self._stt.load()
        if hasattr(self._tts, "load"):
            await self._tts.load()  # type: ignore[union-attr]
        self._wake.load()
        self._wake.start()
        bus = get_event_bus()
        bus.subscribe(EventType.WAKE_WORD_DETECTED, self._on_wake)
        bus.subscribe(EventType.AUTH_SUCCESS,       self._on_auth_ok)
        bus.subscribe(EventType.SESSION_LOCKED,     self._on_lock)
        logger.info("voice_pipeline_started")

    async def stop(self) -> None:
        self._wake.stop()
        if self._pa:
            self._pa.terminate()

    async def _on_auth_ok(self, _: AtlasEvent) -> None:
        """SRS: FR-079"""
        self._state = PipelineState.IDLE
        logger.info("pipeline_unlocked")

    async def _on_lock(self, _: AtlasEvent) -> None:
        """SRS: FR-092"""
        self._state = PipelineState.LOCKED

    def _wake_sync(self) -> None:
        asyncio.get_event_loop().call_soon_threadsafe(
            lambda: asyncio.create_task(self._record_and_process())
        )

    async def _on_wake(self, _: AtlasEvent) -> None:
        if self._state == PipelineState.IDLE:
            await self._record_and_process()

    async def _record_and_process(self) -> None:
        if self._state != PipelineState.IDLE or not self._pa:
            return
        self._state = PipelineState.LISTENING
        bus = get_event_bus()

        audio = await self._record_until_silence()
        if audio is None or len(audio) < _SR * 0.3:
            self._state = PipelineState.IDLE; return

        self._state = PipelineState.THINKING
        t0 = time.monotonic()
        text = await self._stt.transcribe(audio)
        if not text.strip():
            self._state = PipelineState.IDLE; return

        bus.emit_nowait(AtlasEvent(EventType.STT_TRANSCRIPT_READY, {"text": text}, "pipeline"))

        response = await self._llm.process(text)  # type: ignore[union-attr]

        self._state = PipelineState.SPEAKING
        bus.emit_nowait(AtlasEvent(EventType.TTS_STARTED, source="pipeline"))
        await self._play(response)
        bus.emit_nowait(AtlasEvent(EventType.TTS_FINISHED, source="pipeline"))

        # BUG-09: memory write AFTER TTS — fire-and-forget
        bus.emit_nowait(AtlasEvent(EventType.MEMORY_WRITE_REQUEST,
                                   {"turn": {"user_text": text, "atlas_text": response}},
                                   "pipeline"))

        ms = int((time.monotonic() - t0) * 1000)
        logger.info("pipeline_round_trip", ms=ms)
        self._state = PipelineState.IDLE

    async def _record_until_silence(self) -> np.ndarray | None:
        """SRS: FR-005 (auto end-of-speech)"""
        cfg = get_config()
        try:
            import pyaudio  # type: ignore[import]
            stream = self._pa.open(rate=_SR, channels=1, format=pyaudio.paInt16,  # type: ignore[union-attr]
                                   input=True, input_device_index=cfg.voice.mic_device_index,
                                   frames_per_buffer=_CHUNK)
        except Exception as exc:
            logger.error("mic_open_failed", exc_info=exc); return None

        frames: list[np.ndarray] = []
        silent = 0
        limit  = int(_SIL_SEC * _SR / _CHUNK)
        try:
            while True:
                raw   = await asyncio.to_thread(stream.read, _CHUNK, False)
                chunk = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                frames.append(chunk)
                silent = silent + 1 if np.abs(chunk).mean() < _SIL_THR else 0
                if silent >= limit and len(frames) > limit:
                    break
        finally:
            stream.stop_stream(); stream.close()
        return np.concatenate(frames) if frames else None

    async def _play(self, text: str) -> None:
        """SRS: FR-009 (streaming audio)"""
        if not self._pa:
            return
        import pyaudio  # type: ignore[import]
        stream = self._pa.open(rate=24000, channels=1, format=pyaudio.paFloat32, output=True)
        try:
            async for chunk in self._tts.stream(text):
                if chunk:
                    await asyncio.to_thread(stream.write, chunk)
        finally:
            stream.stop_stream(); stream.close()

    async def process_text(self, text: str) -> str:
        """SRS: FR-003 (keyboard text input)"""
        if self._state == PipelineState.LOCKED:
            return "ATLAS is locked. Please authenticate first."
        prev = self._state; self._state = PipelineState.THINKING
        try:
            response = await self._llm.process(text)  # type: ignore[union-attr]
        finally:
            self._state = prev
        get_event_bus().emit_nowait(AtlasEvent(EventType.MEMORY_WRITE_REQUEST,
                                               {"turn": {"user_text": text, "atlas_text": response}},
                                               "pipeline"))
        return response

    def set_persona(self, voice_id: str) -> None:
        """SRS: FR-013, NFR-003"""
        if hasattr(self._tts, "set_voice"):
            self._tts.set_voice(voice_id)  # type: ignore[union-attr]
