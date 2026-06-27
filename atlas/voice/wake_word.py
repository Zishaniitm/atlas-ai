"""Wake word detector — background thread. SRS: FR-001, FR-007, NFR-005"""
from __future__ import annotations
import threading
from typing import Callable
import numpy as np
from atlas.core.config import get_config
from atlas.core.events import AtlasEvent, EventType, get_event_bus
from atlas.utils.logging import get_logger

logger = get_logger(__name__)
_SAMPLE_RATE = 16000
_CHUNK       = 1280   # 80ms — openWakeWord recommended


class WakeWordDetector:
    def __init__(self, on_detected: Callable[[], None] | None = None) -> None:
        self._wake_word   = get_config().voice.wake_word
        self._on_detected = on_detected
        self._stop        = threading.Event()
        self._thread: threading.Thread | None = None
        self._model: object | None = None

    def load(self) -> None:
        """SRS: NFR-010 (loaded at startup)"""
        try:
            from openwakeword.model import Model  # type: ignore[import]
            self._model = Model(inference_framework="onnx")
            logger.info("wake_word_loaded", word=self._wake_word)
        except Exception as exc:
            raise RuntimeError("openWakeWord failed to load.") from exc

    def start(self) -> None:
        """SRS: FR-001 (continuous monitoring)"""
        if self._model is None:
            raise RuntimeError("Call load() first.")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="atlas-ww")
        self._thread.start()
        logger.info("wake_word_started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        try:
            import pyaudio  # type: ignore[import]
        except ImportError:
            logger.error("pyaudio_not_installed")
            return
        cfg = get_config()
        pa  = pyaudio.PyAudio()
        stream = pa.open(rate=_SAMPLE_RATE, channels=1, format=pyaudio.paInt16,
                         input=True, input_device_index=cfg.voice.mic_device_index,
                         frames_per_buffer=_CHUNK)
        try:
            while not self._stop.is_set():
                raw   = stream.read(_CHUNK, exception_on_overflow=False)
                audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                self._model.predict(audio)  # type: ignore[union-attr]
                for _, buf in self._model.prediction_buffer.items():  # type: ignore[union-attr]
                    if buf[-1] > 0.5:
                        logger.info("wake_word_detected")
                        self._fire()
                        import time; time.sleep(1.0)
                        break
        except Exception as exc:
            logger.error("wake_word_loop_error", exc_info=exc)
        finally:
            stream.stop_stream(); stream.close(); pa.terminate()

    def _fire(self) -> None:
        get_event_bus().emit_nowait(AtlasEvent(
            EventType.WAKE_WORD_DETECTED,
            data={"wake_word": self._wake_word},
            source="wake_word_detector",
        ))
        if self._on_detected:
            self._on_detected()
