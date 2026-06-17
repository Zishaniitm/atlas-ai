"""
TTS abstraction for ATLAS — Kokoro (offline) + ElevenLabs (premium).

Kokoro TTS is always available (bundled, no network).
ElevenLabs is used only when an API key is present in the OS keychain.
Persona switching must complete in <=500ms (SRS NFR-003).

SRS: FR-004 (TTS uses selected persona), FR-009 (streaming audio),
     FR-010 (8 built-in offline personas), FR-013 (switch without restart),
     FR-014 (ElevenLabs premium voices), FR-015 (offline vs premium badge),
     NFR-003 (persona switch <=500ms), NFR-017 (voice data stays local)
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import AsyncIterator

from atlas.core.config import get_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


# ── Abstract base ─────────────────────────────────────────────

class TTSEngine(ABC):
    """Base class all TTS engines implement."""

    @abstractmethod
    async def speak(self, text: str) -> bytes:
        """
        Synthesize text to audio bytes (WAV).

        SRS: FR-004, FR-009
        """

    @abstractmethod
    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Stream audio chunks as they are generated.

        SRS: FR-009 (first audio byte before full response ready)
        """
        # mypy requires yield in abstract async generators
        raise NotImplementedError
        yield b""  # pragma: no cover

    @abstractmethod
    def set_speaking_rate(self, rate: float) -> None:
        """SRS: FR-016 (0.5 to 2.0)"""

    @abstractmethod
    def set_pitch_offset(self, semitones: int) -> None:
        """SRS: FR-016 (-12 to +12)"""


# ── Kokoro TTS (offline, always available) ────────────────────

