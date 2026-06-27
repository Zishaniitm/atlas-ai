"""
ATLAS crash reporter.
SRS: FR-102 (local crash.json), FR-104 (Sentry opt-in), FR-105 (no PII),
     NFR-036 (write before exit)
"""
from __future__ import annotations
import json, platform, signal, sys, traceback
from datetime import datetime, timezone
from pathlib import Path
from types import FrameType, TracebackType

from atlas.utils.logging import get_logger
logger = get_logger(__name__)

_CRASH_DIR = Path("~/.atlas/logs").expanduser()
_sentry_ok = False


def _write_crash(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> Path:
    """SRS: FR-102, FR-105 (no PII in report)"""
    _CRASH_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    ts   = datetime.now(tz=timezone.utc)
    path = _CRASH_DIR / f"crash_{ts.strftime('%Y%m%d_%H%M%S')}.json"
    report = {
        "atlas_version": _version(),
        "timestamp_utc": ts.isoformat(),
        "platform": {
            "system": platform.system(), "release": platform.release(),
            "python": sys.version, "machine": platform.machine(),
        },
        "exception": {
            "type":    exc_type.__name__,
            "module":  getattr(exc_type, "__module__", "unknown"),
            "message": str(exc_value)[:200],
        },
        "traceback": traceback.format_exception(exc_type, exc_value, exc_tb),
    }
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.error("crash_report_written", path=str(path), exc=exc_type.__name__)
    return path


def _version() -> str:
    try:
        import importlib.metadata
        return importlib.metadata.version("atlas-ai")
    except Exception:
        return "unknown"


def _hook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb); return
    _write_crash(exc_type, exc_value, exc_tb)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _signal_handler(signum: int, _frame: FrameType | None) -> None:
    logger.warning("signal_received", signal=signum)
    sys.exit(1)


def init_sentry(dsn: str) -> None:
    """SRS: FR-104 (opt-in only), FR-105 (no PII)"""
    global _sentry_ok
    if _sentry_ok:
        return
    import sentry_sdk  # type: ignore[import]
    sentry_sdk.init(dsn=dsn, send_default_pii=False,
                    before_send=lambda e, _: {k: v for k, v in e.items()
                                              if k not in {"user","email","ip_address"}},
                    traces_sample_rate=0.0)
    _sentry_ok = True
    logger.info("sentry_init")


def register_handlers() -> None:
    """Call once at startup, before anything else. SRS: NFR-036"""
    sys.excepthook = _hook
    signal.signal(signal.SIGTERM, _signal_handler)
    logger.info("crash_reporter_registered")
