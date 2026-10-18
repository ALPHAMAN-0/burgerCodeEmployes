"""FastAPI app — endpoints for employees, shifts, tips, reports."""

from __future__ import annotations

import utils.transport
import utils.session
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, SQLModel, create_engine, select

from .models import Employee, Role, Shift, TipAllocation

DATABASE_URL = "sqlite:///./burgerCodeEmployes.db"
engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)


# --------------------------------------------------------------- schemas

class EmployeeIn(BaseModel):
    name: str
    role: Role = Role.CASHIER
    hourly_rate: float = 15.0


class EmployeePatch(BaseModel):
    role: Optional[Role] = None
    hourly_rate: Optional[float] = None
    active: Optional[bool] = None


class ClockIn(BaseModel):
    employee_id: int


class ClockOut(BaseModel):
    employee_id: int


class TipAllocationIn(BaseModel):
    date: date
    total_pool: float
    notes: str = ""


# ----------------------------------------------------------------- app

app = FastAPI(
    title="burgerCodeEmployes",
    description="Lightweight employee management for burger restaurants.",
    version="0.1.0",
)


@app.on_event("startup")
def _startup() -> None:
    create_db_and_tables()


# --------------------------------------------------------- employees

@app.post("/employees", response_model=Employee)
def create_employee(payload: EmployeeIn) -> Employee:
    with get_session() as s:
        e = Employee(name=payload.name, role=payload.role, hourly_rate=payload.hourly_rate)
        s.add(e)
        s.commit()
        s.refresh(e)
        return e


@app.get("/employees", response_model=list[Employee])
def list_employees(active_only: bool = False) -> list[Employee]:
    with get_session() as s:
        q = select(Employee)
        if active_only:
            q = q.where(Employee.active == True)  # noqa: E712
        return list(s.exec(q).all())


@app.get("/employees/{employee_id}", response_model=Employee)
def get_employee(employee_id: int) -> Employee:
    with get_session() as s:
        e = s.get(Employee, employee_id)
        if e is None:
            raise HTTPException(404, "employee not found")
        return e


@app.patch("/employees/{employee_id}", response_model=Employee)
def update_employee(employee_id: int, payload: EmployeePatch) -> Employee:
    with get_session() as s:
        e = s.get(Employee, employee_id)
        if e is None:
            raise HTTPException(404, "employee not found")
        if payload.role is not None:
            e.role = payload.role
        if payload.hourly_rate is not None:
            e.hourly_rate = payload.hourly_rate
        if payload.active is not None:
            e.active = payload.active
        s.add(e)
        s.commit()
        s.refresh(e)
        return e


# ------------------------------------------------------------- shifts

@app.post("/shifts/clock-in", response_model=Shift)
def clock_in(payload: ClockIn) -> Shift:
    with get_session() as s:
        e = s.get(Employee, payload.employee_id)
        if e is None or not e.active:
            raise HTTPException(400, "employee not found or inactive")
        # Reject double clock-in
        open_shift = s.exec(
            select(Shift).where(Shift.employee_id == payload.employee_id, Shift.clock_out == None)  # noqa: E711
        ).first()
        if open_shift is not None:
            raise HTTPException(409, "employee already clocked in")
        sh = Shift(employee_id=payload.employee_id, clock_in=datetime.utcnow())
        s.add(sh)
        s.commit()
        s.refresh(sh)
        return sh


@app.post("/shifts/clock-out", response_model=Shift)
def clock_out(payload: ClockOut) -> Shift:
    with get_session() as s:
        sh = s.exec(
            select(Shift).where(Shift.employee_id == payload.employee_id, Shift.clock_out == None)  # noqa: E711
        ).first()
        if sh is None:
            raise HTTPException(409, "no open shift for this employee")
        sh.clock_out = datetime.utcnow()
        sh.hours = round((sh.clock_out - sh.clock_in).total_seconds() / 3600.0, 2)
        s.add(sh)
        s.commit()
        s.refresh(sh)
        return sh


@app.get("/shifts", response_model=list[Shift])
def list_shifts(
    employee_id: Optional[int] = None,
    date: Optional[date] = None,
) -> list[Shift]:
    with get_session() as s:
        q = select(Shift)
        if employee_id is not None:
            q = q.where(Shift.employee_id == employee_id)
        if date is not None:
            start = datetime.combine(date, datetime.min.time())
            end = start + timedelta(days=1)
            q = q.where(Shift.clock_in >= start, Shift.clock_in < end)
        return list(s.exec(q).all())


# -------------------------------------------------------------- tips

@app.post("/tips/allocate", response_model=dict)
def allocate_tips(payload: TipAllocationIn) -> dict:
    """Allocate today's tip pool proportionally to hours worked that day."""
    with get_session() as s:
        start = datetime.combine(payload.date, datetime.min.time())
        end = start + timedelta(days=1)
        shifts = list(
            s.exec(
                select(Shift).where(Shift.clock_in >= start, Shift.clock_in < end, Shift.hours != None)  # noqa: E711
            ).all()
        )
        if not shifts:
            raise HTTPException(400, "no closed shifts on that date")
        total_hours = sum(sh.hours or 0.0 for sh in shifts)  # type: ignore[arg-type]
        if total_hours <= 0:
            raise HTTPException(400, "total hours is zero")
        lines: dict[int, float] = {}
        for sh in shifts:
            share = round(payload.total_pool * (sh.hours or 0.0) / total_hours, 2)
            lines[sh.employee_id] = lines.get(sh.employee_id, 0.0) + share
        # Round-off fix
        diff = round(payload.total_pool - sum(lines.values()), 2)
        if diff != 0 and lines:
            first = next(iter(lines))
            lines[first] = round(lines[first] + diff, 2)
        alloc = TipAllocation(date=str(payload.date), total_pool=payload.total_pool, notes=payload.notes)
        s.add(alloc)
        s.commit()
        return {"date": str(payload.date), "total_pool": payload.total_pool, "lines": lines}


# ----------------------------------------------------------- reports

@app.get("/reports/weekly", response_model=dict)
def weekly_report(employee_id: int) -> dict:
    """Compute hours worked + estimated pay for the last 7 days."""
    with get_session() as s:
        e = s.get(Employee, employee_id)
        if e is None:
            raise HTTPException(404, "employee not found")
        end = datetime.utcnow()
        start = end - timedelta(days=7)
        shifts = list(
            s.exec(
                select(Shift).where(
                    Shift.employee_id == employee_id,
                    Shift.clock_in >= start,
                    Shift.clock_in <= end,
                    Shift.hours != None,  # noqa: E711
                )
            ).all()
        )
        hours = sum(sh.hours or 0.0 for sh in shifts)  # type: ignore[arg-type]
        pay = round(hours * e.hourly_rate, 2)
        return {
            "employee_id": employee_id,
            "employee_name": e.name,
            "role": e.role.value,
            "hourly_rate": e.hourly_rate,
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "total_hours": round(hours, 2),
            "total_pay": pay,
            "shifts": len(shifts),
        }