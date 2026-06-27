"""Persona endpoints /api/v1/personas. SRS: FR-010–019"""
from __future__ import annotations
from pathlib import Path
import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from atlas.core.config import get_config, reload_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()
_DIR = Path(__file__).parents[3] / "voice" / "personas"


def _load_all() -> list[dict]:
    out = []
    for f in sorted(_DIR.glob("*.atlasvoice")):
        try:
            data = yaml.safe_load(f.read_text())
            if data and "id" in data:
                out.append(data)
        except Exception:
            pass
    return out


class SelectPayload(BaseModel):
    persona_id: str


@router.get("/")
async def list_personas() -> list[dict]:
    """SRS: FR-011"""
    active = get_config().voice.persona
    personas = _load_all()
    for p in personas:
        p["active"] = (p.get("id") == active)
    return personas


@router.get("/{persona_id}")
async def get_persona(persona_id: str) -> dict:
    for p in _load_all():
        if p.get("id") == persona_id:
            return p
    raise HTTPException(404, f"Persona '{persona_id}' not found.")


@router.get("/{persona_id}/preview")
async def preview(persona_id: str) -> FileResponse:
    """SRS: FR-012, NFR-041 (<=500ms — served from disk, no TTS synthesis)"""
    path = _DIR / f"{persona_id}_preview.mp3"
    if not path.exists():
        raise HTTPException(404, f"Preview for '{persona_id}' not found.")
    return FileResponse(path, media_type="audio/mpeg")


@router.post("/select")
async def select_persona(payload: SelectPayload) -> dict[str, str]:
    """SRS: FR-013 (switch without restart), NFR-003 (<=500ms)"""
    valid = {str(p["id"]) for p in _load_all()}
    if payload.persona_id not in valid:
        raise HTTPException(404, f"Persona '{payload.persona_id}' not found.")
    p = Path("~/.atlas/config/user.yaml").expanduser()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    existing: dict = {}
    if p.exists():
        existing = yaml.safe_load(p.read_text()) or {}
    existing.setdefault("atlas", {}).setdefault("voice", {})["persona"] = payload.persona_id
    p.write_text(yaml.dump(existing, default_flow_style=False))
    reload_config()
    logger.info("persona_selected", id=payload.persona_id)
    return {"status": "ok", "active_persona": payload.persona_id}
