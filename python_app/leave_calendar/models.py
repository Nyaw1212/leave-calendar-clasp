from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class Employee:
    employee_id: str
    name: str
    assumption_date: date | None = None
    earned_vl: float = 0.0
    earned_sl: float = 0.0

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.employee_id})"


@dataclass(frozen=True, slots=True)
class LeaveDay:
    day: date
    credits: float

    def to_dict(self) -> dict[str, Any]:
        return {"day": self.day.isoformat(), "credits": self.credits}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LeaveDay":
        return cls(
            day=date.fromisoformat(str(value["day"])),
            credits=float(value.get("credits", 0)),
        )


@dataclass(frozen=True, slots=True)
class DraftEntry:
    entry_id: str
    leave_type: str
    days: tuple[LeaveDay, ...]
    remarks: str = ""

    @property
    def total_credits(self) -> float:
        return round(sum(item.credits for item in self.days), 3)

    @property
    def first_day(self) -> date:
        return min(item.day for item in self.days)

    @property
    def last_day(self) -> date:
        return max(item.day for item in self.days)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "leave_type": self.leave_type,
            "days": [item.to_dict() for item in self.days],
            "remarks": self.remarks,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DraftEntry":
        return cls(
            entry_id=str(value["entry_id"]),
            leave_type=str(value["leave_type"]),
            days=tuple(LeaveDay.from_dict(item) for item in value.get("days", [])),
            remarks=str(value.get("remarks", "")),
        )


@dataclass(frozen=True, slots=True)
class LeaveRecord:
    leave_type: str
    start: date
    end: date
    vl: float
    sl: float
    lwop: float
    record_id: str
    employee_id: str
    name: str
    remarks: str = ""


@dataclass(frozen=True, slots=True)
class EmployeeProfile:
    employee_id: str
    name: str
    assumption_date: date | None
    as_of_date: date
    opening_vl: float
    opening_sl: float
    earned_vl: float
    earned_sl: float
    used_vl: float
    used_sl: float
    balance_vl: float
    balance_sl: float


@dataclass(frozen=True, slots=True)
class SaveResult:
    rows_written: int
    dates_added: int
    skipped_existing: int
    zero_credit_dates: int
    magclip_rows: tuple[tuple[str, ...], ...] = ()

    @property
    def message(self) -> str:
        parts = [
            f"{self.rows_written} grouped leave record(s) saved from "
            f"{self.dates_added} selected date(s)."
        ]
        if self.skipped_existing:
            parts.append(f"{self.skipped_existing} existing date(s) skipped.")
        if self.zero_credit_dates:
            parts.append(
                f"{self.zero_credit_dates} non-credit/weekend/regular holiday "
                "date(s) carried 0 credit."
            )
        return " ".join(parts)
