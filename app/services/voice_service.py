"""
Voice service — Person 3 (Ignacio) — AI Landlord Agent

Two call flows:
  - repair_confirm : call the contractor to confirm the booked slot, then
                     separately call the tenant to confirm that time works.
  - rent_reminder  : call a tenant about overdue rent, using the mock ledger.

Priorities (per the plan):
  1. The text-transcript FALLBACK simulation works first, offline, with no keys.
  2. The live ActionLayer path is isolated in ONE method (_place_call_actionlayer)
     plus handle_webhook — the only two spots you edit once you have their docs.

Flip live with VOICE_SIMULATION=false once ActionLayer is confirmed. Until then
everything below runs and demos cleanly with zero secrets.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from app.services import rent_ledger

load_dotenv()

logger = logging.getLogger("voice_service")


# --------------------------------------------------------------------------- #
# Config (env only — nothing here blocks the app from starting)
# --------------------------------------------------------------------------- #

# Default to SIMULATION so the demo is safe. Set VOICE_SIMULATION=false to go live.
SIMULATION = os.getenv("VOICE_SIMULATION", "true").lower() != "false"

ACTIONLAYER_API_KEY = os.getenv("ACTIONLAYER_API_KEY", "")
# TODO(Ignacio): confirm base URL + path against the Install tab / AL session.
ACTIONLAYER_BASE_URL = os.getenv("ACTIONLAYER_BASE_URL", "https://api.actionlayer.io")
# Public URL AL posts results to. Dev: `ngrok http 8000` -> paste https URL + /voice/webhook
PUBLIC_WEBHOOK_URL = os.getenv("PUBLIC_WEBHOOK_URL", "")
REQUIRE_APPROVAL = os.getenv("VOICE_REQUIRE_APPROVAL", "false").lower() == "true"

# Optional flair: Novita generates a realistic (and multilingual) transcript in
# simulation mode. Falls back to a template if the key is missing.
NOVITA_API_KEY = os.getenv("NOVITA_API_KEY", "")
NOVITA_BASE_URL = os.getenv("NOVITA_BASE_URL", "https://api.novita.ai/openai")
NOVITA_MODEL = os.getenv("NOVITA_MODEL", "meta-llama/llama-3.1-8b-instruct")

# Ledger has no phone numbers — fake ones so the demo has something to show.
TENANT_PHONES = {"t1": "+14155550111", "t2": "+14155550122", "t3": "+14155550133",
                 "t4": "+14155550144", "t5": "+14155550155"}
DEMO_CONTRACTOR_PHONE = os.getenv("DEMO_CONTRACTOR_PHONE", "")
DEMO_PLUMBER_PHONE = os.getenv("DEMO_PLUMBER_PHONE", "")


# --------------------------------------------------------------------------- #
# Contract models (matches the CallRequest/CallResult the team expects)
# --------------------------------------------------------------------------- #

class CallType(str, Enum):
    REPAIR_CONFIRM = "repair_confirm"
    RENT_REMINDER = "rent_reminder"


class CallStatus(str, Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class CallRequest(BaseModel):
    call_type: CallType
    reference_id: str                       # repair_id (repair) or tenant_id (rent)
    phone_number: Optional[str] = None      # resolved automatically if omitted
    language: str = "en"                    # "es", "zh"… -> your in-language call story
    # optional extras the routers fill in; core three fields above are enough to call
    goal: Optional[str] = None
    context: dict[str, Any] = Field(default_factory=dict)


class CallResult(BaseModel):
    call_id: str
    call_type: CallType
    reference_id: str
    to_number: str
    language: str
    status: CallStatus
    goal: str
    transcript: str = ""
    outcome: dict[str, Any] = Field(default_factory=dict)
    simulated: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# --------------------------------------------------------------------------- #
# In-memory store (fine for a hackathon)
# --------------------------------------------------------------------------- #

_CALLS: dict[str, CallResult] = {}


def _save(result: CallResult) -> None:
    _CALLS[result.call_id] = result


def get_call(call_id: str) -> Optional[CallResult]:
    return _CALLS.get(call_id)


def list_calls() -> list[CallResult]:
    return sorted(_CALLS.values(), key=lambda c: c.created_at, reverse=True)


def _by_external_id(ext: str) -> Optional[CallResult]:
    return next((c for c in _CALLS.values() if c.outcome.get("external_id") == ext), None)


# --------------------------------------------------------------------------- #
# Call scripts / goals (natural-sounding, in plain English for ActionLayer)
# --------------------------------------------------------------------------- #

def _lang_clause(language: str) -> str:
    return f" Speak entirely in {language}." if language and language != "en" else ""


def contractor_goal(*, contractor: str, issue: str, slot_human: str,
                    language: str) -> str:
    return (
        f"Call {contractor}, a repair contractor.{_lang_clause(language)} "
        f"You are the property manager's assistant. Confirm they can carry out "
        f"this repair: \"{issue}\". Proposed time: {slot_human}. "
        f"If that time works, confirm it. If not, ask for the soonest alternative. "
        f"Be brief and polite. Report back: confirmed (yes/no) and the agreed time."
    )


def tenant_repair_goal(*, tenant_name: str, contractor: str, issue: str,
                       slot_human: str, language: str) -> str:
    first = tenant_name.split()[0] if tenant_name else "there"
    return (
        f"Call the tenant {first}.{_lang_clause(language)} "
        f"Let them know {contractor} is scheduled to handle the {issue} on "
        f"{slot_human}. Ask if that time works for them to provide access. "
        f"Be warm and brief. Report back: works for tenant (yes/no) and any note."
    )


def rent_goal(*, tenant_name: str, amount_due: float, due_date: str, status: str,
              language: str) -> str:
    first = tenant_name.split()[0] if tenant_name else "there"
    tone = "a friendly reminder" if status == "unpaid" else "a polite but firm notice"
    return (
        f"Call the tenant {first} with {tone} about rent.{_lang_clause(language)} "
        f"Amount due: ${amount_due:.2f}, due date {due_date}. "
        f"Ask whether they can pay by the due date; if not, note the date they "
        f"expect to pay and offer to set up a payment arrangement. Be respectful. "
        f"Report back: acknowledged (yes/no) and any promised payment date."
    )


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #

async def place_call(req: CallRequest) -> CallResult:
    """
    Place ONE call. For rent_reminder this fully self-serves from the ledger.
    For repair_confirm, use run_repair_confirm() which drives the two legs and
    fills req.context/goal for each.
    """
    # Resolve goal + phone if the caller only passed the core three fields.
    if req.call_type == CallType.RENT_REMINDER and not req.goal:
        _hydrate_rent(req)

    to_number = req.phone_number or req.context.get("to_number") or "unknown"
    goal = req.goal or "Complete the requested task and report back."

    call_id = f"call_{uuid.uuid4().hex[:10]}"
    result = CallResult(
        call_id=call_id, call_type=req.call_type, reference_id=req.reference_id,
        to_number=to_number, language=req.language, status=CallStatus.QUEUED,
        goal=goal, simulated=SIMULATION,
    )
    _save(result)

    if SIMULATION:
        await _simulate_call(req, result)
    else:
        await _place_call_actionlayer(req, result)

    _save(result)
    return result


async def run_repair_confirm(repair: dict, *, language: str = "en") -> dict:
    """
    Two calls: contractor then tenant. `repair` is the record from the REPAIRS
    store (has description, category, slots, and booked_slot once booked).
    Returns both CallResults plus a small summary for the demo UI.
    """
    slot = repair.get("booked_slot") or (repair.get("slots") or [{}])[0]
    contractor = slot.get("contractor", "the contractor")
    contractor_phone = (
        slot.get("contractor_phone")
        or (DEMO_PLUMBER_PHONE if repair.get("category") == "plumbing" else "")
        or DEMO_CONTRACTOR_PHONE
        or ("+15555550199" if SIMULATION else "")
    )
    if not contractor_phone:
        raise ValueError("No contractor phone configured for live dispatch")
    issue = repair.get("description", "the reported issue")
    slot_human = _human_time(slot.get("start"))
    tenant = rent_ledger.get_status(repair.get("tenant_id", "")) or {}
    tenant_name = tenant.get("name", "the tenant")

    # Leg 1 — contractor
    contractor_req = CallRequest(
        call_type=CallType.REPAIR_CONFIRM, reference_id=repair["id"],
        phone_number=contractor_phone, language=language,
        goal=contractor_goal(contractor=contractor, issue=issue,
                             slot_human=slot_human, language=language),
        context={"leg": "contractor", "slot_human": slot_human,
                 "contractor": contractor, "issue": issue},
    )
    contractor_res = await place_call(contractor_req)

    # Leg 2 — tenant
    tenant_req = CallRequest(
        call_type=CallType.REPAIR_CONFIRM, reference_id=repair["id"],
        phone_number=TENANT_PHONES.get(repair.get("tenant_id", ""), "+14155550100"),
        language=language,
        goal=tenant_repair_goal(tenant_name=tenant_name, contractor=contractor,
                               issue=issue, slot_human=slot_human, language=language),
        context={"leg": "tenant", "slot_human": slot_human,
                 "contractor": contractor, "issue": issue},
    )
    tenant_res = await place_call(tenant_req)

    return {
        "repair_id": repair["id"],
        "slot": slot_human,
        "contractor_call": contractor_res.model_dump(),
        "tenant_call": tenant_res.model_dump(),
        "confirmed": bool(contractor_res.outcome.get("confirmed")
                          and tenant_res.outcome.get("confirmed")),
    }


def _hydrate_rent(req: CallRequest) -> None:
    tenant = rent_ledger.get_status(req.reference_id) or {}
    req.phone_number = req.phone_number or TENANT_PHONES.get(req.reference_id)
    req.context.setdefault("tenant_name", tenant.get("name", "the tenant"))
    req.context.setdefault("amount_due", tenant.get("amount_due", 0.0))
    req.context.setdefault("due_date", tenant.get("due_date", ""))
    req.context.setdefault("status", tenant.get("status", "unpaid"))
    req.goal = rent_goal(
        tenant_name=tenant.get("name", "the tenant"),
        amount_due=float(tenant.get("amount_due", 0.0)),
        due_date=tenant.get("due_date", ""),
        status=tenant.get("status", "unpaid"),
        language=req.language,
    )


# --------------------------------------------------------------------------- #
# LIVE: the ONE method that touches ActionLayer
# --------------------------------------------------------------------------- #

async def _place_call_actionlayer(req: CallRequest, result: CallResult) -> None:
    """
    TODO(Ignacio): make this match ActionLayer's real API from the Install tab /
    hands-on session. Their public JS shape is roughly:

        const layer = new ActionLayer({ apiKey });
        await layer.run({ goal, requireApproval, plugins });

    Below is the HTTP equivalent. Expected async flow: START a run here, get an
    external id, and ActionLayer POSTs the transcript/outcome to /voice/webhook
    (handled by handle_webhook). Keep try/except so a live failure degrades to a
    clear FAILED status instead of crashing the live demo. Confirm the three ???
    keys/paths with them.
    """
    result.status = CallStatus.IN_PROGRESS
    _save(result)

    headers = {"Authorization": f"Bearer {ACTIONLAYER_API_KEY}"}
    payload = {
        "goal": result.goal,
        "phone_number": result.to_number,      # ??? confirm key name
        "language": req.language,              # ??? confirm key name
        "require_approval": REQUIRE_APPROVAL,
        "webhook_url": PUBLIC_WEBHOOK_URL,
        "metadata": {"call_id": result.call_id, "call_type": req.call_type.value},
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{ACTIONLAYER_BASE_URL}/v1/run",   # ??? confirm path
                json=payload, headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        result.outcome["external_id"] = data.get("id") or data.get("task_id", "")
        logger.info("ActionLayer run started: %s", result.outcome["external_id"])
    except Exception as exc:  # noqa: BLE001 — never crash the demo
        logger.exception("ActionLayer call failed: %s", exc)
        result.status = CallStatus.FAILED
        result.outcome["error"] = str(exc)


# --------------------------------------------------------------------------- #
# FALLBACK: simulation (offline, never fails) — build/verify this FIRST
# --------------------------------------------------------------------------- #

async def _simulate_call(req: CallRequest, result: CallResult) -> None:
    result.status = CallStatus.IN_PROGRESS
    _save(result)
    await asyncio.sleep(0.35)  # let the UI show "in progress" first

    transcript = await _novita_transcript(req, result.goal)
    if not transcript:
        transcript = _template_transcript(req)

    result.transcript = transcript
    result.outcome.update(_infer_outcome(req, transcript))
    result.status = CallStatus.COMPLETED


async def _novita_transcript(req: CallRequest, goal: str) -> str:
    if not NOVITA_API_KEY:
        return ""
    lang = (f"Write the dialogue in {req.language}."
            if req.language and req.language != "en" else "")
    prompt = (
        "Simulate a short, realistic phone-call transcript for a demo. "
        f"The caller is an AI assistant with this goal:\n{goal}\n{lang}\n"
        "Format as 'Agent:' / 'Callee:' turns, under 8 turns, ending with the "
        "objective clearly resolved (a yes)."
    )
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{NOVITA_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {NOVITA_API_KEY}"},
                json={"model": NOVITA_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "max_tokens": 400, "temperature": 0.7},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Novita transcript unavailable, using template: %s", exc)
        return ""


def _template_transcript(req: CallRequest) -> str:
    ctx = req.context
    if req.call_type == CallType.REPAIR_CONFIRM and ctx.get("leg") == "contractor":
        return (
            f"Agent: Hi, calling on behalf of the property manager about a "
            f"{ctx.get('issue', 'repair')}. Can you make {ctx.get('slot_human', 'the slot')}?\n"
            f"Callee: Yes, we can cover that — we'll be there.\n"
            f"Agent: Great, confirmed for {ctx.get('slot_human', 'that time')}. Thank you!"
        )
    if req.call_type == CallType.REPAIR_CONFIRM:  # tenant leg
        return (
            f"Agent: Hi, just confirming {ctx.get('contractor', 'the contractor')} will "
            f"handle the {ctx.get('issue', 'repair')} on {ctx.get('slot_human', 'the slot')}. "
            f"Does that work for you?\n"
            f"Callee: Yes, that works — I'll be home.\n"
            f"Agent: Perfect, thanks!"
        )
    # rent reminder
    amt = ctx.get("amount_due", 0.0)
    return (
        f"Agent: Hello, this is a courtesy call — ${amt:.2f} in rent is due on "
        f"{ctx.get('due_date', 'the due date')}. Will you be able to pay by then?\n"
        f"Callee: Yes, I'll take care of it on time.\n"
        f"Agent: Thank you, appreciate it. Have a good day!"
    )


def _infer_outcome(req: CallRequest, transcript: str) -> dict[str, Any]:
    t = transcript.lower()
    positive = any(w in t for w in ("yes", "confirmed", "works", "on time",
                                    "sí", "claro", "de acuerdo"))
    if req.call_type == CallType.REPAIR_CONFIRM:
        return {"leg": req.context.get("leg"), "confirmed": positive,
                "agreed_time": req.context.get("slot_human", "")}
    return {"acknowledged": positive, "promised_date": req.context.get("due_date", "")}


# --------------------------------------------------------------------------- #
# Webhook: ActionLayer posts the final result here
# --------------------------------------------------------------------------- #

def handle_webhook(payload: dict) -> dict:
    """
    TODO(Ignacio): map ActionLayer's real webhook fields once known. We match on
    metadata.call_id (we set it when starting the run), else their external id.
    """
    meta = payload.get("metadata", {}) or {}
    result = get_call(meta.get("call_id")) if meta.get("call_id") else None
    if result is None:
        ext = payload.get("id") or payload.get("task_id", "")
        result = _by_external_id(ext)
    if result is None:
        logger.warning("Webhook for unknown call: %s", payload)
        return {"ok": False, "reason": "no matching call"}

    status = str(payload.get("status", "completed")).lower()
    result.status = (CallStatus.COMPLETED if status in ("completed", "done", "success")
                     else CallStatus.FAILED)
    result.transcript = payload.get("transcript", result.transcript)
    if isinstance(payload.get("outcome"), dict):
        result.outcome.update(payload["outcome"])
    _save(result)
    return {"ok": True, "call": result.model_dump()}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _human_time(iso: Optional[str]) -> str:
    if not iso:
        return "the proposed time"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%a %b %-d at %-I:%M %p")
    except Exception:  # noqa: BLE001
        return str(iso)
