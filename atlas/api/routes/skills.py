"""
Skills REST endpoints — /api/v1/skills.

Allows the HUD to list available skills, check their status,
and enable or disable them from the settings panel.

Phase 0 stub for skill execution — full dispatch in Phase 1.

SRS: FR-056 (HUD shows which skill is executing),
     FR-069-076 (skill configuration),
     NFR-025 (zero core-code changes to add a skill),
     NFR-039 (all settings configurable via GUI)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atlas.core.config import get_config, reload_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()

# Skills that ship with ATLAS v1.0 (Phase 1 builds them)
_BUILTIN_SKILLS = [
    {"id": "file_manager",   "name": "File Manager",    "description": "Create, move, delete, search files & folders",          "phase": 1, "permissions": ["filesystem.read","filesystem.write"]},
    {"id": "app_launcher",   "name": "App Launcher",    "description": "Open, close, focus applications by name",               "phase": 1, "permissions": ["process.execute"]},
    {"id": "web_search",     "name": "Web Search",      "description": "Search the web and summarise top results",             "phase": 1, "permissions": ["network.outbound"]},
    {"id": "web_browsing",   "name": "Web Browsing",    "description": "Autonomously browse URLs, click, fill forms",          "phase": 1, "permissions": ["network.outbound","browser.control"]},
    {"id": "code_executor",  "name": "Code Executor",   "description": "Write and run Python/shell scripts in a sandbox",      "phase": 1, "permissions": ["process.execute","filesystem.write"]},
    {"id": "system_monitor", "name": "System Monitor",  "description": "Report CPU, RAM, disk, battery stats",                "phase": 1, "permissions": ["system.monitor"]},
    {"id": "calculator",     "name": "Calculator",      "description": "Perform calculations and unit conversions",            "phase": 1, "permissions": []},
    {"id": "wikipedia",      "name": "Wikipedia",       "description": "Retrieve and summarise Wikipedia articles",            "phase": 1, "permissions": ["network.outbound"]},
    {"id": "weather",        "name": "Weather",         "description": "Current weather and 7-day forecast by city",          "phase": 1, "permissions": ["network.outbound"]},
    {"id": "datetime",       "name": "Date & Time",     "description": "Current time/date, alarms, countdown timers",         "phase": 1, "permissions": []},
    {"id": "clipboard",      "name": "Clipboard",       "description": "Read and write system clipboard",                     "phase": 1, "permissions": ["clipboard.read","clipboard.write"]},
    {"id": "screenshot_ocr", "name": "Screenshot+OCR",  "description": "Capture screen and extract text via OCR",             "phase": 1, "permissions": ["screen.capture"]},
    {"id": "volume_control", "name": "Volume Control",  "description": "Adjust system audio volume",                         "phase": 1, "permissions": ["audio.output"]},
]


class SkillTogglePayload(BaseModel):
    skill_id: str
    enabled: bool


@router.get("/")
async def list_skills() -> list[dict[str, object]]:
    """
    Return all available skills with enabled/disabled status.

    SRS: NFR-025 (auto-discovery), NFR-039 (GUI control)

    Returns:
        List of skill dicts including enabled flag from user config.
    """
    enabled_ids = set(get_config().skills.enabled)
    skills_out = []
    for skill in _BUILTIN_SKILLS:
        skills_out.append({
            **skill,
            "enabled": skill["id"] in enabled_ids,
            "available": True,   # Phase 0: all shown, none execute yet
        })
    return skills_out


@router.get("/{skill_id}")
async def get_skill(skill_id: str) -> dict[str, object]:
    """
    Return details for a single skill.

    SRS: FR-056

    Args:
        skill_id: Skill identifier string.

    Raises:
        HTTPException 404: If skill is not found.
    """
    for skill in _BUILTIN_SKILLS:
        if skill["id"] == skill_id:
            enabled_ids = set(get_config().skills.enabled)
            return {**skill, "enabled": skill_id in enabled_ids}
    raise HTTPException(404, f"Skill '{skill_id}' not found.")


@router.patch("/toggle")
async def toggle_skill(payload: SkillTogglePayload) -> dict[str, object]:
    """
    Enable or disable a skill and persist to user config.

    SRS: NFR-039 (GUI control over skills)

    Args:
        payload: SkillTogglePayload with skill_id and enabled flag.

    Raises:
        HTTPException 404: If skill_id is not a known skill.
    """
    valid_ids = {s["id"] for s in _BUILTIN_SKILLS}
    if payload.skill_id not in valid_ids:
        raise HTTPException(404, f"Skill '{payload.skill_id}' not found.")

    import yaml
    user_cfg = Path("~/.atlas/config/user.yaml").expanduser()
    user_cfg.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    existing: dict[str, object] = {}
    if user_cfg.exists():
        with user_cfg.open() as f:
            existing = yaml.safe_load(f) or {}

    atlas_block = existing.setdefault("atlas", {})
    skills_block = atlas_block.setdefault("skills", {})  # type: ignore[union-attr]
    current_enabled: list[str] = skills_block.get("enabled", [s["id"] for s in _BUILTIN_SKILLS])  # type: ignore[assignment]

    if payload.enabled and payload.skill_id not in current_enabled:
        current_enabled.append(payload.skill_id)
    elif not payload.enabled and payload.skill_id in current_enabled:
        current_enabled.remove(payload.skill_id)

    skills_block["enabled"] = current_enabled

    with user_cfg.open("w") as f:
        yaml.dump(existing, f, default_flow_style=False)

    reload_config()
    logger.info("skill_toggled", skill_id=payload.skill_id, enabled=payload.enabled)
    return {"status": "ok", "skill_id": payload.skill_id, "enabled": payload.enabled}


@router.post("/{skill_id}/execute")
async def execute_skill(skill_id: str, args: dict[str, object]) -> dict[str, object]:
    """
    Execute a skill directly via REST (debug/testing endpoint).

    Phase 0 stub — full execution implemented in Phase 1 Orchestrator.

    SRS: FR-113 (skill chaining via Orchestrator in Phase 1)

    Args:
        skill_id: Skill to execute.
        args: Skill input arguments dict.
    """
    logger.info("skill_execute_requested", skill_id=skill_id, args=args)
    return {
        "status": "phase0_stub",
        "skill_id": skill_id,
        "message": "Skill execution implemented in Phase 1 via LangChain Orchestrator.",
    }
