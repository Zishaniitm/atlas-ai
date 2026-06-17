"""
WebSocket endpoint for real-time LLM token streaming to the HUD.

The HUD connects to ws://localhost:7770/ws/conversation on startup.
Tokens stream as they arrive from the LLM — never buffered.
Also pushes pipeline state changes (listening, thinking, speaking).

SRS: FR-055 (live transcript streaming), FR-056 (task status),
     SRS 4.2.6 (/ws/conversation), NFR-029 (versioned API backbone)
"""

from __future__ import annotations

import asyncio
import json
from enum import StrEnum, auto
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from atlas.core.events import AtlasEvent, EventType, get_event_bus
from atlas.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class WSMessageType(StrEnum):
    """Message types sent over the WebSocket to the HUD."""

    TOKEN          = auto()   # LLM token streamed in real-time
    TRANSCRIPT     = auto()   # Final STT transcript
    STATE_CHANGE   = auto()   # Pipeline state: idle/listening/thinking/speaking
    NOTIFICATION   = auto()   # Desktop-style in-HUD notification
    ERROR          = auto()   # Error to display in HUD
    PONG           = auto()   # Keepalive reply


class ConnectionManager:
    """
    Manages all active WebSocket connections from the HUD.

    Multiple windows can connect simultaneously (e.g. main HUD + mini widget).

    SRS: FR-054–068 (HUD data delivery), SRS 4.2.6
    """

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await ws.accept()
        self._connections.append(ws)
        logger.info("ws_client_connected", total=len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a disconnected WebSocket."""
        self._connections.remove(ws)
        logger.info("ws_client_disconnected", total=len(self._connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """
        Send a JSON message to all connected HUD windows.

        SRS: FR-055 (live transcript), FR-056 (task status)

        Args:
            message: Dict with at minimum a 'type' key (WSMessageType).
        """
        if not self._connections:
            return
        text = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)

    async def send_token(self, token: str) -> None:
        """
        Stream one LLM token to all HUD windows.

        SRS: FR-055 (real-time token streaming), FR-009 (first token before full response)
        """
        await self.broadcast({"type": WSMessageType.TOKEN, "token": token})

    async def send_state(self, state: str) -> None:
        """
        Push pipeline state change to HUD.

        SRS: FR-056 (HUD shows current task status)
        """
        await self.broadcast({"type": WSMessageType.STATE_CHANGE, "state": state})

    async def send_transcript(self, text: str) -> None:
        """
        Send final STT transcript to HUD.

        SRS: FR-055 (live transcription display)
        """
        await self.broadcast({"type": WSMessageType.TRANSCRIPT, "text": text})

    async def send_notification(self, title: str, body: str) -> None:
        """
        Send in-HUD notification.

        SRS: FR-064 (HUD desktop toast notifications), FR-098
        """
        await self.broadcast({
            "type": WSMessageType.NOTIFICATION,
            "title": title,
            "body": body,
        })


# Module-level singleton — shared across all WebSocket connections
manager = ConnectionManager()


def _register_event_handlers() -> None:
    """
    Subscribe the WebSocket manager to relevant ATLAS events.

    Called once when the first WS client connects.

    SRS: SRS 4.2.6 (event bus → WebSocket bridge)
    """
    bus = get_event_bus()

    async def on_token(event: AtlasEvent) -> None:
        await manager.send_token(event.data.get("token", ""))

    async def on_transcript(event: AtlasEvent) -> None:
        await manager.send_transcript(event.data.get("text", ""))

    async def on_state(event: AtlasEvent) -> None:
        await manager.send_state(event.data.get("state", "idle"))

    async def on_notification(event: AtlasEvent) -> None:
        await manager.send_notification(
            event.data.get("title", "ATLAS"),
            event.data.get("body", ""),
        )

    bus.subscribe(EventType.LLM_TOKEN_RECEIVED,   on_token)
    bus.subscribe(EventType.STT_TRANSCRIPT_READY, on_transcript)
    bus.subscribe(EventType.WAKE_WORD_DETECTED,
                  lambda _: asyncio.create_task(manager.send_state("listening")))
    bus.subscribe(EventType.TTS_STARTED,
                  lambda _: asyncio.create_task(manager.send_state("speaking")))
    bus.subscribe(EventType.TTS_FINISHED,
                  lambda _: asyncio.create_task(manager.send_state("idle")))
    bus.subscribe(EventType.NOTIFICATION_REQUEST, on_notification)


_handlers_registered = False


@router.websocket("/ws/conversation")
async def conversation_ws(websocket: WebSocket) -> None:
    """
    Primary WebSocket endpoint consumed by the ATLAS HUD.

    Streams LLM tokens, pipeline state, STT transcripts, and
    notifications to all connected HUD windows in real time.

    SRS: SRS 4.2.6, FR-055, FR-056, NFR-029

    Protocol (JSON messages sent by server):
        { "type": "token",        "token": "..." }
        { "type": "transcript",   "text": "..." }
        { "type": "state_change", "state": "listening|thinking|speaking|idle" }
        { "type": "notification", "title": "...", "body": "..." }

    Messages accepted from HUD client:
        { "type": "ping" }   → server replies { "type": "pong" }
    """
    global _handlers_registered

    await manager.connect(websocket)

    if not _handlers_registered:
        _register_event_handlers()
        _handlers_registered = True

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": WSMessageType.PONG}))
            except json.JSONDecodeError:
                pass  # ignore malformed messages

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.debug("ws_disconnected")
