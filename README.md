
# AI Landlord Agent
 
An AI agent that turns a tenant's photo of a repair issue into a booked, calendar-confirmed contractor visit, with voice call confirmation and rent tracking layered in.
 
## The Problem
 
Real estate agencies take up to 10% off the top, just to manage things a landlord could hand off entirely. Tenants call a property manager, wait on a callback, and hope someone follows up. Landlords pay a cut for coordination that mostly amounts to phone calls and scheduling.
 
## What We Built
 
Our agent replaces that overhead. Tenants just call the agent. It scores the issue, books the repair, confirms it by voice, and keeps rent on track, all without a human in the loop.
 
**Flow:**
1. Tenant submits a photo and description of a repair issue
2. Agent scores severity (emergency vs. routine) from the photo
3. Agent checks a mock contractor's availability against the landlord's real calendar
4. Agent books the best matching slot and confirms it with a real voice call
5. Rent status is tracked on a mocked ledger, with voice reminders for anything overdue
## How We Used the Sponsor Tools
 
**Novita** runs the vision model that scores repair severity from a tenant's photo and description, turning that visual input into a structured decision the rest of the agent can act on.
 
**ActionLayer** places the actual voice calls, confirming the booked repair slot with the tenant and contractor and delivering rent reminders, so the agent's decisions turn into real phone conversations instead of just API calls.
 
**Google Calendar API** grounds the whole flow in a real calendar, so the agent is booking against actual availability, not a fake schedule.
 
## Scope
 
We intentionally kept this to repair scheduling, rent status, and voice coordination. Eviction handling, legal advice, and tax matters are cut from scope, since those carry real legal and financial consequences that don't belong in a hackathon demo.
 
## Architecture
 
```
Tenant photo + description
        |
        v
  Novita (severity scoring)
        |
        v
  Mock contractor slots  <-->  Google Calendar (real availability)
        |
        v
  Best slot booked + event created
        |
        v
  ActionLayer (voice confirmation call)
```
 
Rent reminders follow the same voice path, triggered off a mocked ledger rather than a real payment rail.
 
## Tech Stack
 
- FastAPI backend
- Novita (vision model)
- ActionLayer (voice calls)
- Google Calendar API
## Project Structure
 
```
app/
  main.py                 FastAPI entrypoint
  routers/                repairs, rent, voice endpoints
  services/
    vision.py              Novita severity scoring
    calendar_service.py    Google Calendar auth + booking
    mock_provider.py       fake contractor availability
    scheduling.py          ties severity + calendar + booking together
    rent_ledger.py         mocked rent status
    voice_service.py       ActionLayer call handling
  models/schemas.py         request/response models
```
 
## Running Locally
 
```bash
pip install -r requirements.txt
cp .env.example .env  # fill in API keys
uvicorn app.main:app --reload
```
 
## What's Not Real
 
Rent collection is a mocked in-memory ledger. No real payment rails are wired in, on purpose, this was a deliberate scope cut to avoid handling real money in a hackathon demo.

## Endpoints
- `POST /repairs/submit` — tenant submits photo + description
- `POST /repairs/{ticket_id}/book` — triggers scheduling + voice confirm
- `GET /rent/status/{tenant_id}` — mocked rent ledger status
- `POST /rent/remind/{tenant_id}` — triggers voice reminder
- `POST /voice/call` — direct call trigger (mostly used internally)
- `POST /voice/webhook` — ActionLayer callback receiver

## Demo — presenter script (~2 minutes, two windows)

The demo UI is served by the app itself at **http://localhost:8000** —
no separate frontend to run. Everything is mocked in-memory
(`app/services/`); restart the server to reset state.

Setup: open **/tenant** and **/landlord** in two windows side by side.
The landlord feed polls every 2s, so it updates live while you drive
the tenant window.

1. **Photo repair** — tenant window, pick **Rosa Delgado**, click the
   **💧 Burst pipe** preset, attach a clear plumbing photo, then Send. Novita
   scores the photo and description together. The agent routes the job to
   **Hendricks Plumbing & Heating**, books the best severity-appropriate slot,
   and automatically starts contractor + tenant confirmation calls.
2. **Landlord window** — the report → triage → booking trail has already
   appeared in the live feed. The sidebar shows the four-level severity and
   dispatch status; the feed shows call confirmation. Calls are simulated by
   default so this path is deterministic on stage.
3. **Routine contrast** — tenant window, switch to **Dev Patel**, click
   **🔌 Dead outlet** → Send. This time the agent picks the
   **highest-rated** electrician days out, business hours.
4. **Rent** — landlord sidebar: Marcus Webb is 2 months overdue. Click
   **Remind** → mocked SMS appears in the feed, button flips to *Sent ✓*.

## Known risks
- ActionLayer's call tool behavior/latency unknown until hands-on session
  — calendar + vision logic is independent, build/demo those first if
  voice proves flaky.
- If live voice is unreliable during the demo, fall back to text-transcript
  simulation so core logic still demos cleanly.

## Vision demo photos
- **LOW:** loose cabinet knob; door still works.
- **MEDIUM:** cabinet door detached from one hinge, with no sharp debris.
- **MEDIUM:** dripping faucet with all water contained in a bowl.
- **HIGH:** steady under-sink leak visibly spreading across the cabinet floor.
- **EMERGENCY:** use a safe, disconnected damaged-cable prop and describe an
  outlet that sparked with a burning smell. Never stage a real electrical hazard.

Use clear JPEGs under 1 MB and pre-run the exact demo photos against the selected
Novita model before presenting.

## Integrated repair dispatch

`POST /repairs/submit` accepts either the original JSON body or multipart form
data with `tenant_id`, `description`, and optional `photo`. With a photo, the
flow is:

`photo + description → Novita severity → trade routing → slot booking → call confirmation`

Set these values in `.env` for the demo:

```dotenv
VOICE_SIMULATION=true
DEMO_AUTO_DISPATCH=true
DEMO_PLUMBER_PHONE=
```

`DEMO_PLUMBER_PHONE` may be blank in simulation. Before setting
`VOICE_SIMULATION=false`, provide a real E.164 test number and replace the
explicitly unverified ActionLayer request/webhook mapping in
`app/services/voice_service.py` with the API contract from the ActionLayer
hackathon session.