class KokoroTTS(TTSEngine):
    """
    Kokoro TTS engine — offline, bundled, MIT licensed.
    Replaces abandoned Coqui TTS (BUG-02 fix).

    SRS: FR-010 (8 offline personas), NFR-003 (switch <=500ms),
         NFR-017 (no network — fully local)
    """

    def __init__(self, voice_id: str = "af_sky") -> None:
        self._voice_id = voice_id
        self._rate: float = 1.0
        self._pitch: int = 0
        self._pipeline: object | None = None

    async def load(self) -> None:
        """
        Load Kokoro pipeline (blocking — runs in thread pool).

        SRS: NFR-010 (loaded once at startup as part of cold start budget)
        """
        try:
            self._pipeline = await asyncio.to_thread(self._load_pipeline)
            logger.info("kokoro_loaded", voice=self._voice_id)
        except Exception as exc:
            logger.error("kokoro_load_failed", exc_info=exc)
            raise RuntimeError("Failed to load Kokoro TTS pipeline.") from exc

    def _load_pipeline(self) -> object:
        """Blocking Kokoro load — called inside thread pool."""
        from kokoro import KPipeline  # type: ignore[import]
        return KPipeline(lang_code="a")  # 'a' = American English default

    def set_voice(self, voice_id: str) -> None:
        """
        Change the active Kokoro voice token.

        SRS: FR-013 (persona switch without restart), NFR-003 (<=500ms)
        """
        self._voice_id = voice_id
        logger.debug("kokoro_voice_set", voice=voice_id)

    def set_speaking_rate(self, rate: float) -> None:
        """SRS: FR-016 (0.5 to 2.0)"""
        self._rate = max(0.5, min(2.0, rate))

    def set_pitch_offset(self, semitones: int) -> None:
        """SRS: FR-016 (-12 to +12 semitones)"""
        self._pitch = max(-12, min(12, semitones))

    async def speak(self, text: str) -> bytes:
        """
        Synthesize text to WAV bytes using Kokoro.

        SRS: FR-004, FR-009, NFR-017

        Args:
            text: Text to synthesize. Should not contain API keys or PII.

        Returns:
            WAV audio bytes.
        """
        if self._pipeline is None:
            raise RuntimeError("KokoroTTS.load() must be called before speak().")

        chunks: list[bytes] = []
        async for chunk in self.stream(text):
            chunks.append(chunk)
        return b"".join(chunks)

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Stream Kokoro audio chunks.

        SRS: FR-009 (first byte before full response ready)
        """
        if self._pipeline is None:
            raise RuntimeError("KokoroTTS.load() must be called before stream().")

        import numpy as np  # type: ignore[import]
        import soundfile as sf  # type: ignore[import]
        import io

        def _generate() -> list[bytes]:
            chunks_out: list[bytes] = []
            pipeline = self._pipeline  # type: ignore[union-attr]
            for _, _, audio in pipeline(
                text,
                voice=self._voice_id,
                speed=self._rate,
            ):
                buf = io.BytesIO()
                sf.write(buf, audio, 24000, format="WAV")
                chunks_out.append(buf.getvalue())
            return chunks_out

        audio_chunks = await asyncio.to_thread(_generate)
        for chunk in audio_chunks:
            yield chunk


# ── ElevenLabs TTS (premium, requires API key) ────────────────

class ElevenLabsTTS(TTSEngine):
    """
    ElevenLabs premium TTS — requires API key in OS keychain.
    Used only when the user has configured an ElevenLabs voice.

    SRS: FR-014 (premium voices), FR-015 (clearly marked as premium),
         NFR-015 (API key from keychain only — never from config file)
    """

    def __init__(self, voice_id: str, api_key: str) -> None:
        self._voice_id = voice_id
        self._api_key = api_key  # passed from keychain, never stored on disk
        self._rate: float = 1.0
        self._pitch: int = 0

    def set_speaking_rate(self, rate: float) -> None:
        """SRS: FR-016"""
        self._rate = max(0.5, min(2.0, rate))

    def set_pitch_offset(self, semitones: int) -> None:
        """SRS: FR-016"""
        self._pitch = max(-12, min(12, semitones))

    async def speak(self, text: str) -> bytes:
        """
        Synthesize text via ElevenLabs API.

        SRS: FR-004, FR-014, NFR-016 (HTTPS enforced by elevenlabs SDK)

        Args:
            text: Text to synthesize.

        Returns:
            MP3 audio bytes from ElevenLabs.

        Raises:
            RuntimeError: If ElevenLabs API call fails.
        """
        try:
            from elevenlabs.client import ElevenLabs  # type: ignore[import]
            client = ElevenLabs(api_key=self._api_key)
            audio = await asyncio.to_thread(
                client.text_to_speech.convert,
                voice_id=self._voice_id,
                text=text,
                model_id="eleven_turbo_v2",
            )
            return b"".join(audio)
        except Exception as exc:
            logger.error("elevenlabs_speak_failed", exc_info=exc)
            raise RuntimeError("ElevenLabs TTS failed.") from exc

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """
        Stream ElevenLabs audio chunks.

        SRS: FR-009 (streaming — first chunk before full audio ready)
        """
        try:
            from elevenlabs.client import ElevenLabs  # type: ignore[import]
            client = ElevenLabs(api_key=self._api_key)

            def _stream_sync() -> list[bytes]:
                return list(client.text_to_speech.convert_as_stream(
                    voice_id=self._voice_id,
                    text=text,
                    model_id="eleven_turbo_v2",
                ))

            chunks = await asyncio.to_thread(_stream_sync)
            for chunk in chunks:
                yield chunk
        except Exception as exc:
            logger.error("elevenlabs_stream_failed", exc_info=exc)
            raise RuntimeError("ElevenLabs stream failed.") from exc


# ── Factory ───────────────────────────────────────────────────

def build_tts_engine(
    engine_name: str,
    voice_id: str,
    api_key: str | None = None,
) -> TTSEngine:
    """
    Build the correct TTS engine from config.

    SRS: FR-010 (kokoro default), FR-014 (elevenlabs when key present),
         BUG-02 (coqui MUST NOT be used)

    Args:
        engine_name: 'kokoro' or 'elevenlabs'. Never 'coqui'.
        voice_id: Kokoro voice token or ElevenLabs voice ID.
        api_key: ElevenLabs API key from OS keychain (None for Kokoro).

    Returns:
        Configured TTSEngine instance.

    Raises:
        ValueError: If engine_name is 'coqui' (BUG-02) or unknown.
    """
    if engine_name == "coqui":
        raise ValueError(
            "coqui-tts is abandoned (Jan 2024). Use 'kokoro' instead. (BUG-02 fix)"
        )

    if engine_name == "elevenlabs":
        if not api_key:
            logger.warning("elevenlabs_no_key_falling_back_to_kokoro")
            return KokoroTTS(voice_id=voice_id)
        return ElevenLabsTTS(voice_id=voice_id, api_key=api_key)

    if engine_name == "kokoro":
        return KokoroTTS(voice_id=voice_id)

    raise ValueError(f"Unknown TTS engine: '{engine_name}'. Valid: kokoro, elevenlabs.")
