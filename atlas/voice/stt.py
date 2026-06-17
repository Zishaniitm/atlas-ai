"""
Whisper STT wrapper for ATLAS.

Loads Whisper locally — audio never sent to external servers.
Transcription runs in a thread pool to avoid blocking the async event loop.

SRS: FR-001 (continuous monitoring), FR-002 (>=95% accuracy),
     FR-005 (auto end-of-speech), FR-006 (multi-language),
     NFR-002 (<=5% WER), NFR-017 (audio stays local)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import numpy as np

from atlas.core.config import get_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class WhisperSTT:
    """
    Async wrapper around OpenAI Whisper for local speech transcription.

    SRS: FR-002 (>=95% accuracy), NFR-017 (fully local — no network call)
    """

    def __init__(self) -> None:
        self._model: Any = None
        self._model_name: str = get_config().voice.whisper_model

    async def load(self) -> None:
        """
        Load the Whisper model into memory (runs in thread pool).

        SRS: NFR-010 (cold start <=8 sec — model loaded once at startup)

        Raises:
            RuntimeError: If the Whisper model cannot be loaded.
        """
        logger.info("whisper_loading", model=self._model_name)
        try:
            self._model = await asyncio.to_thread(self._load_model)
            logger.info("whisper_loaded", model=self._model_name)
        except Exception as exc:
            logger.error("whisper_load_failed", model=self._model_name, exc_info=exc)
            raise RuntimeError(f"Failed to load Whisper model '{self._model_name}'") from exc

    def _load_model(self) -> Any:
        """Blocking model load — called inside thread pool."""
        import whisper  # type: ignore[import]
        return whisper.load_model(self._model_name)

    async def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        language: str | None = None,
    ) -> str:
        """
        Transcribe a numpy audio array to text.

        SRS: FR-002 (>=95% WER English), FR-006 (multi-language via language param),
             NFR-002 (WER target), NFR-017 (local only)

        Args:
            audio: Float32 numpy array normalised to [-1.0, 1.0].
            sample_rate: Audio sample rate. Whisper expects 16 kHz.
            language: ISO 639-1 language code (e.g. 'en', 'hi'). None = auto-detect.

        Returns:
            Transcribed text string, stripped of leading/trailing whitespace.

        Raises:
            RuntimeError: If the model has not been loaded via load() first.
        """
        if self._model is None:
            raise RuntimeError("WhisperSTT.load() must be called before transcribe().")

        if sample_rate != 16000:
            audio = self._resample(audio, sample_rate, 16000)

        logger.debug("whisper_transcribing", language=language or "auto")

        result: dict[str, Any] = await asyncio.to_thread(
            self._model.transcribe,
            audio,
            language=language,
            fp16=False,  # CPU-safe
        )

        text: str = result.get("text", "").strip()
        logger.debug("whisper_transcript", chars=len(text))
        return text

    @staticmethod
    def _resample(
        audio: np.ndarray,
        orig_rate: int,
        target_rate: int,
    ) -> np.ndarray:
        """
        Simple linear resample. For production, prefer librosa or resampy.

        SRS: FR-002 — Whisper requires 16 kHz input.
        """
        ratio = target_rate / orig_rate
        new_len = int(len(audio) * ratio)
        indices = np.linspace(0, len(audio) - 1, new_len)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

    async def transcribe_file(self, path: Path) -> str:
        """
        Transcribe an audio file at the given path.

        SRS: FR-002, NFR-017

        Args:
            path: Path to WAV or MP3 file.

        Returns:
            Transcribed text.
        """
        if self._model is None:
            raise RuntimeError("WhisperSTT.load() must be called first.")

        result: dict[str, Any] = await asyncio.to_thread(
            self._model.transcribe, str(path), fp16=False
        )
        return result.get("text", "").strip()
