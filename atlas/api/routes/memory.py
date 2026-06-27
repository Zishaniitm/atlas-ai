"""Memory endpoints /api/v1/memory. SRS: FR-047–053, NFR-044"""
from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
from atlas.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class DeletePayload(BaseModel):
    memory_id: str | None = None


@router.get("/summary")
async def summary() -> dict[str, object]:
    """SRS: FR-050"""
    try:
        from atlas.memory.manager import what_do_you_remember
        text = await what_do_you_remember()
        return {"status": "ok", "summary": text}
    except Exception as exc:
        return {"status": "error", "summary": str(exc)}


@router.get("/search")
async def search(q: str) -> dict[str, object]:
    """SRS: FR-049"""
    try:
        from atlas.memory.vector_store import search_memory
        results = await search_memory(q)
        return {"status": "ok", "query": q, "results": results}
    except Exception as exc:
        return {"status": "error", "results": [], "error": str(exc)}


@router.delete("/")
async def delete_memory(payload: DeletePayload) -> dict[str, object]:
    """SRS: FR-051, NFR-044"""
    try:
        from atlas.memory.manager import delete_all_data
        result = await delete_all_data()
        return {"status": "ok", **result}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@router.get("/export")
async def export_memory() -> dict[str, object]:
    """SRS: NFR-044 (data portability)"""
    try:
        from atlas.memory.manager import export_all_data
        return {"status": "ok", **(await export_all_data())}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
