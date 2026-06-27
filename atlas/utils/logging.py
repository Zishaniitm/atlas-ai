"""
ATLAS structured logging. SRS: FR-106 (30-day retention), NFR-024 (no PII)
"""
from __future__ import annotations
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
import structlog

_LOG_DIR: Path | None = None


def _get_log_dir(log_dir: str = "~/.atlas/logs") -> Path:
    p = Path(log_dir).expanduser()
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    return p


def _purge_old_logs(log_dir: Path, retention_days: int = 30) -> None:
    """SRS: FR-106 — auto-delete logs older than retention_days."""
    cutoff = datetime.now(tz=timezone.utc).timestamp() - retention_days * 86400
    for f in log_dir.glob("atlas_*.log"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def setup_logging(
    log_dir: str = "~/.atlas/logs",
    retention_days: int = 30,
    dev_mode: bool = False,
) -> None:
    """SRS: FR-106, NFR-024"""
    global _LOG_DIR
    _LOG_DIR = _get_log_dir(log_dir)
    _purge_old_logs(_LOG_DIR, retention_days)

    today = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    log_file = _LOG_DIR / f"atlas_{today}.log"

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    logging.basicConfig(format="%(message)s", level=logging.DEBUG,
                        handlers=[file_handler, console_handler])

    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer() if dev_mode
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer, foreign_pre_chain=shared
    )
    for h in [file_handler, console_handler]:
        h.setFormatter(formatter)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """SRS: NFR-024 — never pass PII, keys, or biometrics as log fields."""
    return structlog.get_logger(name)  # type: ignore[return-value]
