"""
PIN authentication. SRS: FR-079, FR-080, FR-096, NFR-022 (bcrypt cost=12)
"""
from __future__ import annotations
import asyncio, json, time
from dataclasses import dataclass, field
from pathlib import Path
import bcrypt
from atlas.core.config import get_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)
_PIN_FILE = Path("~/.atlas/security/pin.json").expanduser()


@dataclass
class AuthResult:
    success: bool
    message: str
    locked_until: float | None = None


@dataclass
class _State:
    attempts: int = 0
    locked_until: float = 0.0
    full_locked: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


_state = _State()


def _load_hash() -> bytes | None:
    if not _PIN_FILE.exists():
        return None
    try:
        return json.loads(_PIN_FILE.read_text())["hash"].encode()
    except Exception:
        return None


def _save_hash(h: bytes) -> None:
    _PIN_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _PIN_FILE.write_text(json.dumps({"hash": h.decode()}))
    _PIN_FILE.chmod(0o600)


async def _check_limit() -> AuthResult | None:
    async with _state._lock:
        if _state.full_locked:
            return AuthResult(False, "Account fully locked. Contact support.")
        if time.monotonic() < _state.locked_until:
            remaining = int(_state.locked_until - time.monotonic())
            return AuthResult(False, f"Too many attempts. Try again in {remaining}s.",
                              locked_until=_state.locked_until)
    return None


async def _fail() -> None:
    """FR-096: counter incremented BEFORE returning failure."""
    cfg = get_config().auth
    async with _state._lock:
        _state.attempts += 1
        if _state.attempts >= cfg.full_lockout_after:
            _state.full_locked = True
            logger.error("auth_full_lockout", attempts=_state.attempts)
        elif _state.attempts >= cfg.rate_limit_attempts:
            _state.locked_until = time.monotonic() + cfg.rate_limit_lockout_sec
            logger.warning("auth_rate_locked", sec=cfg.rate_limit_lockout_sec)


async def _succeed() -> None:
    async with _state._lock:
        _state.attempts = 0
        _state.locked_until = 0.0


def is_enrolled() -> bool:
    return _PIN_FILE.exists() and _load_hash() is not None


async def enrol(pin: str) -> bool:
    """SRS: FR-079, FR-080, FR-095"""
    if len(pin) < 4 or len(pin) > 64:
        return False
    h = await asyncio.to_thread(bcrypt.hashpw, pin.encode(), bcrypt.gensalt(rounds=12))
    _save_hash(h)
    logger.info("pin_enrolled")
    return True


async def verify(pin: str) -> AuthResult:
    """SRS: FR-079, FR-096 — rate limit checked BEFORE hash comparison."""
    if lockout := await _check_limit():
        return lockout
    stored = _load_hash()
    if stored is None:
        return AuthResult(False, "No PIN enrolled. Please set up authentication.")
    try:
        match = await asyncio.to_thread(bcrypt.checkpw, pin.encode(), stored)
    except (ValueError, OSError) as exc:
        logger.error("pin_verify_error", exc_info=exc)
        await _fail()
        return AuthResult(False, "Authentication error. Please try again.")
    if match:
        await _succeed()
        logger.info("pin_auth_success")
        return AuthResult(True, "Authenticated.")
    await _fail()   # FR-096: counter before return
    return AuthResult(False, "Incorrect PIN. Please try again.")


async def delete() -> bool:
    """SRS: FR-095"""
    if not _PIN_FILE.exists():
        return False
    try:
        _PIN_FILE.unlink()
        logger.info("pin_deleted")
        return True
    except OSError:
        return False
