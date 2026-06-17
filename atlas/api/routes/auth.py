"""
Auth REST endpoints — /api/v1/auth.

Used by the HUD for enrolment, verification status, and method management.
Actual verification is done by the security module — this is a thin API layer.

SRS: FR-079 (locked startup), FR-094 (enrol/update/delete from settings),
     FR-095 (rate limiting), FR-097 (fallback chain)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atlas.security.auth import pin as pin_auth
from atlas.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


class PINPayload(BaseModel):
    pin: str


class VerifyPayload(BaseModel):
    method: str   # pin | voice_print | face | hello | fido2
    pin: str | None = None


@router.get("/status")
async def auth_status() -> dict[str, object]:
    """
    Return current auth enrolment status for all methods.

    SRS: FR-094 (user can see what is enrolled)
    """
    return {
        "pin_enrolled": pin_auth.is_enrolled(),
        "voice_print_enrolled": False,   # Phase 1
        "face_enrolled": False,          # Phase 1
        "hello_available": False,        # Phase 1
        "fido2_enrolled": False,         # Phase 3
    }


@router.post("/enrol/pin")
async def enrol_pin(payload: PINPayload) -> dict[str, str]:
    """
    Enrol or replace the PIN.

    SRS: FR-079, FR-080, FR-094

    Args:
        payload: PINPayload with the new PIN string.

    Raises:
        HTTPException 400: If PIN is too short.
    """
    success = await pin_auth.enrol(payload.pin)
    if not success:
        raise HTTPException(400, "PIN must be 4–64 characters.")
    logger.info("api_pin_enrolled")
    return {"status": "ok", "message": "PIN enrolled successfully."}


@router.post("/verify/pin")
async def verify_pin(payload: PINPayload) -> dict[str, object]:
    """
    Verify a PIN and return auth result.

    SRS: FR-079, FR-080, FR-096 (rate limiting enforced inside pin_auth.verify)

    Returns:
        Dict with 'success' bool and 'message' string.
    """
    result = await pin_auth.verify(payload.pin)
    if not result.success:
        # Do NOT raise HTTPException — return 200 with success=False
        # so the HUD can show the specific error message (remaining tries, lockout)
        logger.warning("api_pin_verify_failed", message=result.message)
    return {
        "success": result.success,
        "message": result.message,
        "locked_until": result.locked_until,
    }


@router.delete("/pin")
async def delete_pin() -> dict[str, str]:
    """
    Delete the enrolled PIN.

    SRS: FR-095 (user can delete any auth method)

    Raises:
        HTTPException 404: If no PIN is enrolled.
    """
    deleted = await pin_auth.delete()
    if not deleted:
        raise HTTPException(404, "No PIN enrolled.")
    logger.info("api_pin_deleted")
    return {"status": "ok", "message": "PIN removed."}
