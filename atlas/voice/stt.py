"""Whisper STT wrapper. SRS: FR-001, FR-002, NFR-002, NFR-017 (fully local)"""
from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any
import numpy as np
from atlas.core.config import get_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class WhisperSTT:
    def __init__(self) -> None:
        self._model: Any = None
        self._model_name = get_config().voice.whisper_model

    async def load(self) -> None:
        """SRS: NFR-010 (loaded once at cold start)"""
        logger.info("whisper_loading", model=self._model_name)
        try:
            self._model = await asyncio.to_thread(self._load_sync)
            logger.info("whisper_loaded")
        except Exception as exc:
            raise RuntimeError(f"Failed to load Whisper '{self._model_name}'") from exc

    def _load_sync(self) -> Any:
        import whisper  # type: ignore[import]
        return whisper.load_model(self._model_name)

    async def transcribe(self, audio: np.ndarray, language: str | None = None) -> str:
        """SRS: FR-002 (>=95% WER), FR-006 (multi-language), NFR-017 (local)"""
        if self._model is None:
            raise RuntimeError("Call load() first.")
        result: dict[str, Any] = await asyncio.to_thread(
            self._model.transcribe, audio, language=language, fp16=False
        )
        return result.get("text", "").strip()

    async def transcribe_file(self, path: Path) -> str:
        if self._model is None:
            raise RuntimeError("Call load() first.")
        result: dict[str, Any] = await asyncio.to_thread(
            self._model.transcribe, str(path), fp16=False
        )
        return result.get("text", "").strip()
