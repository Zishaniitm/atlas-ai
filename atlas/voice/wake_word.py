"""
Wake word detection for ATLAS using openWakeWord.

Runs in a background thread (not async — PyAudio uses blocking I/O).
When the wake word fires, posts a WAKE_WORD_DETECTED event to the bus.

SRS: FR-001 (continuous monitoring), FR-007 (configurable wake word),
     NFR-005 (<=3% CPU idle), NFR-017 (fully local — no cloud call)
"""

from __future__ import annotations

import threading
from typing import Callable

import numpy as np

from atlas.core.config import get_config
from atlas.core.events import AtlasEvent, EventType, get_event_bus
from atlas.utils.logging import get_logger

logger = get_logger(__name__)

_SAMPLE_RATE = 16000
_CHUNK_SIZE  = 1280   # 80ms at 16kHz — openWakeWord recommended


class WakeWordDetector:
    """
    Continuous wake word monitor running in a dedicated background thread.

    Uses openWakeWord for on-device detection with no cloud dependency.

    SRS: FR-001, FR-007, NFR-005 (lightweight — runs on CPU <=3% idle)
    """

    def __init__(self, on_detected: Callable[[], None] | None = None) -> None:
        self._wake_word: str = get_config().voice.wake_word
        self._on_detected = on_detected
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._oww_model: object | None = None

    def load(self) -> None:
        """
        Load the openWakeWord model (blocking — call before start()).

        SRS: NFR-010 (loaded at startup as part of cold start)

        Raises:
            RuntimeError: If openWakeWord cannot be imported or model not found.
        """
        try:
            from openwakeword.model import Model  # type: ignore[import]
            self._oww_model = Model(
                wakeword_models=["hey_atlas"],  # custom model name
                inference_framework="onnx",
            )
            logger.info("wake_word_loaded", wake_word=self._wake_word)
        except ImportError as exc:
            raise RuntimeError(
                "openWakeWord not installed. Run: pip install openWakeWord"
            ) from exc
        except Exception as exc:
            logger.warning(
                "wake_word_custom_model_not_found",
                detail="Falling back to 'hey jarvis' placeholder. "
                       "Train a custom model for 'hey atlas'.",
            )
            # Fallback: use included model for development
            try:
                from openwakeword.model import Model  # type: ignore[import]
                self._oww_model = Model(inference_framework="onnx")
            except Exception as inner:
                raise RuntimeError("openWakeWord failed to load.") from inner

    def start(self) -> None:
        """
        Start the wake word detector in a background thread.

        SRS: FR-001 (continuous monitoring), SRS 4.2.1 (background thread)
        """
        if self._oww_model is None:
            raise RuntimeError("Call load() before start().")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="atlas-wake-word",
        )
        self._thread.start()
        logger.info("wake_word_started", wake_word=self._wake_word)

    def stop(self) -> None:
        """
        Stop the wake word detector.

        SRS: NFR-005 (releases CPU when ATLAS is shutting down)
        """
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("wake_word_stopped")

    def _run_loop(self) -> None:
        """
        Blocking audio loop — runs inside the background thread.

        Reads microphone chunks, runs openWakeWord inference,
        emits WAKE_WORD_DETECTED event when confidence exceeds threshold.

        SRS: FR-001, NFR-005
        """
        try:
            import pyaudio  # type: ignore[import]
        except ImportError:
            logger.error("pyaudio_not_installed")
            return

        cfg = get_config()
        pa = pyaudio.PyAudio()
        stream = pa.open(
            rate=_SAMPLE_RATE,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            input_device_index=cfg.voice.mic_device_index,
            frames_per_buffer=_CHUNK_SIZE,
        )

        logger.debug("wake_word_listening")

        try:
            while not self._stop_event.is_set():
                raw = stream.read(_CHUNK_SIZE, exception_on_overflow=False)
                audio_chunk = (
                    np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                )

                model = self._oww_model  # type: ignore[union-attr]
                model.predict(audio_chunk)
                scores: dict[str, float] = model.prediction_buffer

                for model_name, score_buf in scores.items():
                    if score_buf[-1] > 0.5:  # confidence threshold
                        logger.info("wake_word_detected", model=model_name)
                        self._fire_detected()
                        # brief cooldown to avoid double-firing
                        import time; time.sleep(1.0)
                        break

        except Exception as exc:
            logger.error("wake_word_loop_error", exc_info=exc)
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    def _fire_detected(self) -> None:
        """Emit wake word event and call optional callback."""
        bus = get_event_bus()
        bus.emit_nowait(
            AtlasEvent(
                type=EventType.WAKE_WORD_DETECTED,
                data={"wake_word": self._wake_word},
                source="wake_word_detector",
            )
        )
        if self._on_detected:
            self._on_detected()
