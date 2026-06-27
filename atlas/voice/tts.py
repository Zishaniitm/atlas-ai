"""
TTS abstraction — Kokoro (offline) + ElevenLabs (premium).
SRS: FR-004, FR-009, FR-010, FR-013–015, NFR-003, BUG-02 (no coqui)
"""
from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from typing import AsyncIterator
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class TTSEngine(ABC):
    @abstractmethod
    async def speak(self, text: str) -> bytes: ...
    @abstractmethod
    async def stream(self, text: str) -> AsyncIterator[bytes]:
        yield b""  # pragma: no cover
    @abstractmethod
    def set_speaking_rate(self, rate: float) -> None: ...
    @abstractmethod
    def set_pitch_offset(self, semitones: int) -> None: ...


class KokoroTTS(TTSEngine):
    """Offline TTS — replaces abandoned Coqui (BUG-02). SRS: FR-010, NFR-017"""

    def __init__(self, voice_id: str = "af_sky") -> None:
        self._voice = voice_id
        self._rate  = 1.0
        self._pitch = 0
        self._pipe: object | None = None

    async def load(self) -> None:
        try:
            self._pipe = await asyncio.to_thread(self._load_sync)
            logger.info("kokoro_loaded", voice=self._voice)
        except Exception as exc:
            raise RuntimeError("Failed to load Kokoro TTS.") from exc

    def _load_sync(self) -> object:
        from kokoro import KPipeline  # type: ignore[import]
        return KPipeline(lang_code="a")

    def set_voice(self, voice_id: str) -> None:
        """SRS: FR-013 (switch without restart), NFR-003 (<=500ms)"""
        self._voice = voice_id

    def set_speaking_rate(self, rate: float) -> None:
        self._rate = max(0.5, min(2.0, rate))

    def set_pitch_offset(self, semitones: int) -> None:
        self._pitch = max(-12, min(12, semitones))

    async def speak(self, text: str) -> bytes:
        chunks = [c async for c in self.stream(text)]
        return b"".join(chunks)

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        if self._pipe is None:
            raise RuntimeError("Call load() first.")
        import io, soundfile as sf  # type: ignore[import]

        def _gen() -> list[bytes]:
            out = []
            for _, _, audio in self._pipe(text, voice=self._voice, speed=self._rate):  # type: ignore[call-overload]
                buf = io.BytesIO()
                sf.write(buf, audio, 24000, format="WAV")
                out.append(buf.getvalue())
            return out

        for chunk in await asyncio.to_thread(_gen):
            yield chunk


class ElevenLabsTTS(TTSEngine):
    """Premium TTS. SRS: FR-014, NFR-015 (key from keychain only)"""

    def __init__(self, voice_id: str, api_key: str) -> None:
        self._voice = voice_id
        self._key   = api_key
        self._rate  = 1.0
        self._pitch = 0

    def set_speaking_rate(self, rate: float) -> None:
        self._rate = max(0.5, min(2.0, rate))

    def set_pitch_offset(self, semitones: int) -> None:
        self._pitch = max(-12, min(12, semitones))

    async def speak(self, text: str) -> bytes:
        try:
            from elevenlabs.client import ElevenLabs  # type: ignore[import]
            client = ElevenLabs(api_key=self._key)
            audio = await asyncio.to_thread(
                client.text_to_speech.convert, voice_id=self._voice,
                text=text, model_id="eleven_turbo_v2"
            )
            return b"".join(audio)
        except Exception as exc:
            logger.error("elevenlabs_failed", exc_info=exc)
            raise RuntimeError("ElevenLabs TTS failed.") from exc

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        chunks = await asyncio.to_thread(lambda: list(self._stream_sync(text)))
        for c in chunks:
            yield c

    def _stream_sync(self, text: str):  # type: ignore[no-untyped-def]
        from elevenlabs.client import ElevenLabs  # type: ignore[import]
        return ElevenLabs(api_key=self._key).text_to_speech.convert_as_stream(
            voice_id=self._voice, text=text, model_id="eleven_turbo_v2"
        )


def build_tts_engine(engine_name: str, voice_id: str,
                     api_key: str | None = None) -> TTSEngine:
    """SRS: BUG-02 (reject coqui), FR-010 (kokoro default)"""
    if engine_name == "coqui":
        raise ValueError("coqui-tts is abandoned (Jan 2024). Use 'kokoro'. (BUG-02)")
    if engine_name == "elevenlabs":
        if not api_key:
            logger.warning("elevenlabs_no_key_falling_back_to_kokoro")
            return KokoroTTS(voice_id=voice_id)
        return ElevenLabsTTS(voice_id=voice_id, api_key=api_key)
    if engine_name == "kokoro":
        return KokoroTTS(voice_id=voice_id)
    raise ValueError(f"Unknown TTS engine: '{engine_name}'")
