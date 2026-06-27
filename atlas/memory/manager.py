"""
Async memory coordinator — ONLY entry point for reading/writing memory.
Enforces BUG-09: writes are always asyncio.create_task(), never awaited
in the response pipeline so TTS is never blocked.

SRS: FR-047–053, BUG-09, NFR-044
"""
from __future__ import annotations
import asyncio
import uuid

from atlas.core.events import AtlasEvent, EventType, get_event_bus
from atlas.memory import sqlite_store, vector_store
from atlas.utils.logging import get_logger

logger = get_logger(__name__)

_session_id: str = str(uuid.uuid4())


async def init_memory() -> None:
    """Initialise both memory backends at startup. SRS: NFR-010"""
    await sqlite_store.init_db()
    vector_store.init_vector_store()
    logger.info("memory_ready", session=_session_id)


def write_turn_fire_and_forget(user_text: str, atlas_text: str) -> None:
    """
    Schedule a conversation turn write WITHOUT awaiting it.

    THIS is the BUG-09 fix in concrete form. The voice pipeline calls
    this AFTER TTS playback — never before. The database write happens
    in the background and the user never waits on it.

    SRS: BUG-09 — the canonical fire-and-forget entry point.
    """
    asyncio.create_task(_write_and_extract(user_text, atlas_text))


async def _write_and_extract(user_text: str, atlas_text: str) -> None:
    """
    Internal: write to SQLite then extract preferences to ChromaDB.
    Runs entirely after TTS has finished playing.
    SRS: BUG-09, FR-047, FR-048
    """
    try:
        await sqlite_store.write_turn_async(_session_id, user_text, atlas_text)
        if _looks_like_preference(user_text):
            await vector_store.store_memory_async(
                text=user_text, category="preference", confidence=0.7
            )
        get_event_bus().emit_nowait(AtlasEvent(
            EventType.MEMORY_WRITE_DONE,
            data={"session": _session_id},
            source="memory_manager",
        ))
    except Exception as exc:
        # BUG-09: a failed memory write must NEVER crash ATLAS
        logger.error("memory_write_failed", exc_info=exc)


def _looks_like_preference(text: str) -> bool:
    """Lightweight heuristic for Phase 1. Replace with LLM extraction in Phase 2."""
    markers = ("i like", "i prefer", "i love", "i hate", "my name is", "i live in",
               "i work at", "i am", "call me")
    return any(m in text.lower() for m in markers)


async def get_working_memory() -> list[dict[str, str]]:
    """
    Return recent turns as LLM-format messages.
    SRS: FR-047, MemoryConfig.working_window
    """
    rows = await sqlite_store.get_recent_turns(_session_id)
    messages: list[dict[str, str]] = []
    for r in rows:
        messages.append({"role": "user",      "content": r.user_text})
        messages.append({"role": "assistant", "content": r.atlas_text})
    return messages


async def what_do_you_remember() -> str:
    """Answer 'What do you remember about me?'. SRS: FR-050"""
    facts = await vector_store.search_memory("user preferences and facts", n_results=10)
    if not facts:
        return "I don't have any saved memories about you yet."
    lines = [f"- {f['text']}" for f in facts]
    return "Here's what I remember:\n" + "\n".join(lines)


async def delete_all_data() -> dict[str, int]:
    """Purge all memory. SRS: FR-051, NFR-044"""
    count = await sqlite_store.delete_all_turns()
    await vector_store.delete_all_memory()
    logger.info("all_data_deleted", rows=count)
    return {"conversation_turns_deleted": count}


async def export_all_data() -> dict[str, object]:
    """Export all memory as JSON-serialisable dict. SRS: NFR-044"""
    return {"conversations": await sqlite_store.export_all_turns()}
