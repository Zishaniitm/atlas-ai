"""
Voice Persona REST endpoints — /api/v1/personas.

Serves the persona list to the HUD Persona Picker.
Handles active persona selection and preview audio serving.

SRS: FR-010–019 (Voice Persona System), FR-011 (Picker panel),
     FR-012 (5-sec preview), FR-013 (switch without restart),
     NFR-003 (switch <=500ms), NFR-041 (preview <=500ms)
"""

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

_PERSONAS_DIR = Path(__file__).parents[3] / "voice" / "personas"


def _load_all_personas() -> list[dict[str, object]]:
    """
    Discover and parse all .atlasvoice manifest files.

    SRS: NFR-027 (auto-discovered — no code change to add personas)

    Returns:
        List of persona dicts parsed from .atlasvoice YAML files.
    """
    personas: list[dict[str, object]] = []
    for manifest in sorted(_PERSONAS_DIR.glob("*.atlasvoice")):
        try:
            with manifest.open() as f:
                data = yaml.safe_load(f)
            if data and "id" in data:
                personas.append(data)
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("persona_load_failed", file=manifest.name, exc_info=exc)
    return personas


class PersonaSelectPayload(BaseModel):
    persona_id: str


@router.get("/")
async def list_personas() -> list[dict[str, object]]:
    """
    Return all available voice personas.

    Used by the HUD Persona Picker to populate the list.

    SRS: FR-011 (picker shows name, language, accent, gender, style, premium badge)

    Returns:
        List of persona manifest dicts.
    """
    personas = _load_all_personas()
    active = get_config().voice.persona

    # Tag the currently active persona
    for p in personas:
        p["active"] = (p.get("id") == active)

    return personas


@router.get("/{persona_id}")
async def get_persona(persona_id: str) -> dict[str, object]:
    """
    Return details for a single persona by ID.

    SRS: FR-011

    Args:
        persona_id: Persona ID string (e.g. 'nova').

    Raises:
        HTTPException 404: If persona not found.
    """
    for p in _load_all_personas():
        if p.get("id") == persona_id:
            return p
    raise HTTPException(404, f"Persona '{persona_id}' not found.")


@router.get("/{persona_id}/preview")
async def preview_audio(persona_id: str) -> FileResponse:
    """
    Serve the 5-second preview audio file for a persona.

    Response is served directly from disk — no TTS synthesis on request.
    This keeps preview latency under 500ms (NFR-041).

    SRS: FR-012 (5-sec preview), NFR-041 (<=500ms to first audio byte)

    Args:
        persona_id: Persona ID string.

    Raises:
        HTTPException 404: If persona or preview file not found.
    """
    preview_path = _PERSONAS_DIR / f"{persona_id}_preview.mp3"
    if not preview_path.exists():
        raise HTTPException(
            404,
            f"Preview audio for '{persona_id}' not found. "
            "Run 'atlas generate-previews' to create preview files."
        )
    return FileResponse(preview_path, media_type="audio/mpeg")


@router.post("/select")
async def select_persona(payload: PersonaSelectPayload) -> dict[str, str]:
    """
    Set the active voice persona and persist to user config.

    SRS: FR-013 (switch without restart), NFR-003 (<=500ms switch)

    Args:
        payload: PersonaSelectPayload with persona_id.

    Raises:
        HTTPException 404: If persona_id is not found.
    """
    # Validate persona exists
    valid_ids = {str(p["id"]) for p in _load_all_personas()}
    if payload.persona_id not in valid_ids:
        raise HTTPException(404, f"Persona '{payload.persona_id}' not found.")

    # Write to user config
    import yaml as _yaml
    user_cfg = Path("~/.atlas/config/user.yaml").expanduser()
    user_cfg.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    existing: dict[str, object] = {}
    if user_cfg.exists():
        with user_cfg.open() as f:
            existing = _yaml.safe_load(f) or {}

    atlas_block = existing.setdefault("atlas", {})
    atlas_block.setdefault("voice", {})["persona"] = payload.persona_id  # type: ignore[index]

    with user_cfg.open("w") as f:
        _yaml.dump(existing, f, default_flow_style=False)

    reload_config()
    logger.info("persona_selected", persona_id=payload.persona_id)
    return {"status": "ok", "active_persona": payload.persona_id}
