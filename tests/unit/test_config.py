"""
Unit tests for atlas.core.config.

SRS: SRS Section 11.1 (>=90% coverage for config module)
Tests: BUG-02 guard (no coqui), BUG-04 (auth section present),
       BUG-09 (async_writes always True), deep merge logic.
"""

from __future__ import annotations

import pytest
import yaml
from pathlib import Path
from pydantic import ValidationError

from atlas.core.config import (
    AtlasConfig,
    AuthConfig,
    LLMConfig,
    MemoryConfig,
    VoiceConfig,
    _deep_merge,
    load_config,
)


# ── _deep_merge ───────────────────────────────────────────────

class TestDeepMerge:
    def test_deep_merge_basic(self) -> None:
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        override = {"b": {"d": 99}}
        result = _deep_merge(base, override)
        assert result["b"]["c"] == 2   # untouched
        assert result["b"]["d"] == 99  # overridden

    def test_deep_merge_adds_new_key(self) -> None:
        base = {"a": 1}
        override = {"b": 2}
        result = _deep_merge(base, override)
        assert result["a"] == 1
        assert result["b"] == 2

    def test_deep_merge_does_not_mutate_base(self) -> None:
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        _deep_merge(base, override)
        assert "y" not in base["a"]

    def test_deep_merge_nested_three_levels(self) -> None:
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"c": 99}}}
        result = _deep_merge(base, override)
        assert result["a"]["b"]["c"] == 99
        assert result["a"]["b"]["d"] == 2


# ── VoiceConfig — BUG-02 guard ────────────────────────────────

class TestVoiceConfigBug02:
    def test_coqui_rejected(self) -> None:
        """BUG-02: coqui-tts is abandoned — must be rejected at config load."""
        with pytest.raises(ValidationError, match="coqui"):
            VoiceConfig(tts_engine="coqui")

    def test_kokoro_accepted(self) -> None:
        cfg = VoiceConfig(tts_engine="kokoro")
        assert cfg.tts_engine == "kokoro"

    def test_elevenlabs_accepted(self) -> None:
        cfg = VoiceConfig(tts_engine="elevenlabs")
        assert cfg.tts_engine == "elevenlabs"

    def test_speaking_rate_clamped_by_validator(self) -> None:
        with pytest.raises(ValidationError):
            VoiceConfig(speaking_rate=5.0)   # > 2.0

    def test_pitch_offset_clamped_by_validator(self) -> None:
        with pytest.raises(ValidationError):
            VoiceConfig(pitch_offset=99)      # > 12


# ── MemoryConfig — BUG-09 guard ──────────────────────────────

class TestMemoryConfigBug09:
    def test_async_writes_false_rejected(self) -> None:
        """BUG-09: async_writes=False blocks TTS — must always be True."""
        with pytest.raises(ValidationError, match="async_writes"):
            MemoryConfig(async_writes=False)

    def test_async_writes_true_accepted(self) -> None:
        cfg = MemoryConfig(async_writes=True)
        assert cfg.async_writes is True

    def test_working_window_bounds(self) -> None:
        with pytest.raises(ValidationError):
            MemoryConfig(working_window=0)


# ── AuthConfig — BUG-04 (always present) ─────────────────────

class TestAuthConfigBug04:
    def test_auth_config_has_defaults(self) -> None:
        """BUG-04: auth section must always be present with valid defaults."""
        cfg = AuthConfig()
        assert cfg.primary_method == "pin"
        assert cfg.voice_print_threshold == 0.92
        assert cfg.face_distance_threshold == 0.45
        assert cfg.rate_limit_attempts == 5
        assert cfg.rate_limit_lockout_sec == 30

    def test_voice_print_threshold_bounds(self) -> None:
        with pytest.raises(ValidationError):
            AuthConfig(voice_print_threshold=1.5)  # > 1.0

    def test_tier2_risk_levels_default(self) -> None:
        cfg = AuthConfig()
        assert "critical" in cfg.tier2_risk_levels
        assert "high" in cfg.tier2_risk_levels


# ── AtlasConfig — full model ──────────────────────────────────

class TestAtlasConfig:
    def test_default_config_is_valid(self) -> None:
        cfg = AtlasConfig()
        assert cfg.llm.provider == "openai"
        assert cfg.voice.persona == "atlas_default"
        assert cfg.api.port == 7770

    def test_auth_always_present(self) -> None:
        """BUG-04: auth section must never be missing."""
        cfg = AtlasConfig()
        assert cfg.auth is not None
        assert cfg.auth.primary_method == "pin"

    def test_model_validate_from_dict(self) -> None:
        data = {
            "llm": {"provider": "ollama", "model": "mistral"},
            "voice": {"tts_engine": "kokoro"},
        }
        cfg = AtlasConfig.model_validate(data)
        assert cfg.llm.provider == "ollama"


# ── load_config ───────────────────────────────────────────────

class TestLoadConfig:
    def test_load_config_missing_defaults_raises(self, tmp_path: Path) -> None:
        """If defaults.yaml is missing, load_config raises FileNotFoundError."""
        from unittest.mock import patch
        fake_path = tmp_path / "nonexistent.yaml"
        with patch("atlas.core.config._DEFAULTS_PATH", fake_path):
            with pytest.raises(FileNotFoundError):
                load_config()

    def test_load_config_with_user_override(self, tmp_path: Path) -> None:
        """User override merges on top of defaults without losing unset keys."""
        defaults_path = tmp_path / "defaults.yaml"
        defaults_path.write_text(
            "atlas:\n  llm:\n    provider: openai\n    model: gpt-4o\n"
            "  voice:\n    tts_engine: kokoro\n  memory:\n    async_writes: true\n"
        )
        user_path = tmp_path / "user.yaml"
        user_path.write_text("atlas:\n  llm:\n    provider: ollama\n")

        from unittest.mock import patch
        with patch("atlas.core.config._DEFAULTS_PATH", defaults_path), \
             patch("atlas.core.config._USER_PATH", user_path):
            cfg = load_config()

        assert cfg.llm.provider == "ollama"   # overridden
        assert cfg.llm.model == "gpt-4o"      # preserved from defaults
