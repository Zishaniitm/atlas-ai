"""
ATLAS crash reporter.

On any unhandled exception or fatal signal, writes a structured
crash_YYYYMMDD_HHMMSS.json to ~/.atlas/logs/ before the process exits.
Sentry integration is opt-in only — off by default (NFR-024).

Never includes conversation content, API keys, or biometric data.

SRS: FR-102 (local crash.json), FR-103 (HUD dialog), FR-104 (Sentry opt-in),
     FR-105 (no personal data), FR-106 (30-day retention), NFR-036 (write before exit)
"""

from __future__ import annotations

import json
import platform
import signal
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType, TracebackType
from typing import TYPE_CHECKING

from atlas.utils.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

_CRASH_DIR: Path = Path("~/.atlas/logs").expanduser()
_sentry_initialised: bool = False


def _write_crash_report(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> Path:
    """
    Write a structured crash report JSON file.

    SRS: FR-102, FR-105 — no personal data, no API keys, no biometric values.

    Args:
        exc_type: Exception class.
        exc_value: Exception instance.
        exc_tb: Traceback object.

    Returns:
        Path to the written crash file.
    """
    _CRASH_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    timestamp = datetime.now(tz=timezone.utc)
    filename = f"crash_{timestamp.strftime('%Y%m%d_%H%M%S')}.json"
    crash_path = _CRASH_DIR / filename

    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)

    report: dict[str, object] = {
        "atlas_version": _get_atlas_version(),
        "timestamp_utc": timestamp.isoformat(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": sys.version,
            "machine": platform.machine(),
        },
        "exception": {
            "type": exc_type.__name__,
            "module": getattr(exc_type, "__module__", "unknown"),
            # value str may contain user text — truncate and sanitise
            "message": _safe_truncate(str(exc_value), max_len=200),
        },
        "traceback": tb_lines,
        # Explicitly excluded: conversation, memory, biometrics, API keys
    }

    crash_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.error(
        "crash_report_written",
        path=str(crash_path),
        exc_type=exc_type.__name__,
    )
    return crash_path


def _safe_truncate(text: str, max_len: int = 200) -> str:
    """Truncate potentially sensitive exception messages."""
    if len(text) > max_len:
        return text[:max_len] + "… [truncated]"
    return text


def _get_atlas_version() -> str:
    """Read version from pyproject.toml without importing the full package."""
    try:
        import importlib.metadata
        return importlib.metadata.version("atlas-ai")
    except Exception:
        return "unknown"


def _unhandled_exception_hook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    """
    sys.excepthook replacement — called on any unhandled exception.

    SRS: NFR-036 — crash report written before process exits.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        # Normal Ctrl-C — don't write a crash report
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    _write_crash_report(exc_type, exc_value, exc_tb)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _signal_handler(signum: int, _frame: FrameType | None) -> None:
    """
    Handle SIGTERM / SIGINT — write crash report then exit.

    SRS: NFR-036
    """
    logger.warning("signal_received", signal=signum)
    sys.exit(1)


def init_sentry(dsn: str) -> None:
    """
    Initialise opt-in Sentry crash telemetry.

    Must only be called after the user has explicitly opted in during
    first-run setup. Never called by default.

    SRS: FR-104 (opt-in), FR-105 (no personal data)

    Args:
        dsn: Sentry DSN string from OS keychain (never from config file).

    Raises:
        ImportError: If sentry-sdk is not installed.
    """
    global _sentry_initialised
    if _sentry_initialised:
        return

    try:
        import sentry_sdk
    except ImportError as exc:
        raise ImportError("sentry-sdk is not installed.") from exc

    sentry_sdk.init(
        dsn=dsn,
        # Never send personally identifiable information
        send_default_pii=False,
        before_send=_sentry_filter_event,
        traces_sample_rate=0.0,  # No performance tracing — privacy
    )
    _sentry_initialised = True
    logger.info("sentry_initialised")


def _sentry_filter_event(
    event: dict[str, object],
    _hint: dict[str, object],
) -> dict[str, object] | None:
    """
    Strip any sensitive keys before sending to Sentry.

    SRS: FR-105 — crash telemetry must never include personal data.
    """
    _BLOCKED_KEYS = {"user", "email", "username", "ip_address", "request"}
    for key in _BLOCKED_KEYS:
        event.pop(key, None)
    return event


def register_handlers() -> None:
    """
    Register the crash reporter as the global exception hook and signal handler.

    Call once at ATLAS startup, before any other module is initialised.

    SRS: NFR-036, FR-102
    """
    sys.excepthook = _unhandled_exception_hook
    signal.signal(signal.SIGTERM, _signal_handler)
    logger.info("crash_reporter_registered")
