"""Unit tests for atlas.core.config. SRS: Section 11.1 (>=90% coverage)"""
from __future__ import annotations
import pytest
from unittest.mock import patch
from atlas.core.config import AtlasConfig, LLMConfig, VoiceConfig, MemoryConfig, AuthConfig, load_config


class TestVoiceConfig:
    def test_valid_tts_engine_accepted(self):
        v = VoiceConfig(tts_engine="kokoro")
        assert v.tts_engine == "kokoro"

    def test_coqui_rejected(self):
        """BUG-02: coqui-tts is abandoned — must be rejected at config load."""
        with pytest.raises(ValueError, match="coqui"):
            VoiceConfig(tts_engine="coqui")

    def test_speaking_rate_clamped(self):
        v = VoiceConfig(speaking_rate=0.5)
        assert v.speaking_rate == 0.5

    def test_speaking_rate_out_of_range(self):
        with pytest.raises(ValueError):
            VoiceConfig(speaking_rate=0.1)

    def test_pitch_offset_range(self):
        with pytest.raises(ValueError):
            VoiceConfig(pitch_offset=13)


class TestMemoryConfig:
    def test_async_writes_true_accepted(self):
        m = MemoryConfig(async_writes=True)
        assert m.async_writes is True

    def test_async_writes_false_rejected(self):
        """BUG-09: synchronous memory writes block TTS — never allowed."""
        with pytest.raises(ValueError, match="BUG-09"):
            MemoryConfig(async_writes=False)


class TestAuthConfig:
    def test_auth_section_present(self):
        """BUG-04: auth section must always be present in config."""
        cfg = AtlasConfig()
        assert cfg.auth is not None
        assert cfg.auth.primary_method == "pin"

    def test_default_threshold_values(self):
        a = AuthConfig()
        assert a.voice_print_threshold == 0.92
        assert a.face_distance_threshold == 0.45

    def test_rate_limit_defaults(self):
        a = AuthConfig()
        assert a.rate_limit_attempts == 5
        assert a.rate_limit_lockout_sec == 30

    def test_tier2_risk_levels_default(self):
        a = AuthConfig()
        assert "critical" in a.tier2_risk_levels
        assert "high" in a.tier2_risk_levels


class TestLoadConfig:
    def test_load_returns_atlas_config(self, tmp_path):
        from pathlib import Path
        import yaml, shutil
        defaults = Path(__file__).parents[2] / "config" / "defaults.yaml"
        if not defaults.exists():
            pytest.skip("defaults.yaml not present in test environment")
        cfg = load_config()
        assert isinstance(cfg, AtlasConfig)

    def test_deep_merge_user_overrides_default(self, tmp_path):
        import yaml
        from atlas.core.config import _deep_merge
        base     = {"atlas": {"llm": {"provider": "openai"}, "voice": {"persona": "atlas_default"}}}
        override = {"atlas": {"llm": {"provider": "ollama"}}}
        merged   = _deep_merge(base, override)
        assert merged["atlas"]["llm"]["provider"]    == "ollama"
        assert merged["atlas"]["voice"]["persona"]   == "atlas_default"
