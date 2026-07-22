
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

