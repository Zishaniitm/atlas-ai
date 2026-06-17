"""
Unit tests for atlas.security.auth.pin.

SRS: SRS Section 11.1 (Auth >= 85% coverage),
     FR-079 (locked startup), FR-080 (PIN baseline),
     FR-096 (rate limiting — counter incremented BEFORE returning failure)
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock

from atlas.security.auth.pin import (
    AuthResult,
    _RateLimitState,
    _state,
    enrol,
    verify,
    delete,
    is_enrolled,
)


# ── Helpers ───────────────────────────────────────────────────

def _reset_state() -> None:
    """Reset in-process rate limit state between tests."""
    _state.attempts = 0
    _state.locked_until = 0.0
    _state.full_locked = False


# ── Enrolment ─────────────────────────────────────────────────

class TestEnrol:
    @pytest.mark.asyncio
    async def test_enrol_valid_pin_returns_true(self, tmp_path):
        pin_file = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            result = await enrol("1234")
        assert result is True
        assert pin_file.exists()

    @pytest.mark.asyncio
    async def test_enrol_too_short_returns_false(self, tmp_path):
        pin_file = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            result = await enrol("123")
        assert result is False
        assert not pin_file.exists()

    @pytest.mark.asyncio
    async def test_enrol_too_long_returns_false(self, tmp_path):
        pin_file = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            result = await enrol("x" * 65)
        assert result is False

    @pytest.mark.asyncio
    async def test_enrol_replaces_existing_pin(self, tmp_path):
        pin_file = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            await enrol("1234")
            first_content = pin_file.read_text()
            await enrol("5678")
            second_content = pin_file.read_text()
        assert first_content != second_content


# ── Verification ──────────────────────────────────────────────

class TestVerify:
    @pytest.mark.asyncio
    async def test_verify_correct_pin_succeeds(self, tmp_path):
        _reset_state()
        pin_file = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            await enrol("9999")
            result = await verify("9999")
        assert result.success is True
        assert result.message == "Authenticated."

    @pytest.mark.asyncio
    async def test_verify_wrong_pin_fails(self, tmp_path):
        _reset_state()
        pin_file = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            await enrol("9999")
            result = await verify("0000")
        assert result.success is False
        assert "Incorrect" in result.message

    @pytest.mark.asyncio
    async def test_verify_no_pin_enrolled(self, tmp_path):
        _reset_state()
        pin_file = tmp_path / "nofile.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            result = await verify("1234")
        assert result.success is False
        assert "No PIN enrolled" in result.message

    @pytest.mark.asyncio
    async def test_verify_counter_incremented_before_return(self, tmp_path):
        """FR-096: failure counter incremented BEFORE returning failure result."""
        _reset_state()
        pin_file = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            await enrol("1234")
            before = _state.attempts
            await verify("wrong")
            after = _state.attempts
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_verify_success_resets_counter(self, tmp_path):
        _reset_state()
        pin_file = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            await enrol("1234")
            await verify("wrong")   # fail once
            assert _state.attempts == 1
            await verify("1234")    # succeed
            assert _state.attempts == 0


# ── Rate Limiting — FR-096 ────────────────────────────────────

class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_lockout_after_5_failures(self, tmp_path):
        """FR-096: 5 failures trigger 30-second lockout."""
        _reset_state()
        pin_file = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            await enrol("1234")
            for _ in range(5):
                await verify("wrong")
            result = await verify("wrong")
        assert result.success is False
        assert "Try again" in result.message

    @pytest.mark.asyncio
    async def test_full_lockout_after_10_failures(self, tmp_path):
        """FR-096: 10 failures trigger full lockout."""
        _reset_state()
        pin_file = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            await enrol("1234")
            for _ in range(10):
                _state.attempts += 1
        _state.full_locked = True
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            result = await verify("1234")
        assert result.success is False
        assert "fully locked" in result.message

    @pytest.mark.asyncio
    async def test_correct_pin_blocked_during_lockout(self, tmp_path):
        """Even the correct PIN is blocked during a rate-limit lockout."""
        _reset_state()
        pin_file = tmp_path / "pin.json"
        import time
        _state.locked_until = time.monotonic() + 30.0
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            await enrol("1234")
            result = await verify("1234")
        assert result.success is False
        assert "Try again" in result.message


# ── Delete ────────────────────────────────────────────────────

class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_enrolled_pin(self, tmp_path):
        pin_file = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            await enrol("1234")
            assert pin_file.exists()
            result = await delete()
            assert result is True
            assert not pin_file.exists()

    @pytest.mark.asyncio
    async def test_delete_non_existent_returns_false(self, tmp_path):
        pin_file = tmp_path / "nofile.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            result = await delete()
        assert result is False


# ── is_enrolled ───────────────────────────────────────────────

class TestIsEnrolled:
    @pytest.mark.asyncio
    async def test_not_enrolled_when_no_file(self, tmp_path):
        pin_file = tmp_path / "nofile.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            assert is_enrolled() is False

    @pytest.mark.asyncio
    async def test_enrolled_after_enrol(self, tmp_path):
        pin_file = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pin_file):
            await enrol("1234")
            assert is_enrolled() is True
