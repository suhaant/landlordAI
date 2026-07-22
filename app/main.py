# ponytail: stand-in for the team's endpoint file so the demo runs
# end-to-end. Routes match the agreed contract: POST /repairs/submit,
# POST /repairs/{id}/book, GET /rent/status/{id}, POST /rent/remind/{id}.
# The agent auto-books on submit; /repairs/{id}/book remains for rebooking.
import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.models import Severity
from app.services import mock_provider, rent_ledger, vision, voice_service

from app.routers import voice

app = FastAPI(title="AI Landlord Agent")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(voice.router)

REPAIRS: dict[str, dict] = {}
ACTIVITY: list[dict] = []  # agent action feed shown on the landlord page

EMERGENCY_WORDS = ("leak", "burst", "flood", "no heat", "sparks", "smoke",
                   "gas", "sewage", "no power", "locked out")
CATEGORY_WORDS = {"plumbing": ("leak", "pipe", "drain", "toilet", "sink", "water"),
                  "electrical": ("outlet", "power", "light", "sparks", "breaker")}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(kind: str, text: str, **extra) -> None:
    ACTIVITY.append({"ts": now(), "kind": kind, "text": text, **extra})


class RepairRequest(BaseModel):
    tenant_id: str
    description: str
    urgency: str | None = None  # auto-classified if omitted


class BookingRequest(BaseModel):
    slot_id: str


