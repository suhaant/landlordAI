from fastapi.testclient import TestClient
import pytest

from app import main
from app.models import Severity


@pytest.fixture(autouse=True)
def reset_demo_state():
    main.REPAIRS.clear()
    main.ACTIVITY.clear()
    yield
    main.REPAIRS.clear()
    main.ACTIVITY.clear()


def test_photo_report_routes_to_plumber_and_dispatches(monkeypatch):
    monkeypatch.setenv("DEMO_AUTO_DISPATCH", "true")
    monkeypatch.setattr(
        main.vision,
        "score_severity",
        lambda _photo, _description: Severity.HIGH,
    )
    dispatched = []

    async def fake_dispatch(repair):
        dispatched.append(repair)
        return {
            "slot": "today at 8:00 PM",
            "contractor_call": {
                "call_id": "call_contractor",
                "simulated": True,
            },
            "tenant_call": {
                "call_id": "call_tenant",
                "simulated": True,
            },
            "confirmed": True,
        }

    monkeypatch.setattr(main.voice_service, "run_repair_confirm", fake_dispatch)

    with TestClient(main.app) as client:
        response = client.post(
            "/repairs/submit",
            data={
                "tenant_id": "t1",
                "description": (
                    "Pipe under the kitchen sink is leaking and water is spreading."
                ),
            },
            files={"photo": ("leak.jpg", b"\xff\xd8\xffdemo", "image/jpeg")},
        )
        overview = client.get("/landlord/overview").json()

    assert response.status_code == 200
    repair = overview["repairs"][0]
    assert repair["severity"] == "HIGH"
    assert repair["urgency"] == "emergency"
    assert repair["category"] == "plumbing"
    assert repair["booked_slot"]["contractor_trade"] == "plumbing"
    assert repair["dispatch_status"] == "confirmed"
    assert repair["call_ids"] == ["call_contractor", "call_tenant"]
    assert dispatched[0]["id"] == repair["id"]
    assert any(event["kind"] == "dispatch" for event in overview["events"])


def test_json_report_remains_supported(monkeypatch):
    monkeypatch.setenv("DEMO_AUTO_DISPATCH", "false")

    with TestClient(main.app) as client:
        response = client.post(
            "/repairs/submit",
            json={
                "tenant_id": "t2",
                "description": "The bathroom door handle is loose.",
            },
        )

    assert response.status_code == 200
    repair = response.json()
    assert repair["severity"] == "LOW"
    assert repair["urgency"] == "routine"
    assert repair["has_photo"] is False
    assert repair["dispatch_status"] == "not_requested"
