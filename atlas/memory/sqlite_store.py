"""
SQLite conversation history store — async, WAL mode for crash safety.

All writes are fire-and-forget after the response is delivered (BUG-09).
SRS: FR-047, NFR-035 (WAL mode), BUG-09 (async writes only)
"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Float, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from atlas.core.config import get_config
from atlas.utils.logging import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    pass


class ConversationTurnRow(Base):
    """One row per user↔ATLAS exchange. SRS: FR-047, FR-052"""
    __tablename__ = "conversation_turns"
    id: int          = Column(Integer, primary_key=True, autoincrement=True)
    session_id: str  = Column(String(64), nullable=False, index=True)
    user_text: str   = Column(Text, nullable=False)
    atlas_text: str  = Column(Text, nullable=False)
    timestamp: float = Column(Float, nullable=False, index=True)
    confidence: float = Column(Float, default=1.0)


_engine = None
_SessionLocal: sessionmaker | None = None


def _get_db_path() -> Path:
    return Path(get_config().memory.sqlite_path).expanduser()


async def init_db() -> None:
    """
    Initialise async engine in WAL mode and create tables.
    SRS: NFR-035 (WAL = survives power loss)
    """
    global _engine, _SessionLocal
    db_path = _get_db_path()
    db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    async with _engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.run_sync(Base.metadata.create_all)
    _SessionLocal = sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)
    logger.info("sqlite_init", path=str(db_path))


async def write_turn_async(
    session_id: str,
    user_text: str,
    atlas_text: str,
    confidence: float = 1.0,
) -> None:
    """
    Write one conversation turn. Caller must use asyncio.create_task().
    SRS: BUG-09 — caller is responsible for fire-and-forget scheduling.
    """
    if _SessionLocal is None:
        raise RuntimeError("Call init_db() first.")
    async with _SessionLocal() as session:
        session.add(ConversationTurnRow(
            session_id=session_id,
            user_text=user_text,
            atlas_text=atlas_text,
            timestamp=time.time(),
            confidence=confidence,
        ))
        await session.commit()
    logger.debug("turn_written", session=session_id)


async def get_recent_turns(session_id: str, limit: int | None = None) -> list[ConversationTurnRow]:
    """Fetch recent turns for working memory. SRS: FR-047"""
    if _SessionLocal is None:
        raise RuntimeError("Call init_db() first.")
    window = limit or get_config().memory.working_window
    async with _SessionLocal() as session:
        stmt = (
            select(ConversationTurnRow)
            .where(ConversationTurnRow.session_id == session_id)
            .order_by(ConversationTurnRow.timestamp.desc())
            .limit(window)
        )
        rows = list((await session.execute(stmt)).scalars().all())
        return list(reversed(rows))


async def delete_all_turns() -> int:
    """Delete all conversation history. SRS: FR-051, NFR-044"""
    if _SessionLocal is None:
        raise RuntimeError("Call init_db() first.")
    async with _SessionLocal() as session:
        rows = list((await session.execute(select(ConversationTurnRow))).scalars().all())
        for row in rows:
            await session.delete(row)
        await session.commit()
    logger.info("all_turns_deleted", count=len(rows))
    return len(rows)


async def export_all_turns() -> list[dict[str, Any]]:
    """Export all history. SRS: NFR-044 (data portability)"""
    if _SessionLocal is None:
        raise RuntimeError("Call init_db() first.")
    async with _SessionLocal() as session:
        rows = (await session.execute(
            select(ConversationTurnRow).order_by(ConversationTurnRow.timestamp)
        )).scalars().all()
        return [
            {"session_id": r.session_id, "user_text": r.user_text,
             "atlas_text": r.atlas_text, "timestamp": r.timestamp}
            for r in rows
        ]
