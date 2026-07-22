"""
Voice router — Person 3 (Ignacio) — AI Landlord Agent

Endpoints:
  POST /voice/repair/{repair_id}/confirm   -> two-leg contractor+tenant flow
  POST /voice/rent/{tenant_id}/remind      -> voice rent reminder (uses ledger)
  POST /voice/call                         -> raw CallRequest (flexible/manual)
  POST /voice/webhook                      -> ActionLayer callback
  GET  /voice/calls                        -> demo: list all calls
  GET  /voice/calls/{call_id}              -> demo: poll one call

Wire it up in app/main.py with:
    from app.routers import voice
    app.include_router(voice.router)

Runs in simulation mode with no secrets. Flip VOICE_SIMULATION=false to go live.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from app.services import voice_service
from app.services.voice_service import CallRequest, CallType

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/repair/{repair_id}/confirm")
async def confirm_repair(repair_id: str, language: str = Body("en", embed=True)):
    """Call the contractor to confirm the booked slot, then confirm with the tenant."""
    # Lazy import avoids a circular import with main at module load time.
    from app.main import REPAIRS

    repair = REPAIRS.get(repair_id)
    if not repair:
        raise HTTPException(404, "unknown repair id")
    if not (repair.get("booked_slot") or repair.get("slots")):
        raise HTTPException(400, "no slot to confirm for this repair")
    return await voice_service.run_repair_confirm(repair, language=language)


@router.post("/rent/{tenant_id}/remind")
async def remind_rent(tenant_id: str, language: str = Body("en", embed=True)):
    """Place a voice rent reminder to a tenant, using the mock ledger."""
    from app.services import rent_ledger

    if not rent_ledger.get_status(tenant_id):
        raise HTTPException(404, "unknown tenant")
    result = await voice_service.place_call(CallRequest(
        call_type=CallType.RENT_REMINDER, reference_id=tenant_id, language=language,
    ))
    return result.model_dump()


@router.post("/call")
async def raw_call(req: CallRequest):
    """Escape hatch: place any call by passing a full CallRequest."""
    result = await voice_service.place_call(req)
    return result.model_dump()


@router.post("/webhook")
async def actionlayer_webhook(request: Request):
    """ActionLayer posts the transcript + outcome here when a call ends."""
    payload = await request.json()
    # Always 200 so AL doesn't retry-storm during the demo.
    return voice_service.handle_webhook(payload)


@router.get("/calls")
async def list_calls():
    return [c.model_dump() for c in voice_service.list_calls()]


@router.get("/calls/{call_id}")
async def get_call(call_id: str):
    result = voice_service.get_call(call_id)
    if result is None:
        raise HTTPException(404, "call not found")
    return result.model_dump()
