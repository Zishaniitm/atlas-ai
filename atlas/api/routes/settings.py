"""
Settings REST endpoints — /api/v1/settings.

Allows the HUD to read and update ATLAS configuration.
All changes are validated by Pydantic before writing to disk.

SRS: NFR-039 (all settings configurable via GUI — no YAML editing),
     SRS 4.2.6 (versioned API)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atlas.core.config import AtlasConfig, get_config, reload_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class SettingsPatch(BaseModel):
    """Partial settings update payload from HUD."""

    llm_provider: str | None = None
    llm_model: str | None = None
    tts_engine: str | None = None
    persona: str | None = None
    speaking_rate: float | None = None
    theme: str | None = None
    font_scale: float | None = None
    language: str | None = None


@router.get("/")
async def get_settings() -> dict[str, object]:
    """
    Return current ATLAS configuration (safe subset — no secrets).

    SRS: NFR-039

    Returns:
        Dict of current non-sensitive settings.
    """
    cfg = get_config()
    return {
        "llm": {
            "provider": cfg.llm.provider,
            "model": cfg.llm.model,
            "temperature": cfg.llm.temperature,
        },
        "voice": {
            "stt_engine": cfg.voice.stt_engine,
            "whisper_model": cfg.voice.whisper_model,
            "tts_engine": cfg.voice.tts_engine,
            "persona": cfg.voice.persona,
            "speaking_rate": cfg.voice.speaking_rate,
            "pitch_offset": cfg.voice.pitch_offset,
            "wake_word": cfg.voice.wake_word,
        },
        "ui": {
            "theme": cfg.ui.theme,
            "font_scale": cfg.ui.font_scale,
            "language": cfg.ui.language,
            "hud_opacity": cfg.ui.hud_opacity,
        },
        "auth": {
            "primary_method": cfg.auth.primary_method,
            "two_factor_enabled": cfg.auth.two_factor_enabled,
            "tier2_risk_levels": cfg.auth.tier2_risk_levels,
        },
        "notifications": {
            "desktop_toasts": cfg.notifications.desktop_toasts,
            "proactive_reminders": cfg.notifications.proactive_reminders,
        },
        "telemetry": {
            "sentry_enabled": cfg.telemetry.sentry_enabled,
        },
    }


@router.patch("/")
async def patch_settings(patch: SettingsPatch) -> dict[str, str]:
    """
    Apply a partial settings update and reload config.

    SRS: NFR-039 (settings configurable from HUD — no YAML editing)

    Args:
        patch: Partial settings update. Only provided fields are changed.

    Returns:
        Success message.

    Raises:
        HTTPException 400: If a setting value is invalid.
    """
    import yaml
    from pathlib import Path

    user_cfg_path = Path("~/.atlas/config/user.yaml").expanduser()
    user_cfg_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    # Load existing user overrides
    existing: dict[str, object] = {}
    if user_cfg_path.exists():
        with user_cfg_path.open() as f:
            existing = yaml.safe_load(f) or {}

    atlas_block = existing.setdefault("atlas", {})

    # Apply patch fields
    if patch.llm_provider is not None:
        atlas_block.setdefault("llm", {})["provider"] = patch.llm_provider  # type: ignore[index]
    if patch.llm_model is not None:
        atlas_block.setdefault("llm", {})["model"] = patch.llm_model  # type: ignore[index]
    if patch.tts_engine is not None:
        if patch.tts_engine == "coqui":
            raise HTTPException(400, "coqui-tts is abandoned. Use 'kokoro'. (BUG-02)")
        atlas_block.setdefault("voice", {})["tts_engine"] = patch.tts_engine  # type: ignore[index]
    if patch.persona is not None:
        atlas_block.setdefault("voice", {})["persona"] = patch.persona  # type: ignore[index]
    if patch.speaking_rate is not None:
        atlas_block.setdefault("voice", {})["speaking_rate"] = patch.speaking_rate  # type: ignore[index]
    if patch.theme is not None:
        atlas_block.setdefault("ui", {})["theme"] = patch.theme  # type: ignore[index]
    if patch.font_scale is not None:
        atlas_block.setdefault("ui", {})["font_scale"] = patch.font_scale  # type: ignore[index]
    if patch.language is not None:
        atlas_block.setdefault("ui", {})["language"] = patch.language  # type: ignore[index]

    with user_cfg_path.open("w") as f:
        yaml.dump(existing, f, default_flow_style=False)

    try:
        reload_config()
    except ValueError as exc:
        raise HTTPException(400, f"Invalid setting value: {exc}") from exc

    logger.info("settings_updated", patch=patch.model_dump(exclude_none=True))
    return {"status": "ok", "message": "Settings saved and reloaded."}
