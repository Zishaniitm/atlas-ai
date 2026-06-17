"""
Memory REST endpoints — /api/v1/memory.

Phase 0 stubs — returns appropriate 503 until Phase 1 memory
subsystem is built. Structure is final so HUD can be coded against it.

SRS: FR-047–053 (memory system), FR-050 ('what do you remember'),
     FR-051 (delete memory), NFR-044 (export + delete all data)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atlas.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class MemoryDeletePayload(BaseModel):
    memory_id: str | None = None   # None = delete ALL


@router.get("/summary")
async def memory_summary() -> dict[str, object]:
    """
    Return a summary of what ATLAS remembers about the user.

    SRS: FR-050 ('what do you remember about me?')

    Returns:
        Dict with summary text and entry counts.

    Note:
        Full implementation in Phase 1 (memory subsystem).
        Returns stub response in Phase 0.
    """
    # Phase 0 stub — Phase 1 wires this to MemoryManager
    return {
        "status": "phase0_stub",
        "message": "Memory subsystem implemented in Phase 1.",
        "conversation_count": 0,
        "fact_count": 0,
    }


@router.get("/search")
async def search_memory(q: str) -> dict[str, object]:
    """
    Semantic search over episodic memory.

    SRS: FR-049 (ChromaDB similarity search)

    Args:
        q: Natural language search query.
    """
    return {
        "status": "phase0_stub",
        "query": q,
        "results": [],
    }


@router.delete("/")
async def delete_memory(payload: MemoryDeletePayload) -> dict[str, str]:
    """
    Delete a specific memory entry or all memories.

    SRS: FR-051 (user can delete memory), NFR-044 (delete all data)

    Args:
        payload: memory_id=None deletes all; otherwise deletes by ID.
    """
    if payload.memory_id is None:
        logger.info("memory_delete_all_requested")
        return {"status": "phase0_stub", "message": "Memory deletion implemented in Phase 1."}

    return {
        "status": "phase0_stub",
        "message": f"Delete memory '{payload.memory_id}' implemented in Phase 1.",
    }


@router.get("/export")
async def export_memory() -> dict[str, object]:
    """
    Export all memory data as a structured JSON payload.

    SRS: NFR-044 (right to data portability — export all local data)
    """
    return {
        "status": "phase0_stub",
        "message": "Memory export implemented in Phase 1.",
        "conversations": [],
        "facts": [],
    }
