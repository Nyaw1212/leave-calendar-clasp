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


def allocate_unique_estimates(records: list[dict], holidays: set[date] | frozenset[date],
                              holiday_min_year: int, holiday_max_year: int) -> dict[str, dict]:
    """Allocate a chargeable date once per employee without changing source records.

    Overlapping different types need review; approval is never inferred.
    """
    cancelled = {"C", "D", "CANCELLED", "CANCELED", "DISAPPROVED"}
    result = {}
    by_day: dict[date, list[dict]] = {}
    unknown_ranges = []
    for row in records:
        status = str(row.get("status") or "").strip().upper()
        start, end = date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"])
        if status not in cancelled and (start.year < holiday_min_year or end.year > holiday_max_year):
            unknown_ranges.append((start, end))
    # Propagate uncertainty through chains of overlapping records.
    while unknown_ranges:
        expanded = False
        for row in records:
            if str(row.get("status") or "").strip().upper() in cancelled:
                continue
            interval = (date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"]))
            if interval not in unknown_ranges and any(interval[0] <= b and interval[1] >= a for a, b in unknown_ranges):
                unknown_ranges.append(interval)
                expanded = True
        if not expanded:
            break
    for row in records:
        key = row["record_key"]
        start, end = date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"])
        status = str(row.get("status") or "").strip().upper()
        item = {"chargeable": 0, "vl": 0.0, "sl": 0.0, "duplicates": [], "conflicts": [], "unavailable": False, "excluded": False}
        result[key] = item
        if status in cancelled:
            item["excluded"] = True
            continue
        if any(start <= unknown_end and end >= unknown_start for unknown_start, unknown_end in unknown_ranges):
            item["unavailable"] = True
            continue
        for offset in range((end - start).days + 1):
            day = start + timedelta(days=offset)
            if day.weekday() < 5 and day not in holidays:
                by_day.setdefault(day, []).append(row)
    for day, candidates in by_day.items():
        kinds = {str(row["leave_type"]).strip().upper() for row in candidates}
        if len(kinds) > 1:
            for row in candidates:
                result[row["record_key"]]["conflicts"].append(day)
            continue
        def priority(row: dict) -> tuple:
            status = str(row.get("status") or "").strip().upper()
            return (0 if status in {"A", "APPROVED"} else 1,
                    str(row.get("source_path") or "").casefold(),
                    str(row.get("source_sheet") or ""),
                    int(row.get("source_row") or 0), row["record_key"])
        ordered = sorted(candidates, key=priority)
        selected = ordered[0]
        entry = result[selected["record_key"]]
        entry["chargeable"] += 1
        if selected["leave_type"].strip().upper() in {"VL", "FL"}:
            entry["vl"] += 1.0
        elif selected["leave_type"].strip().upper() == "SL":
            entry["sl"] += 1.0
        for other in ordered[1:]:
            result[other["record_key"]]["duplicates"].append(day)
    return result
