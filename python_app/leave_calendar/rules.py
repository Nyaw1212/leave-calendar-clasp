from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta
from typing import Iterable, Sequence, TypeVar


LEAVE_TYPES = (
    "Vacation Leave",
    "Sick Leave",
    "Forced Leave",
    "Special Privilege Leave",
    "Compensatory Time Off",
    "Maternity Leave",
    "Paternity Leave",
    "Other",
)

_LEAVE_TYPE_MAP = {
    "VL": "Vacation Leave",
    "VACATION LEAVE": "Vacation Leave",
    "SL": "Sick Leave",
    "SICK LEAVE": "Sick Leave",
    "FL": "Forced Leave",
    "FORCED LEAVE": "Forced Leave",
    "SPL": "Special Privilege Leave",
    "SPECIAL PRIVILEGE LEAVE": "Special Privilege Leave",
    "CTO": "Compensatory Time Off",
    "COMPENSATORY TIME OFF": "Compensatory Time Off",
    "ML": "Maternity Leave",
    "MATERNITY LEAVE": "Maternity Leave",
    "PL": "Paternity Leave",
    "PATERNITY LEAVE": "Paternity Leave",
}


def normalize_leave_type(value: str) -> str:
    text = str(value or "Other").strip()
    code_match = re.search(r"\(([A-Za-z0-9-]+)\)\s*$", text)
    if code_match:
        code = code_match.group(1).upper()
        if code in _LEAVE_TYPE_MAP:
            return _LEAVE_TYPE_MAP[code]
    return _LEAVE_TYPE_MAP.get(text.upper(), text or "Other")


def is_vl_charge(leave_type: str) -> bool:
    return normalize_leave_type(leave_type) in {"Vacation Leave", "Forced Leave"}


def is_sl_charge(leave_type: str) -> bool:
    return normalize_leave_type(leave_type) == "Sick Leave"


def carries_credit(leave_type: str) -> bool:
    return is_vl_charge(leave_type) or is_sl_charge(leave_type)


def credit_for_day(
    day: date,
    leave_type: str,
    requested_credit: float,
    regular_holidays: set[date] | frozenset[date],
) -> float:
    if not carries_credit(leave_type):
        return 0.0
    if day.weekday() >= 5 or day in regular_holidays:
        return 0.0
    return round(max(0.0, float(requested_credit)), 3)


T = TypeVar("T")


def group_consecutive_dates(
    values: Sequence[T],
    date_getter=lambda value: value,
) -> list[list[T]]:
    ordered = sorted(values, key=date_getter)
    groups: list[list[T]] = []
    for item in ordered:
        item_date = date_getter(item)
        if not groups:
            groups.append([item])
            continue
        previous_date = date_getter(groups[-1][-1])
        if item_date - previous_date == timedelta(days=1):
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def inclusive_dates(start: date, end: date) -> list[date]:
    if end < start:
        start, end = end, start
    count = (end - start).days + 1
    return [start + timedelta(days=offset) for offset in range(count)]


def inclusive_days(start: date, end: date) -> int:
    return (end - start).days + 1


def compute_opening_credit(assumption_date: date) -> float:
    last_day = monthrange(assumption_date.year, assumption_date.month)[1]
    month_end = date(assumption_date.year, assumption_date.month, last_day)
    return round(min(inclusive_days(assumption_date, month_end) / 24, 1.25), 3)


def compute_csc_accrual(start: date, end: date) -> float:
    """Port of the current Apps Script CSC accrual rule."""
    if end < start:
        return 0.0

    if start.year == end.year and start.month == end.month:
        return round(min(inclusive_days(start, end) / 24, 1.25), 3)

    first_month_end = date(start.year, start.month, monthrange(start.year, start.month)[1])
    first_partial = min(inclusive_days(start, first_month_end) / 24, 1.25)

    current_month_start = date(end.year, end.month, 1)
    current_partial = min(inclusive_days(current_month_start, end) / 24, 1.25)

    if start.month == 12:
        first_full_month = date(start.year + 1, 1, 1)
    else:
        first_full_month = date(start.year, start.month + 1, 1)

    months_between = max(
        0,
        (current_month_start.year - first_full_month.year) * 12
        + current_month_start.month
        - first_full_month.month,
    )
    return round(first_partial + months_between * 1.25 + current_partial, 3)


def prorated_usage(
    start: date,
    end: date,
    as_of_date: date,
    amount: float,
) -> float:
    if start > as_of_date:
        return 0.0
    if end <= as_of_date:
        return float(amount)
    total_days = inclusive_days(start, end)
    elapsed_days = max(0, inclusive_days(start, as_of_date))
    ratio = min(1.0, elapsed_days / total_days) if total_days else 0.0
    return float(amount) * ratio