def fmt(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%a %d %b, %H:%M")


def severity_to_urgency(severity: Severity) -> str:
    return (
        "emergency"
        if severity in (Severity.HIGH, Severity.EMERGENCY)
        else "routine"
    )


def auto_dispatch_enabled() -> bool:
    return os.getenv("DEMO_AUTO_DISPATCH", "false").lower() == "true"


async def parse_repair_submission(request: Request) -> tuple[RepairRequest, bytes | None]:
    content_type = request.headers.get("content-type", "")
    photo_bytes = None

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        tenant_id = str(form.get("tenant_id", "")).strip()
        description = str(form.get("description", "")).strip()
        urgency = str(form.get("urgency", "")).strip() or None
        photo = form.get("photo")
        if photo and hasattr(photo, "read"):
            photo_bytes = await photo.read()
    else:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(400, "request must be JSON or multipart form data") from exc
        tenant_id = str(payload.get("tenant_id", "")).strip()
        description = str(payload.get("description", "")).strip()
        urgency = payload.get("urgency")

    if not tenant_id or not description:
        raise HTTPException(422, "tenant_id and description are required")
    return RepairRequest(
        tenant_id=tenant_id, description=description, urgency=urgency
    ), photo_bytes


def create_repair(req: RepairRequest, severity: Severity | None = None) -> dict:
    tenant = rent_ledger.get_status(req.tenant_id)
    if not tenant:
        raise HTTPException(404, "unknown tenant")
    text = req.description.lower()
    urgency = req.urgency or (
        severity_to_urgency(severity)
        if severity
        else ("emergency" if any(w in text for w in EMERGENCY_WORDS) else "routine")
    )
    if urgency not in ("routine", "emergency"):
        raise HTTPException(422, "urgency must be routine or emergency")
    category = next((cat for cat, words in CATEGORY_WORDS.items()
                     if any(w in text for w in words)), "general")
    repair_id = f"r{len(REPAIRS) + 1}"
    slots = mock_provider.get_available_slots(urgency, category, repair_id)

    # Prefer the specialist for the detected trade, then optimize within that pool.
    specialist_slots = [
        candidate for candidate in slots
        if candidate.get("contractor_trade") == category
    ]
    candidate_slots = specialist_slots or slots
    if urgency == "emergency":
        slot = min(candidate_slots, key=lambda candidate: candidate["start"])
        reason = "the soonest specialist emergency slot"
    else:
        slot = max(
            candidate_slots,
            key=lambda candidate: (
                candidate["rating"], -candidate["callout_fee"]
            ),
        )
        reason = "the highest-rated specialist for the job"

    when = fmt(slot["start"])
    severity_value = severity.value if severity else (
        Severity.EMERGENCY.value if urgency == "emergency" else Severity.LOW.value
    )
    timeline = [
        {"ts": now(), "text": f"Got it — I’ve logged your report: “{req.description}”"},
        {
            "ts": now(),
            "text": (
                f"{'Vision assessed' if severity else 'I triaged'} this as "
                f"{severity_value} severity / {category}. "
                "Checking contractor availability…"
            ),
        },
        {"ts": now(), "text": f"✅ Booked {slot['contractor']} ({slot['rating']}★) "
                              f"for {when} — I picked {reason}. "
                              f"They’ll need about {slot['window_hours']}h access."},
    ]
    REPAIRS[repair_id] = {"id": repair_id, "tenant_id": req.tenant_id,
                          "description": req.description, "severity": severity_value,
                          "urgency": urgency,
                          "category": category, "status": "booked",
                          "dispatch_status": (
                              "queued" if auto_dispatch_enabled()
                              else "not_requested"
                          ),
                          "booked_slot": slot, "timeline": timeline,
                          "slots": slots, "has_photo": severity is not None}
    log("repair", f"🔧 {tenant['name']} (unit {tenant['unit']}) reported: "
                  f"“{req.description}”", repair_id=repair_id)
    log("triage", f"🧠 Triaged {repair_id} as {severity_value} / {category} — "
                  f"{len(slots)} slots found across "
                  f"{len({s['contractor'] for s in slots})} contractors",
        repair_id=repair_id)
    log("booking", f"📅 Auto-booked {slot['contractor']} ({slot['rating']}★, "
                   f"${slot['callout_fee']} callout) for {when} — {reason}. "
                   f"Tenant notified.", repair_id=repair_id)
    return REPAIRS[repair_id]


async def dispatch_repair(repair_id: str) -> None:
    repair = REPAIRS.get(repair_id)
    if not repair:
        return

    repair["dispatch_status"] = "calling"
    repair["timeline"].append({
        "ts": now(),
        "text": (
            f"📞 Calling {repair['booked_slot']['contractor']} on the landlord’s "
            "behalf to confirm the repair."
        ),
    })
    log(
        "dispatch",
        f"📞 Contacting {repair['booked_slot']['contractor']} for {repair_id}.",
        repair_id=repair_id,
    )

    try:
        result = await voice_service.run_repair_confirm(repair)
        repair["dispatch_status"] = (
            "confirmed" if result["confirmed"] else "needs_follow_up"
        )
        repair["call_ids"] = [
            result["contractor_call"]["call_id"],
            result["tenant_call"]["call_id"],
        ]
        mode = (
            "simulated"
            if result["contractor_call"].get("simulated")
            else "live"
        )
        summary = (
            f"✅ {repair['booked_slot']['contractor']} and tenant confirmed "
            f"the {result['slot']} appointment ({mode} call)."
            if result["confirmed"]
            else "⚠️ Call completed but the appointment needs landlord follow-up."
        )
        repair["timeline"].append({"ts": now(), "text": summary})
        log("dispatch", summary, repair_id=repair_id)
    except Exception as exc:
        repair["dispatch_status"] = "failed"
        repair["timeline"].append({
            "ts": now(),
            "text": "⚠️ Contractor call failed; the landlord has been notified.",
        })
        log(
            "dispatch",
            f"⚠️ Dispatch failed for {repair_id}: {exc}",
            repair_id=repair_id,
        )


@app.post("/repairs/submit")
async def submit_repair(request: Request, background_tasks: BackgroundTasks):
    req, photo_bytes = await parse_repair_submission(request)
    severity = None
    if photo_bytes is not None:
        try:
            severity = await asyncio.to_thread(
                vision.score_severity, photo_bytes, req.description
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except vision.VisionServiceError as exc:
            raise HTTPException(502, "photo severity analysis failed") from exc

    repair = create_repair(req, severity)
    if auto_dispatch_enabled():
        background_tasks.add_task(dispatch_repair, repair["id"])
    return repair


@app.post("/repairs/{repair_id}/book")
async def book_repair(
    repair_id: str, req: BookingRequest, background_tasks: BackgroundTasks
):
    repair = REPAIRS.get(repair_id)
    if not repair:
        raise HTTPException(404, "unknown repair id")
    slot = next((s for s in repair["slots"] if s["slot_id"] == req.slot_id), None)
    if not slot:
        raise HTTPException(400, "slot not available for this repair")
    repair.update(status="booked", booked_slot=slot)
    repair["timeline"].append(
        {"ts": now(), "text": f"🔁 Rebooked: {slot['contractor']} for {fmt(slot['start'])}"})
    log("booking", f"🔁 {repair_id} rebooked to {slot['contractor']} "
                   f"for {fmt(slot['start'])}", repair_id=repair_id)
    if auto_dispatch_enabled():
        repair["dispatch_status"] = "queued"
        background_tasks.add_task(dispatch_repair, repair_id)
    return {"id": repair_id, "status": "booked", "booked_slot": slot}


@app.get("/repairs/{repair_id}/calendar.ics")
def repair_ics(repair_id: str):
    repair = REPAIRS.get(repair_id)
    if not repair or not repair.get("booked_slot"):
        raise HTTPException(404, "no booking for this repair")
    slot = repair["booked_slot"]
    tenant = rent_ledger.get_status(repair["tenant_id"])
    start = datetime.fromisoformat(slot["start"])
    end = start + timedelta(hours=slot["window_hours"])
    stamp = "%Y%m%dT%H%M%S"
    ics = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//AI Landlord Agent//EN",
        "BEGIN:VEVENT",
        f"UID:{repair_id}@ai-landlord-agent",
        f"DTSTAMP:{datetime.now().strftime(stamp)}",
        f"DTSTART:{start.strftime(stamp)}",
        f"DTEND:{end.strftime(stamp)}",
        f"SUMMARY:Repair visit — {slot['contractor']}",
        f"LOCATION:Unit {tenant['unit']}",
        f"DESCRIPTION:{repair['description']} ({repair['urgency']} "
        f"{repair['category']}) — booked by AI Landlord Agent",
        "END:VEVENT", "END:VCALENDAR"])
    return Response(ics, media_type="text/calendar", headers={
        "Content-Disposition": f'attachment; filename="repair-{repair_id}.ics"'})


