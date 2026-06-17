"""
Pydantic Settings loader for ATLAS.

Loads config/defaults.yaml, then merges ~/.atlas/config/user.yaml on top.
Never reads secrets from config — API keys come from OS keychain only.

SRS: NFR-039 (all settings configurable via GUI), NFR-015 (no secrets in config),
     BUG-04 (auth section always present), SRS Appendix 14.2
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


# ── Sub-models ────────────────────────────────────────────────

class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=32768)
    max_iterations: int = Field(default=10, ge=1, le=50)


class VoiceConfig(BaseModel):
    stt_engine: str = "whisper"
    whisper_model: str = "base"
    tts_engine: str = "kokoro"
    persona: str = "atlas_default"
    speaking_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch_offset: int = Field(default=0, ge=-12, le=12)
    wake_word: str = "hey atlas"
    mic_device_index: int | None = None

    @field_validator("tts_engine")
    @classmethod
    def no_coqui(cls, v: str) -> str:
        """BUG-02 fix: coqui-tts is abandoned. Reject it at config load time."""
        if v == "coqui":
            raise ValueError(
                "coqui-tts is abandoned (Jan 2024). Use 'kokoro' instead. (BUG-02)"
            )
        return v


class MemoryConfig(BaseModel):
    working_window: int = Field(default=20, ge=1, le=100)
    vector_db_path: str = "~/.atlas/memory/chroma"
    sqlite_path: str = "~/.atlas/data/atlas.db"
    async_writes: bool = True  # BUG-09: must ALWAYS be True

    @field_validator("async_writes")
    @classmethod
    def enforce_async(cls, v: bool) -> bool:
        """BUG-09 fix: memory writes must never block the response pipeline."""
        if not v:
            raise ValueError(
                "async_writes must be True. Synchronous memory writes block TTS. (BUG-09)"
            )
        return v


class AuthConfig(BaseModel):
    """BUG-04 fix: this section was missing in v1.0.0 of defaults.yaml."""

    primary_method: str = "pin"
    fallback_method: str = "pin"
    two_factor_enabled: bool = False
    voice_print_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    face_distance_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    rate_limit_attempts: int = Field(default=5, ge=1, le=20)
    rate_limit_lockout_sec: int = Field(default=30, ge=5, le=3600)
    full_lockout_after: int = Field(default=10, ge=5, le=50)
    tier2_risk_levels: list[str] = ["critical", "high"]
    tier3_enabled: bool = False
    tier3_check_interval_sec: int = Field(default=30, ge=10, le=300)
    biometric_data_path: str = "~/.atlas/security"


class UIConfig(BaseModel):
    theme: str = "dark"
    hud_opacity: float = Field(default=0.95, ge=0.1, le=1.0)
    always_on_top: bool = False
    font_scale: float = Field(default=1.0, ge=0.8, le=1.5)
    language: str = "en_US"


class APIConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=7770, ge=1024, le=65535)


class SkillsConfig(BaseModel):
    enabled: list[str] = []
    confirm_destructive: bool = True


class NotificationsConfig(BaseModel):
    desktop_toasts: bool = True
    proactive_reminders: bool = True
    reminder_lead_time_min: int = Field(default=15, ge=1, le=60)


class TelemetryConfig(BaseModel):
    crash_reports_local: bool = True
    sentry_enabled: bool = False
    log_retention_days: int = Field(default=30, ge=1, le=365)
    log_dir: str = "~/.atlas/logs"


class UpdatesConfig(BaseModel):
    auto_check: bool = True
    update_channel: str = "stable"
    github_repo: str = "atlas-ai/atlas-ai"


class AtlasConfig(BaseModel):
    """Root config model. Mirrors the atlas: block in defaults.yaml."""

    llm: LLMConfig = LLMConfig()
    voice: VoiceConfig = VoiceConfig()
    memory: MemoryConfig = MemoryConfig()
    auth: AuthConfig = AuthConfig()
    ui: UIConfig = UIConfig()
    api: APIConfig = APIConfig()
    skills: SkillsConfig = SkillsConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    telemetry: TelemetryConfig = TelemetryConfig()
    updates: UpdatesConfig = UpdatesConfig()


# ── Loader ────────────────────────────────────────────────────

_DEFAULTS_PATH = Path(__file__).parents[2] / "config" / "defaults.yaml"
_USER_PATH = Path("~/.atlas/config/user.yaml").expanduser()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively merge override dict into base dict.

    SRS: NFR-039 — user overrides only touch keys they specify;
         all other defaults remain intact.
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> AtlasConfig:
    """
    Load and validate ATLAS configuration.

    Reads config/defaults.yaml, then merges ~/.atlas/config/user.yaml
    on top (if it exists). Validates all values via Pydantic.

    SRS: SRS Appendix 14.2, NFR-039, NFR-015, BUG-04

    Returns:
        Fully validated AtlasConfig instance.

    Raises:
        FileNotFoundError: If defaults.yaml is missing (installation error).
        ValueError: If any config value fails validation.
    """
    if not _DEFAULTS_PATH.exists():
        raise FileNotFoundError(
            f"defaults.yaml not found at {_DEFAULTS_PATH}. "
            "ATLAS installation may be corrupted."
        )

    with _DEFAULTS_PATH.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    if _USER_PATH.exists():
        with _USER_PATH.open() as f:
            user_raw: dict[str, Any] = yaml.safe_load(f) or {}
        raw = _deep_merge(raw, user_raw)

    atlas_block: dict[str, Any] = raw.get("atlas", {})
    return AtlasConfig.model_validate(atlas_block)


def get_data_dir() -> Path:
    """
    Return the ATLAS user data directory, creating it if needed.

    SRS: NFR-020 (restricted permissions on data dir)
    """
    data_dir = Path("~/.atlas").expanduser()
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return data_dir


# Module-level singleton — imported by all other modules
_config: AtlasConfig | None = None


def get_config() -> AtlasConfig:
    """
    Return the cached config singleton. Loads on first call.

    SRS: NFR-039
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> AtlasConfig:
    """
    Force-reload config from disk. Called after the user saves settings in HUD.

    SRS: NFR-039
    """
    global _config
    _config = load_config()
    return _config
