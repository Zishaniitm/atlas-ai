"""
ATLAS structured logging setup.

Configures structlog with a rotating file handler and a human-readable
console renderer for development. Log files auto-delete after 30 days.
Never logs personal data, API keys, or biometric values.

SRS: FR-106 (30-day log retention), NFR-024 (no personal data in logs),
     NFR-036 (crash report before exit)
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from datetime import datetime, timezone
from pathlib import Path

import structlog


_LOG_DIR: Path | None = None


def _get_log_dir(log_dir: str = "~/.atlas/logs") -> Path:
    """Create and return the log directory with restricted permissions."""
    path = Path(log_dir).expanduser()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _purge_old_logs(log_dir: Path, retention_days: int = 30) -> None:
    """
    Delete log files older than retention_days.

    SRS: FR-106 — logs auto-delete after 30 days.
    """
    now = datetime.now(tz=timezone.utc).timestamp()
    cutoff = now - (retention_days * 86400)
    for log_file in log_dir.glob("atlas_*.log"):
        try:
            if log_file.stat().st_mtime < cutoff:
                log_file.unlink()
        except OSError:
            pass  # best-effort; don't crash on cleanup


def setup_logging(
    log_dir: str = "~/.atlas/logs",
    retention_days: int = 30,
    dev_mode: bool = False,
) -> None:
    """
    Initialise structlog for the ATLAS process.

    Sets up:
    - Rotating file handler (10 MB max, 5 backups)
    - Console renderer (pretty in dev, JSON in production)
    - Automatic log purge on startup

    SRS: FR-106, NFR-024 (no PII in logs)

    Args:
        log_dir: Directory for log files. Default: ~/.atlas/logs
        retention_days: Delete logs older than this. Default: 30
        dev_mode: Use pretty console output. Default: False (JSON)
    """
    global _LOG_DIR
    _LOG_DIR = _get_log_dir(log_dir)
    _purge_old_logs(_LOG_DIR, retention_days)

    today = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    log_file = _LOG_DIR / f"atlas_{today}.log"

    # stdlib handler — rotating file
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        level=logging.DEBUG,
        handlers=[file_handler, console_handler],
    )

    # Shared processors for all renderers
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if dev_mode:
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Apply renderer to stdlib formatter
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    for handler in [file_handler, console_handler]:
        handler.setFormatter(formatter)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Return a named structlog logger.

    SRS: NFR-024 — callers must never pass PII, keys, or biometric
    values as log fields.

    Args:
        name: Module name, e.g. 'atlas.core.config'

    Returns:
        Configured BoundLogger instance.
    """
    return structlog.get_logger(name)  # type: ignore[return-value]
