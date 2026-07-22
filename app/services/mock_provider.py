# ponytail: pure mock, no real scheduling. Deterministic per repair_id so the
# demo looks stable across refreshes.
import os
import random
from datetime import datetime, timedelta

CONTRACTORS = [
    {"id": "c1", "name": "RapidFix 24/7 Maintenance", "trade": "general",
     "rating": 4.6, "emergency": True, "hours": (0, 24), "callout_fee": 95,
     "phone_env": "DEMO_CONTRACTOR_PHONE"},
    {"id": "c2", "name": "Hendricks Plumbing & Heating", "trade": "plumbing",
     "rating": 4.9, "emergency": True, "hours": (7, 19), "callout_fee": 120,
     "phone_env": "DEMO_PLUMBER_PHONE"},
    {"id": "c3", "name": "Volt & Vine Electrical", "trade": "electrical",
     "rating": 4.7, "emergency": False, "hours": (8, 17), "callout_fee": 110,
     "phone_env": "DEMO_CONTRACTOR_PHONE"},
    {"id": "c4", "name": "GreenLeaf Property Services", "trade": "general",
     "rating": 4.3, "emergency": False, "hours": (9, 17), "callout_fee": 75,
     "phone_env": "DEMO_CONTRACTOR_PHONE"},
]


def get_available_slots(urgency: str = "routine", category: str = "general",
                        repair_id: str | None = None) -> list[dict]:
    """Fake availability: emergency = next few hours, routine = spread over days."""
    rng = random.Random(repair_id or f"{urgency}-{category}")
    now = datetime.now().replace(minute=0, second=0, microsecond=0)

    matching = [c for c in CONTRACTORS if c["trade"] in (category, "general")]
    if urgency == "emergency":
        emergency_capable = [c for c in matching if c["emergency"]]
        matching = emergency_capable or matching

    slots = []
    for c in matching:
        if urgency == "emergency":
            times = [now + timedelta(hours=h)
                     for h in sorted(rng.sample(range(1, 10), 3))]
        else:
            times = []
            for day in sorted(rng.sample(range(1, 6), 3)):
                start, end = c["hours"]
                hour = rng.randrange(max(start, 8), min(end, 17))
                times.append(now.replace(hour=hour) + timedelta(days=day))
        for t in times:
            slots.append({
                "slot_id": f"{c['id']}-{t.strftime('%Y%m%d%H%M')}",
                "contractor_id": c["id"],
                "contractor": c["name"],
                "contractor_trade": c["trade"],
                "contractor_phone": os.getenv(c["phone_env"], ""),
                "rating": c["rating"],
                "callout_fee": c["callout_fee"],
                "start": t.isoformat(),
                "window_hours": 1 if urgency == "emergency" else 2,
            })
    slots.sort(key=lambda s: s["start"])
    return slots


if __name__ == "__main__":
    em = get_available_slots("emergency", "plumbing", "r1")
    rt = get_available_slots("routine", "electrical", "r2")
    assert em and rt
    assert em[0]["start"] < rt[0]["start"], "emergency slots must come sooner"
    assert em == get_available_slots("emergency", "plumbing", "r1"), "must be deterministic"
    print(f"ok: {len(em)} emergency slots, {len(rt)} routine slots")
