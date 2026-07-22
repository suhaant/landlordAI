# ponytail: in-memory fake ledger, no payment rails — intentional for the demo.
LEDGER = {
    "t1": {"name": "Amara Osei", "unit": "2B", "rent": 1850.00, "amount_due": 0.00,
           "status": "paid", "due_date": "2026-07-01", "last_payment": "2026-06-28"},
    "t2": {"name": "Dev Patel", "unit": "4A", "rent": 1620.00, "amount_due": 1620.00,
           "status": "unpaid", "due_date": "2026-08-01", "last_payment": "2026-07-01"},
    "t3": {"name": "Rosa Delgado", "unit": "1C", "rent": 2100.00, "amount_due": 2100.00,
           "status": "overdue", "due_date": "2026-07-01", "last_payment": "2026-06-01"},
    "t4": {"name": "Marcus Webb", "unit": "3F", "rent": 1400.00, "amount_due": 2800.00,
           "status": "overdue", "due_date": "2026-06-01", "last_payment": "2026-05-02"},
    "t5": {"name": "Lin Zhao", "unit": "5D", "rent": 1975.00, "amount_due": 0.00,
           "status": "paid", "due_date": "2026-07-01", "last_payment": "2026-07-01"},
}


def get_status(tenant_id: str) -> dict | None:
    entry = LEDGER.get(tenant_id)
    return {"tenant_id": tenant_id, **entry} if entry else None


def list_tenants() -> list[dict]:
    return [{"tenant_id": tid, **e} for tid, e in LEDGER.items()]


def send_reminder(tenant_id: str) -> dict | None:
    entry = LEDGER.get(tenant_id)
    if not entry:
        return None
    if entry["status"] == "paid":
        message = (f"Hi {entry['name'].split()[0]}, thanks — your rent for unit "
                   f"{entry['unit']} is fully paid. Nothing due.")
    else:
        tone = "a friendly reminder" if entry["status"] == "unpaid" else "an urgent notice"
        message = (f"Hi {entry['name'].split()[0]}, this is {tone}: "
                   f"${entry['amount_due']:.2f} is due for unit {entry['unit']} "
                   f"(due date {entry['due_date']}). Reply here to arrange payment.")
    entry["reminder_sent"] = True
    return {"tenant_id": tenant_id, "channel": "sms (mocked)", "message": message}


if __name__ == "__main__":
    assert get_status("t3")["status"] == "overdue"
    assert "urgent" in send_reminder("t3")["message"]
    assert "fully paid" in send_reminder("t1")["message"]
    assert get_status("nope") is None
    print(f"ok: {len(LEDGER)} tenants")
