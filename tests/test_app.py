"""Smoke tests for burgerCodeEmployes (in-memory DB)."""

from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient

# Use a temp DB so tests don't pollute the working directory
fd, path = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["DATABASE_URL"] = f"sqlite:///{path}"

from burgerCodeEmployes.app import app  # noqa: E402

client = TestClient(app)


def test_create_and_list_employee():
    r = client.post("/employees", json={"name": "Alice", "role": "cashier", "hourly_rate": 16.0})
    assert r.status_code == 200, r.text
    eid = r.json()["id"]

    r2 = client.get("/employees")
    assert r2.status_code == 200
    assert any(e["id"] == eid for e in r2.json())


def test_clock_in_out():
    r = client.post("/employees", json={"name": "Bob", "role": "grill"})
    eid = r.json()["id"]

    r_in = client.post("/shifts/clock-in", json={"employee_id": eid})
    assert r_in.status_code == 200

    # Re-clocking in is rejected
    r_dup = client.post("/shifts/clock-in", json={"employee_id": eid})
    assert r_dup.status_code == 409

    r_out = client.post("/shifts/clock-out", json={"employee_id": eid})
    assert r_out.status_code == 200
    assert r_out.json()["hours"] is not None
    assert r_out.json()["hours"] >= 0


def test_update_employee():
    r = client.post("/employees", json={"name": "Carol", "role": "fry"})
    eid = r.json()["id"]

    r2 = client.patch(f"/employees/{eid}", json={"role": "manager", "hourly_rate": 25.0})
    assert r2.status_code == 200
    assert r2.json()["role"] == "manager"
    assert r2.json()["hourly_rate"] == 25.0


def test_weekly_report_empty():
    r = client.post("/employees", json={"name": "Dan", "role": "manager"})
    eid = r.json()["id"]
    r2 = client.get("/reports/weekly", params={"employee_id": eid})
    assert r2.status_code == 200
    body = r2.json()
    assert body["total_hours"] == 0
    assert body["total_pay"] == 0