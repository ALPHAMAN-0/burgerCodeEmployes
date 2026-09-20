"""SQLModel ORM definitions for burgerCodeEmployes."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel


class Role(str, Enum):
    CASHIER = "cashier"
    GRILL = "grill"
    FRY = "fry"
    MANAGER = "manager"


class Employee(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    role: Role = Field(default=Role.CASHIER)
    hourly_rate: float = Field(default=15.0, ge=0)
    active: bool = Field(default=True)


class Shift(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    employee_id: int = Field(foreign_key="employee.id", index=True)
    clock_in: datetime
    clock_out: datetime | None = None
    hours: float | None = None


class TipAllocation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    date: str = Field(index=True)  # ISO date
    total_pool: float
    notes: str = ""