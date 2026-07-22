# AI Landlord Agent (Hackathon Skeleton)

Scope: repair scheduling (photo intake -> severity -> book slot -> voice confirm)
+ mocked rent collection status + voice-call layer tying it together.

Explicitly out of scope: eviction management, legal advice, tax auditing —
cut for liability reasons, see PRD notes.

## Stack
- FastAPI backend
- Novita: vision model (severity scoring), reasoning model (slot matching)
- ActionLayer: voice calls (repair confirmation, rent reminders)
- Google Calendar API: real slot booking

## Build order (do this first, in order)
1. **Google Calendar auth** (`app/services/calendar_service.py`) — do this
   immediately, it's the dependency everything else needs. OAuth setup
   can eat unexpected time.
2. **Mock provider** (`app/services/mock_provider.py`) — already stubbed
   with fake slot data, adjust as needed.
3. **Novita vision call** (`app/services/vision.py`) — wire the real API
   call in place of the keyword-based stub.
4. **ActionLayer voice call** (`app/services/voice_service.py`) — wire in
   once calendar + vision work standalone.
5. End-to-end test, then polish demo narration.

## Run locally
```bash
pip install -r requirements.txt
cp .env.example .env  # fill in keys
uvicorn app.main:app --reload
```

## Endpoints
- `POST /repairs/submit` — tenant submits photo + description
- `POST /repairs/{ticket_id}/book` — triggers scheduling + voice confirm
- `GET /rent/status/{tenant_id}` — mocked rent ledger status
- `POST /rent/remind/{tenant_id}` — triggers voice reminder
- `POST /voice/call` — direct call trigger (mostly used internally)
- `POST /voice/webhook` — ActionLayer callback receiver

## Demo page & presenter script (~90 seconds)

The demo UI is served by the app itself at **http://localhost:8000** —
no separate frontend to run. Everything is mocked in-memory
(`app/services/`); restart the server to reset state.

1. **Repair flow** — click the **💧 Burst pipe** preset, then **Submit
   repair request**. Point out the agent auto-triaged it as
   *emergency / plumbing* and only emergency-capable contractors with
   same-day slots came back.
2. Click a slot card → it turns green with a booking confirmation.
3. (Optional contrast) Click **🔌 Dead outlet** preset → resubmit → slots
   are now *routine*: spread over the next few days, business hours only.
4. **Rent flow** — in section 3, pick **Marcus Webb** (2 months overdue,
   red badge) → **Send payment reminder** → show the mocked SMS. Pick
   **Amara Osei** to show a paid tenant (no reminder button).

## Known risks
- ActionLayer's call tool behavior/latency unknown until hands-on session
  — calendar + vision logic is independent, build/demo those first if
  voice proves flaky.
- If live voice is unreliable during the demo, fall back to text-transcript
  simulation so core logic still demos cleanly.
