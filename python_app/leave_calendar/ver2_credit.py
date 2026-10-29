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


def audit_excluded_dates(start: date, end: date, holidays: set[date] | frozenset[date]) -> list[tuple[date, str]]:
    """Return the regular holidays and weekend dates excluded from VL/SL/FL."""
    if end < start:
        raise ValueError("The end date cannot precede the start date.")
    result = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if day in holidays:
            result.append((day, "RH"))
        elif day.weekday() == 5:
            result.append((day, "SAT"))
        elif day.weekday() == 6:
            result.append((day, "SUN"))
    return result


def duplicate_leave_overlaps(records: list[dict]) -> dict[str, list[tuple[date, date]]]:
    """Flag overlapping date ranges; cancelled/disapproved/MONE rows are excluded."""
    eligible = []
    for record in records:
        if str(record.get("status") or "").strip().upper() in {"C", "D", "CANCELLED", "CANCELED", "DISAPPROVED"}:
            continue
        if str(record.get("leave_type") or "").strip().upper() == "MONE":
            continue
        eligible.append((date.fromisoformat(record["start_date"]), date.fromisoformat(record["end_date"]), record["record_key"]))
    eligible.sort()
    overlaps: dict[str, list[tuple[date, date]]] = {}
    for i, (start, end, key) in enumerate(eligible):
        for later_start, later_end, other_key in eligible[i + 1:]:
            if later_start > end:
                break
            overlap = (later_start, min(end, later_end))
            overlaps.setdefault(key, []).append(overlap)
            overlaps.setdefault(other_key, []).append(overlap)
    return overlaps
