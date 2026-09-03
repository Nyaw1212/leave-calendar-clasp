from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
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
class Holiday:
    day: date
    name: str
    holiday_type: str

    @property
    def is_regular(self) -> bool:
        return "regular" in self.holiday_type.casefold()

    @property
    def is_special_non_working(self) -> bool:
        normalized = self.holiday_type.casefold().replace("-", " ")
        return all(word in normalized.split() for word in ("special", "non", "working"))

    @property
    def is_special_working(self) -> bool:
        normalized = self.holiday_type.casefold().replace("-", " ")
        words = normalized.split()
        return "special" in words and "working" in words and "non" not in words


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
    vl_allocation: float | None = None
    sl_allocation: float | None = None

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
            "vl_allocation": self.vl_allocation,
            "sl_allocation": self.sl_allocation,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DraftEntry":
        return cls(
            entry_id=str(value["entry_id"]),
            leave_type=str(value["leave_type"]),
            days=tuple(LeaveDay.from_dict(item) for item in value.get("days", [])),
            remarks=str(value.get("remarks", "")),
            vl_allocation=(
                float(value["vl_allocation"])
                if value.get("vl_allocation") is not None
                else None
            ),
            sl_allocation=(
                float(value["sl_allocation"])
                if value.get("sl_allocation") is not None
                else None
            ),
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
    status: str = "A"

    @property
    def calendar_dates(self) -> tuple[date, ...]:
        count = max(0, (self.end - self.start).days + 1)
        return tuple(self.start + timedelta(days=offset) for offset in range(count))

    @property
    def day_count(self) -> int:
        return len(self.calendar_dates)

    @property
    def total_credits(self) -> float:
        return round(self.vl + self.sl + self.lwop, 3)


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
    existing_dates_written: int
    zero_credit_dates: int
    magclip_rows: tuple[tuple[str, ...], ...] = ()

    @property
    def message(self) -> str:
        parts = [
            f"{self.rows_written} grouped leave record(s) saved from "
            f"{self.dates_added} selected date(s)."
        ]
        if self.existing_dates_written:
            parts.append(
                f"Warning: {self.existing_dates_written} date(s) were already recorded "
                "and were saved again."
            )
        if self.zero_credit_dates:
            parts.append(
                f"{self.zero_credit_dates} non-credit/weekend/regular holiday "
                "date(s) carried 0 credit."
            )
        return " ".join(parts)
