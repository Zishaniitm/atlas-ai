"""Auth endpoints /api/v1/auth. SRS: FR-079, FR-094, FR-096"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from atlas.security.auth import pin as pin_auth
from atlas.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class PINPayload(BaseModel):
    pin: str


@router.get("/status")
async def auth_status() -> dict[str, object]:
    """SRS: FR-094"""
    return {
        "pin_enrolled":         pin_auth.is_enrolled(),
        "voice_print_enrolled": False,   # Phase 1
        "face_enrolled":        False,   # Phase 1
        "hello_available":      False,   # Phase 2
        "fido2_enrolled":       False,   # Phase 3
    }


@router.post("/enrol/pin")
async def enrol_pin(payload: PINPayload) -> dict[str, str]:
    """SRS: FR-079, FR-080"""
    if not await pin_auth.enrol(payload.pin):
        raise HTTPException(400, "PIN must be 4–64 characters.")
    return {"status": "ok", "message": "PIN enrolled successfully."}


@router.post("/verify/pin")
async def verify_pin(payload: PINPayload) -> dict[str, object]:
    """SRS: FR-096 — rate limiting enforced inside pin_auth.verify"""
    result = await pin_auth.verify(payload.pin)
    return {"success": result.success, "message": result.message,
            "locked_until": result.locked_until}


@router.delete("/pin")
async def delete_pin() -> dict[str, str]:
    """SRS: FR-095"""
    if not await pin_auth.delete():
        raise HTTPException(404, "No PIN enrolled.")
    return {"status": "ok", "message": "PIN removed."}
