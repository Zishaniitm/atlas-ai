"""
Async voice pipeline orchestrator for ATLAS.

Connects wake word detector → STT → LLM brain → TTS → audio output.
Memory writes fire AFTER TTS playback — never blocking the response (BUG-09).
Target round-trip: <=2s (cloud), <=4s (local LLM).

SRS: FR-001–009, NFR-001 (<=2s/4s latency), BUG-09 (async memory writes),
     SRS 4.2.1 (async queue-based pipeline), SRS 4.3 (data flow steps 1-11)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum, auto

import numpy as np
import pyaudio  # type: ignore[import]

from atlas.core.config import get_config
from atlas.core.events import AtlasEvent, EventType, get_event_bus
from atlas.utils.logging import get_logger
from atlas.voice.stt import WhisperSTT
from atlas.voice.tts import TTSEngine, build_tts_engine
from atlas.voice.wake_word import WakeWordDetector

logger = get_logger(__name__)

_SAMPLE_RATE  = 16000
_RECORD_CHUNK = 1024
_SILENCE_SEC  = 1.2   # seconds of silence = end of speech (FR-005)
_SILENCE_THRESH = 0.01


class PipelineState(StrEnum):
    LOCKED   = auto()   # waiting for auth (FR-079)
    IDLE     = auto()   # listening for wake word
    LISTENING = auto()  # recording user speech
    THINKING  = auto()  # LLM processing
    SPEAKING  = auto()  # TTS playing


@dataclass
class ConversationTurn:
    """
    One full user→ATLAS exchange. Passed to memory after TTS (BUG-09).

    SRS: FR-047 (conversation stored), BUG-09 (written after response)
    """

    user_text: str
    atlas_text: str
    timestamp: float = field(default_factory=time.time)


class VoicePipeline:
    """
    Async voice pipeline — the heart of ATLAS's voice interaction.

    Runs entirely on the async event loop (except wake word thread).
    Memory writes are always scheduled AFTER TTS completes.

    SRS: FR-001–009, SRS Section 4.2.1, NFR-001, BUG-09
    """

    def __init__(self) -> None:
        cfg = get_config()
        self._stt = WhisperSTT()
        self._tts: TTSEngine = build_tts_engine(
            cfg.voice.tts_engine,
            voice_id=cfg.voice.persona,
        )
        self._wake = WakeWordDetector(on_detected=self._on_wake_word_sync)
        self._state = PipelineState.LOCKED
        self._audio_queue: asyncio.Queue[np.ndarray] = asyncio.Queue()
        self._llm_handler: asyncio.Coroutine[None, None, str] | None = None
        self._pa = pyaudio.PyAudio()

    # ── Lifecycle ─────────────────────────────────────────────

    async def start(self, llm_handler: object) -> None:
        """
        Initialise all components and enter the pipeline event loop.

        SRS: NFR-010 (cold start <=8 sec), FR-001 (continuous monitoring)

        Args:
            llm_handler: Object with async method process(text) -> str.
        """
        self._llm = llm_handler
        await self._stt.load()

        if isinstance(self._tts, object) and hasattr(self._tts, "load"):
            await self._tts.load()  # type: ignore[union-attr]

        self._wake.load()
        self._wake.start()

        bus = get_event_bus()
        bus.subscribe(EventType.WAKE_WORD_DETECTED, self._handle_wake_event)
        bus.subscribe(EventType.AUTH_SUCCESS, self._handle_auth_success)
        bus.subscribe(EventType.SESSION_LOCKED, self._handle_session_locked)

        logger.info("voice_pipeline_started")

    async def stop(self) -> None:
        """Gracefully shut down the pipeline."""
        self._wake.stop()
        self._pa.terminate()
        logger.info("voice_pipeline_stopped")

    # ── Auth integration ──────────────────────────────────────

    async def _handle_auth_success(self, _event: AtlasEvent) -> None:
        """
        Unlock pipeline after successful authentication.

        SRS: FR-079 (pipeline locked until auth passes)
        """
        self._state = PipelineState.IDLE
        logger.info("pipeline_unlocked")

    async def _handle_session_locked(self, _event: AtlasEvent) -> None:
        """
        Lock pipeline when OS screen lock fires.

        SRS: FR-092 (auto-lock on OS lock event)
        """
        self._state = PipelineState.LOCKED
        logger.info("pipeline_locked")

    # ── Wake word → record → STT ──────────────────────────────

    def _on_wake_word_sync(self) -> None:
        """Called from the wake word thread. Schedules async handler."""
        asyncio.get_event_loop().call_soon_threadsafe(
            lambda: asyncio.create_task(self._record_and_process())
        )

    async def _handle_wake_event(self, _event: AtlasEvent) -> None:
        """Event bus handler for WAKE_WORD_DETECTED."""
        if self._state != PipelineState.IDLE:
            return
        await self._record_and_process()

    async def _record_and_process(self) -> None:
        """
        Record user speech until silence, then run STT → LLM → TTS.

        SRS: FR-005 (auto end-of-speech), NFR-001 (<=2s/4s round-trip)
        """
        if self._state != PipelineState.IDLE:
            return

        self._state = PipelineState.LISTENING
        bus = get_event_bus()

        # Step 4 (SRS 4.3): record audio
        audio = await self._record_until_silence()
        if audio is None or len(audio) < _SAMPLE_RATE * 0.3:
            self._state = PipelineState.IDLE
            return

        # Step 4 (SRS 4.3): STT transcription
        self._state = PipelineState.THINKING
        t0 = time.monotonic()
        transcript = await self._stt.transcribe(audio)

        if not transcript.strip():
            self._state = PipelineState.IDLE
            return

        logger.info("stt_complete", ms=int((time.monotonic() - t0) * 1000))
        bus.emit_nowait(AtlasEvent(
            EventType.STT_TRANSCRIPT_READY,
            data={"text": transcript},
            source="voice_pipeline",
        ))

        # Step 5-8 (SRS 4.3): LLM → response
        response_text = await self._llm.process(transcript)

        # Step 9 (SRS 4.3): TTS playback
        self._state = PipelineState.SPEAKING
        bus.emit_nowait(AtlasEvent(EventType.TTS_STARTED, source="voice_pipeline"))
        await self._play_tts(response_text)
        bus.emit_nowait(AtlasEvent(EventType.TTS_FINISHED, source="voice_pipeline"))

        # Step 10 (SRS 4.3) BUG-09: memory write AFTER TTS — never before
        turn = ConversationTurn(user_text=transcript, atlas_text=response_text)
        bus.emit_nowait(AtlasEvent(
            EventType.MEMORY_WRITE_REQUEST,
            data={"turn": turn.__dict__},
            source="voice_pipeline",
        ))

        total_ms = int((time.monotonic() - t0) * 1000)
        logger.info("pipeline_round_trip", ms=total_ms)
        self._state = PipelineState.IDLE

    async def _record_until_silence(self) -> np.ndarray | None:
        """
        Record microphone until _SILENCE_SEC of silence detected.

        SRS: FR-005 (auto end-of-speech detection)

        Returns:
            Float32 numpy audio array, or None on error.
        """
        cfg = get_config()
        try:
            stream = self._pa.open(
                rate=_SAMPLE_RATE,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                input_device_index=cfg.voice.mic_device_index,
                frames_per_buffer=_RECORD_CHUNK,
            )
        except Exception as exc:
            logger.error("mic_open_failed", exc_info=exc)
            return None

        frames: list[np.ndarray] = []
        silent_chunks = 0
        silence_limit = int(_SILENCE_SEC * _SAMPLE_RATE / _RECORD_CHUNK)

        try:
            while True:
                raw = await asyncio.to_thread(
                    stream.read, _RECORD_CHUNK, False
                )
                chunk = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                frames.append(chunk)

                if np.abs(chunk).mean() < _SILENCE_THRESH:
                    silent_chunks += 1
                    if silent_chunks >= silence_limit and len(frames) > silence_limit:
                        break
                else:
                    silent_chunks = 0
        finally:
            stream.stop_stream()
            stream.close()

        return np.concatenate(frames) if frames else None

    async def _play_tts(self, text: str) -> None:
        """
        Stream TTS audio to speakers.

        SRS: FR-009 (first audio before full response ready), NFR-001
        """
        stream = self._pa.open(
            rate=24000,
            channels=1,
            format=pyaudio.paFloat32,
            output=True,
        )
        try:
            async for chunk in self._tts.stream(text):
                if chunk:
                    await asyncio.to_thread(stream.write, chunk)
        finally:
            stream.stop_stream()
            stream.close()

    # ── Text-mode input (FR-003) ──────────────────────────────

    async def process_text(self, text: str) -> str:
        """
        Process a text command directly — bypasses wake word + STT.

        SRS: FR-003 (keyboard text input alternative to voice)

        Args:
            text: User's text command.

        Returns:
            ATLAS response text.
        """
        if self._state == PipelineState.LOCKED:
            return "ATLAS is locked. Please authenticate first."

        prev_state = self._state
        self._state = PipelineState.THINKING

        try:
            response = await self._llm.process(text)
        finally:
            self._state = prev_state

        # BUG-09: fire memory write after response — not before
        bus = get_event_bus()
        turn = ConversationTurn(user_text=text, atlas_text=response)
        bus.emit_nowait(AtlasEvent(
            EventType.MEMORY_WRITE_REQUEST,
            data={"turn": turn.__dict__},
            source="voice_pipeline",
        ))
        return response

    def set_persona(self, voice_id: str) -> None:
        """
        Switch the active TTS voice persona.

        SRS: FR-013 (switch without restart), NFR-003 (<=500ms)

        Args:
            voice_id: Kokoro voice token or ElevenLabs voice ID.
        """
        if hasattr(self._tts, "set_voice"):
            self._tts.set_voice(voice_id)  # type: ignore[union-attr]
            logger.info("persona_switched", voice_id=voice_id)
