"""Skills endpoints /api/v1/skills. SRS: NFR-025, NFR-039"""
from __future__ import annotations
from fastapi import APIRouter
from atlas.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/")
async def list_skills() -> dict[str, object]:
    """SRS: NFR-025 — returns all discovered+enabled skills"""
    try:
        from atlas.core.orchestrator import discover_skills
        skills = discover_skills()
        return {
            "status": "ok",
            "count":  len(skills),
            "skills": [
                {
                    "name":        cls.name,
                    "description": cls.description,
                    "risk_level":  cls.risk_level,
                    "permissions": cls.permissions,
                }
                for cls in skills.values()
            ],
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@router.get("/{skill_name}")
async def get_skill(skill_name: str) -> dict[str, object]:
    """Return schema for a single skill."""
    from atlas.core.orchestrator import discover_skills
    from fastapi import HTTPException
    skills = discover_skills()
    cls = skills.get(skill_name)
    if cls is None:
        raise HTTPException(404, f"Skill '{skill_name}' not found.")
    return {
        "name":        cls.name,
        "description": cls.description,
        "parameters":  cls.parameters,
        "permissions": cls.permissions,
        "risk_level":  cls.risk_level,
        "tool_schema": cls.to_tool_schema(),
    }
