"""WebSocket /ws/conversation — real-time token streaming to HUD. SRS: FR-055, SRS 4.2.6"""
from __future__ import annotations
import asyncio, json
from typing import Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from atlas.core.events import AtlasEvent, EventType, get_event_bus
from atlas.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class _Manager:
    def __init__(self) -> None:
        self._conns: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept(); self._conns.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._conns.remove(ws)

    async def broadcast(self, msg: dict[str, Any]) -> None:
        text = json.dumps(msg)
        dead = []
        for ws in self._conns:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._conns.remove(ws)


manager = _Manager()
_registered = False


def _register() -> None:
    global _registered
    if _registered:
        return
    bus = get_event_bus()

    async def on_token(e: AtlasEvent) -> None:
        await manager.broadcast({"type": "token", "token": e.data.get("token", "")})

    async def on_transcript(e: AtlasEvent) -> None:
        await manager.broadcast({"type": "transcript", "text": e.data.get("text", "")})

    async def on_notify(e: AtlasEvent) -> None:
        await manager.broadcast({"type": "notification",
                                  "title": e.data.get("title", "ATLAS"),
                                  "body":  e.data.get("body", "")})

    bus.subscribe(EventType.LLM_TOKEN_RECEIVED,   on_token)
    bus.subscribe(EventType.STT_TRANSCRIPT_READY, on_transcript)
    bus.subscribe(EventType.NOTIFICATION_REQUEST,  on_notify)
    bus.subscribe(EventType.TTS_STARTED,
                  lambda _: asyncio.create_task(manager.broadcast({"type": "state", "state": "speaking"})))
    bus.subscribe(EventType.TTS_FINISHED,
                  lambda _: asyncio.create_task(manager.broadcast({"type": "state", "state": "idle"})))
    bus.subscribe(EventType.WAKE_WORD_DETECTED,
                  lambda _: asyncio.create_task(manager.broadcast({"type": "state", "state": "listening"})))
    _registered = True


@router.websocket("/ws/conversation")
async def conversation_ws(websocket: WebSocket) -> None:
    """SRS: SRS 4.2.6, FR-055, FR-056"""
    await manager.connect(websocket)
    _register()
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                if json.loads(raw).get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
