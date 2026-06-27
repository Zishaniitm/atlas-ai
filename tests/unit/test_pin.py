"""
Unit tests for atlas.security.auth.pin
SRS: Section 11.1 (Auth >=85% coverage), FR-079, FR-080, FR-096
"""
from __future__ import annotations
import pytest
from unittest.mock import patch
from atlas.security.auth.pin import (
    AuthResult, _state, enrol, verify, delete, is_enrolled,
)


def _reset():
    _state.attempts = 0
    _state.locked_until = 0.0
    _state.full_locked = False


# ── Enrolment ─────────────────────────────────────────────────

class TestEnrol:
    @pytest.mark.asyncio
    async def test_valid_pin_returns_true(self, tmp_path):
        pf = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            assert await enrol("1234") is True
        assert pf.exists()

    @pytest.mark.asyncio
    async def test_too_short_returns_false(self, tmp_path):
        pf = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            assert await enrol("12") is False
        assert not pf.exists()

    @pytest.mark.asyncio
    async def test_too_long_returns_false(self, tmp_path):
        pf = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            assert await enrol("x" * 65) is False

    @pytest.mark.asyncio
    async def test_replaces_existing_pin(self, tmp_path):
        pf = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            await enrol("1234")
            first = pf.read_text()
            await enrol("5678")
            assert pf.read_text() != first


# ── Verification ──────────────────────────────────────────────

class TestVerify:
    @pytest.mark.asyncio
    async def test_correct_pin_succeeds(self, tmp_path):
        _reset()
        pf = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            await enrol("9999")
            result = await verify("9999")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_wrong_pin_fails(self, tmp_path):
        _reset()
        pf = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            await enrol("9999")
            result = await verify("0000")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_no_pin_enrolled_returns_clear_message(self, tmp_path):
        _reset()
        pf = tmp_path / "nope.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            result = await verify("1234")
        assert result.success is False
        assert "No PIN enrolled" in result.message

    @pytest.mark.asyncio
    async def test_fr096_counter_incremented_before_return(self, tmp_path):
        """FR-096: failure counter must increment BEFORE returning failure result."""
        _reset()
        pf = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            await enrol("1234")
            before = _state.attempts
            await verify("wrong")
            assert _state.attempts == before + 1

    @pytest.mark.asyncio
    async def test_success_resets_counter(self, tmp_path):
        _reset()
        pf = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            await enrol("1234")
            await verify("wrong")
            assert _state.attempts == 1
            await verify("1234")
            assert _state.attempts == 0


# ── Rate limiting — FR-096 ─────────────────────────────────────

class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_lockout_after_5_failures(self, tmp_path):
        """FR-096: 5 failures trigger 30s lockout."""
        _reset()
        pf = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            await enrol("1234")
            for _ in range(5):
                await verify("wrong")
            result = await verify("wrong")
        assert result.success is False
        assert "Try again" in result.message

    @pytest.mark.asyncio
    async def test_correct_pin_blocked_during_lockout(self, tmp_path):
        """Even the correct PIN is blocked during rate-limit lockout."""
        _reset()
        import time
        _state.locked_until = time.monotonic() + 30.0
        pf = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            await enrol("1234")
            result = await verify("1234")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_full_lockout_after_10_failures(self, tmp_path):
        _reset()
        _state.full_locked = True
        pf = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            await enrol("1234")
            result = await verify("1234")
        assert result.success is False
        assert "fully locked" in result.message


# ── Delete — FR-095 ───────────────────────────────────────────

class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_enrolled_pin(self, tmp_path):
        pf = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            await enrol("1234")
            assert await delete() is True
            assert not pf.exists()

    @pytest.mark.asyncio
    async def test_delete_non_existent_returns_false(self, tmp_path):
        pf = tmp_path / "nope.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            assert await delete() is False


# ── is_enrolled ───────────────────────────────────────────────

class TestIsEnrolled:
    @pytest.mark.asyncio
    async def test_false_when_no_file(self, tmp_path):
        pf = tmp_path / "nope.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            assert is_enrolled() is False

    @pytest.mark.asyncio
    async def test_true_after_enrol(self, tmp_path):
        pf = tmp_path / "pin.json"
        with patch("atlas.security.auth.pin._PIN_FILE", pf):
            await enrol("1234")
            assert is_enrolled() is True
