"""
PIN / password authentication provider.

Baseline auth method — works on all hardware with no peripherals.
PINs are hashed with bcrypt (cost=12) and stored locally.
Rate limiting enforced per FR-096: 5 failures → 30s lockout, 10 → full lock.

SRS: FR-079 (locked startup), FR-080 (PIN baseline), FR-096 (rate limiting),
     NFR-015 (no secrets on disk), NFR-022 (bcrypt hashing)
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import bcrypt

from atlas.core.config import get_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)

_PIN_FILE = Path("~/.atlas/security/pin.json").expanduser()


# ── Data models ───────────────────────────────────────────────

@dataclass
class AuthResult:
    """
    Result returned by every authentication attempt.

    SRS: FR-079 (locked until success=True)
    """

    success: bool
    message: str
    locked_until: float | None = None   # epoch seconds; None = not locked


@dataclass
class _RateLimitState:
    """In-process rate limit state. Resets on ATLAS restart."""

    attempts: int = 0
    locked_until: float = 0.0
    full_locked: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


_state = _RateLimitState()


# ── PIN storage ───────────────────────────────────────────────

def _load_pin_hash() -> bytes | None:
    """
    Load the stored bcrypt hash from disk.

    Returns None if no PIN has been enrolled yet.
    """
    if not _PIN_FILE.exists():
        return None
    try:
        data: dict[str, str] = json.loads(_PIN_FILE.read_text(encoding="utf-8"))
        return data["hash"].encode("utf-8")
    except (KeyError, ValueError, OSError) as exc:
        logger.error("pin_load_failed", exc_info=exc)
        return None


def _save_pin_hash(pin_hash: bytes) -> None:
    """
    Persist the bcrypt hash to disk with restricted permissions.

    SRS: NFR-020 (user-only file permissions)
    """
    _PIN_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _PIN_FILE.write_text(
        json.dumps({"hash": pin_hash.decode("utf-8")}),
        encoding="utf-8",
    )
    _PIN_FILE.chmod(0o600)


# ── Rate limiting ─────────────────────────────────────────────

async def _check_rate_limit() -> AuthResult | None:
    """
    Return a failure AuthResult if currently locked out, else None.

    SRS: FR-096 — checked BEFORE verifying the PIN.
    """
    async with _state._lock:
        if _state.full_locked:
            return AuthResult(
                success=False,
                message="Account fully locked after too many failures. Contact support.",
            )
        if time.monotonic() < _state.locked_until:
            remaining = int(_state.locked_until - time.monotonic())
            return AuthResult(
                success=False,
                message=f"Too many failed attempts. Try again in {remaining}s.",
                locked_until=_state.locked_until,
            )
    return None


async def _record_failure() -> None:
    """
    Increment failure counter and apply lockout if thresholds exceeded.

    SRS: FR-096 — counter incremented BEFORE returning failure result.
    """
    cfg = get_config().auth
    async with _state._lock:
        _state.attempts += 1
        logger.warning("auth_pin_failed", attempt=_state.attempts)

        if _state.attempts >= cfg.full_lockout_after:
            _state.full_locked = True
            logger.error("auth_full_lockout", attempts=_state.attempts)
        elif _state.attempts >= cfg.rate_limit_attempts:
            _state.locked_until = time.monotonic() + cfg.rate_limit_lockout_sec
            logger.warning(
                "auth_rate_locked",
                lockout_sec=cfg.rate_limit_lockout_sec,
            )


async def _record_success() -> None:
    """Reset rate limit state on successful authentication."""
    async with _state._lock:
        _state.attempts = 0
        _state.locked_until = 0.0
        # Note: full_locked stays set — only a manual admin reset clears it


# ── Public API ────────────────────────────────────────────────

def is_enrolled() -> bool:
    """
    Return True if a PIN has been enrolled on this machine.

    SRS: FR-079 — ATLAS shows enrolment screen if not enrolled.
    """
    return _PIN_FILE.exists() and _load_pin_hash() is not None


async def enrol(pin: str) -> bool:
    """
    Hash and store a new PIN. Replaces any existing PIN.

    SRS: FR-079, FR-080, FR-095 (user can update auth method)

    Args:
        pin: Plain-text PIN (4–64 characters enforced here).

    Returns:
        True on success, False if PIN is too short.
    """
    if len(pin) < 4:
        logger.warning("pin_enrol_too_short")
        return False
    if len(pin) > 64:
        logger.warning("pin_enrol_too_long")
        return False

    # bcrypt cost=12 per NFR-022
    pin_hash = await asyncio.to_thread(
        bcrypt.hashpw, pin.encode("utf-8"), bcrypt.gensalt(rounds=12)
    )
    _save_pin_hash(pin_hash)
    logger.info("pin_enrolled")
    return True


async def verify(pin: str) -> AuthResult:
    """
    Verify a PIN against the stored hash.

    Rate limit is checked first, then the PIN is verified.
    Failure counter is incremented BEFORE returning on failure (FR-096).

    SRS: FR-079 (startup lock), FR-080, FR-096 (rate limiting)

    Args:
        pin: Plain-text PIN provided by the user.

    Returns:
        AuthResult with success=True on match, False otherwise.
    """
    # 1. Check rate limit before touching the hash (FR-096)
    if lockout := await _check_rate_limit():
        return lockout

    stored_hash = _load_pin_hash()
    if stored_hash is None:
        logger.error("pin_verify_no_hash_enrolled")
        return AuthResult(success=False, message="No PIN enrolled. Please set up authentication.")

    # 2. Compare — runs in thread pool to avoid blocking event loop
    try:
        match = await asyncio.to_thread(
            bcrypt.checkpw, pin.encode("utf-8"), stored_hash
        )
    except (ValueError, OSError) as exc:
        logger.error("pin_verify_error", exc_info=exc)
        await _record_failure()
        return AuthResult(success=False, message="Authentication error. Please try again.")

    if match:
        await _record_success()
        logger.info("auth_pin_success")
        return AuthResult(success=True, message="Authenticated.")

    # 3. FR-096 — increment counter BEFORE returning failure
    await _record_failure()
    return AuthResult(success=False, message="Incorrect PIN. Please try again.")


async def delete() -> bool:
    """
    Remove the stored PIN hash from disk.

    SRS: FR-095 (user can delete any auth method)

    Returns:
        True if deleted, False if no PIN was enrolled.
    """
    if not _PIN_FILE.exists():
        return False
    try:
        _PIN_FILE.unlink()
        logger.info("pin_deleted")
        return True
    except OSError as exc:
        logger.error("pin_delete_failed", exc_info=exc)
        return False
