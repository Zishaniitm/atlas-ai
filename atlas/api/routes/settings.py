"""Settings endpoints /api/v1/settings. SRS: NFR-039"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from atlas.core.config import get_config, reload_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class SettingsPatch(BaseModel):
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
    cfg = get_config()
    return {
        "llm":   {"provider": cfg.llm.provider, "model": cfg.llm.model},
        "voice": {"tts_engine": cfg.voice.tts_engine, "persona": cfg.voice.persona,
                  "speaking_rate": cfg.voice.speaking_rate, "wake_word": cfg.voice.wake_word},
        "ui":    {"theme": cfg.ui.theme, "font_scale": cfg.ui.font_scale, "language": cfg.ui.language},
        "auth":  {"primary_method": cfg.auth.primary_method,
                  "two_factor_enabled": cfg.auth.two_factor_enabled},
        "notifications": {"desktop_toasts": cfg.notifications.desktop_toasts},
        "telemetry":     {"sentry_enabled": cfg.telemetry.sentry_enabled},
    }


@router.patch("/")
async def patch_settings(patch: SettingsPatch) -> dict[str, str]:
    import yaml
    from pathlib import Path
    p = Path("~/.atlas/config/user.yaml").expanduser()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    existing: dict = {}
    if p.exists():
        with p.open() as f:
            existing = yaml.safe_load(f) or {}
    b = existing.setdefault("atlas", {})
    if patch.tts_engine == "coqui":
        raise HTTPException(400, "coqui-tts is abandoned. Use 'kokoro'. (BUG-02)")
    if patch.llm_provider:  b.setdefault("llm",   {})["provider"]       = patch.llm_provider
    if patch.llm_model:     b.setdefault("llm",   {})["model"]           = patch.llm_model
    if patch.tts_engine:    b.setdefault("voice", {})["tts_engine"]      = patch.tts_engine
    if patch.persona:       b.setdefault("voice", {})["persona"]          = patch.persona
    if patch.speaking_rate: b.setdefault("voice", {})["speaking_rate"]   = patch.speaking_rate
    if patch.theme:         b.setdefault("ui",    {})["theme"]            = patch.theme
    if patch.font_scale:    b.setdefault("ui",    {})["font_scale"]       = patch.font_scale
    if patch.language:      b.setdefault("ui",    {})["language"]         = patch.language
    with p.open("w") as f:
        yaml.dump(existing, f, default_flow_style=False)
    try:
        reload_config()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    logger.info("settings_updated")
    return {"status": "ok"}