@app.get("/rent/status/{tenant_id}")
def rent_status(tenant_id: str):
    status = rent_ledger.get_status(tenant_id)
    if not status:
        raise HTTPException(404, "unknown tenant")
    return status


@app.post("/rent/remind/{tenant_id}")
def rent_remind(tenant_id: str):
    result = rent_ledger.send_reminder(tenant_id)
    if not result:
        raise HTTPException(404, "unknown tenant")
    log("rent", f"💬 Sent payment reminder to "
                f"{rent_ledger.get_status(tenant_id)['name']} via {result['channel']}: "
                f"“{result['message']}”", tenant_id=tenant_id)
    return result


@app.get("/rent/tenants")
def rent_tenants():
    return rent_ledger.list_tenants()


@app.get("/tenant/{tenant_id}/feed")
def tenant_feed(tenant_id: str):
    tenant = rent_ledger.get_status(tenant_id)
    if not tenant:
        raise HTTPException(404, "unknown tenant")
    repairs = [r for r in REPAIRS.values() if r["tenant_id"] == tenant_id]
    return {"tenant": tenant, "repairs": repairs}


@app.get("/landlord/overview")
def landlord_overview():
    return {"tenants": rent_ledger.list_tenants(),
            "repairs": [{k: v for k, v in r.items() if k != "slots"}
                        for r in REPAIRS.values()],
            "events": ACTIVITY}


@app.get("/")
def index_page():
    return FileResponse(STATIC / "index.html")


@app.get("/tenant")
def tenant_page():
    return FileResponse(STATIC / "tenant.html")


@app.get("/landlord")
def landlord_page():
    return FileResponse(STATIC / "landlord.html")
