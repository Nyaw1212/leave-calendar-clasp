from __future__ import annotations

from datetime import date, timedelta


def estimate_leave_charge(
    start: date,
    end: date,
    leave_type: str,
    regular_holidays: set[date] | frozenset[date],
    holiday_min_year: int,
    holiday_max_year: int,
) -> tuple[int, int | None, float | None, float | None]:
    """Return calendar days, chargeable days, and estimated VL/SL charges.

    This is an estimate for the complete date range, independent of approval.
    Unsupported holiday years yield unknown charges rather than understated ones.
    """
    if end < start:
        raise ValueError("The end date cannot precede the start date.")
    kind = leave_type.strip().upper()
    if kind not in {"VL", "SL", "FL"}:
        raise ValueError("Only VL, SL and FL estimates are supported.")
    calendar_days = (end - start).days + 1
    if start.year < holiday_min_year or end.year > holiday_max_year:
        return calendar_days, None, None, None
    chargeable = sum(
        day.weekday() < 5 and day not in regular_holidays
        for day in (start + timedelta(days=offset) for offset in range(calendar_days))
    )
    return calendar_days, chargeable, float(chargeable if kind in {"VL", "FL"} else 0), float(chargeable if kind == "SL" else 0)
