"""
ATLAS config system — Pydantic Settings loader.
Merges config/defaults.yaml with ~/.atlas/config/user.yaml.
SRS: NFR-039, NFR-015 (no secrets in config), BUG-04 (auth section),
     BUG-02 (reject coqui), BUG-09 (enforce async_writes)
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, Field, field_validator

_DEFAULTS_PATH = Path(__file__).parents[2] / "config" / "defaults.yaml"
_USER_PATH     = Path("~/.atlas/config/user.yaml").expanduser()


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(2048, ge=1, le=32768)
    max_iterations: int = Field(10, ge=1, le=50)


class VoiceConfig(BaseModel):
    stt_engine: str = "whisper"
    whisper_model: str = "base"
    tts_engine: str = "kokoro"
    persona: str = "atlas_default"
    speaking_rate: float = Field(1.0, ge=0.5, le=2.0)
    pitch_offset: int = Field(0, ge=-12, le=12)
    wake_word: str = "hey atlas"
    mic_device_index: int | None = None

    @field_validator("tts_engine")
    @classmethod
    def no_coqui(cls, v: str) -> str:
        """BUG-02: coqui-tts is abandoned. Reject at config load time."""
        if v == "coqui":
            raise ValueError("coqui-tts is abandoned (Jan 2024). Use 'kokoro'. (BUG-02)")
        return v


class MemoryConfig(BaseModel):
    working_window: int = Field(20, ge=1, le=100)
    vector_db_path: str = "~/.atlas/memory/chroma"
    sqlite_path: str = "~/.atlas/data/atlas.db"
    async_writes: bool = True

    @field_validator("async_writes")
    @classmethod
    def must_be_async(cls, v: bool) -> bool:
        """BUG-09: synchronous memory writes block TTS — never allowed."""
        if not v:
            raise ValueError("async_writes must be True — sync writes block TTS. (BUG-09)")
        return v


class AuthConfig(BaseModel):
    """BUG-04: this section was missing in SRS v1.0.0."""
    primary_method: str = "pin"
    fallback_method: str = "pin"
    two_factor_enabled: bool = False
    voice_print_threshold: float = Field(0.92, ge=0.0, le=1.0)
    face_distance_threshold: float = Field(0.45, ge=0.0, le=1.0)
    rate_limit_attempts: int = Field(5, ge=1, le=20)
    rate_limit_lockout_sec: int = Field(30, ge=5, le=3600)
    full_lockout_after: int = Field(10, ge=5, le=50)
    tier2_risk_levels: list[str] = ["critical", "high"]
    tier3_enabled: bool = False
    tier3_check_interval_sec: int = Field(30, ge=10, le=300)
    biometric_data_path: str = "~/.atlas/security"


class UIConfig(BaseModel):
    theme: str = "dark"
    hud_opacity: float = Field(0.95, ge=0.1, le=1.0)
    always_on_top: bool = False
    font_scale: float = Field(1.0, ge=0.8, le=1.5)
    language: str = "en_US"


class APIConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(7770, ge=1024, le=65535)


class SkillsConfig(BaseModel):
    enabled: list[str] = []
    confirm_destructive: bool = True


class NotificationsConfig(BaseModel):
    desktop_toasts: bool = True
    proactive_reminders: bool = True
    reminder_lead_time_min: int = Field(15, ge=1, le=60)


class TelemetryConfig(BaseModel):
    crash_reports_local: bool = True
    sentry_enabled: bool = False
    log_retention_days: int = Field(30, ge=1, le=365)
    log_dir: str = "~/.atlas/logs"


class UpdatesConfig(BaseModel):
    auto_check: bool = True
    update_channel: str = "stable"
    github_repo: str = "atlas-ai/atlas-ai"


class AtlasConfig(BaseModel):
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


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> AtlasConfig:
    if not _DEFAULTS_PATH.exists():
        raise FileNotFoundError(f"defaults.yaml not found at {_DEFAULTS_PATH}")
    with _DEFAULTS_PATH.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}
    if _USER_PATH.exists():
        with _USER_PATH.open() as f:
            raw = _deep_merge(raw, yaml.safe_load(f) or {})
    return AtlasConfig.model_validate(raw.get("atlas", {}))


def get_data_dir() -> Path:
    d = Path("~/.atlas").expanduser()
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


_config: AtlasConfig | None = None


def get_config() -> AtlasConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> AtlasConfig:
    global _config
    _config = load_config()
    return _config
