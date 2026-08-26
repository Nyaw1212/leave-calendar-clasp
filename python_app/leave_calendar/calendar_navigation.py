from __future__ import annotations

from datetime import date


CALENDAR_MIN_YEAR = 1975
CALENDAR_MAX_YEAR = 2100
CALENDAR_MIN_MONTH = date(CALENDAR_MIN_YEAR, 1, 1)
CALENDAR_MAX_MONTH = date(CALENDAR_MAX_YEAR, 12, 1)


def add_months(value: date, offset: int) -> date:
    absolute = value.year * 12 + value.month - 1 + offset
    year, month_index = divmod(absolute, 12)
    return date(year, month_index + 1, 1)


def clamp_calendar_month(value: date) -> date:
    month = value.replace(day=1)
    return min(max(month, CALENDAR_MIN_MONTH), CALENDAR_MAX_MONTH)


def calendar_view_start(value: date, month_count: int) -> date:
    month = clamp_calendar_month(value)
    if month_count >= 12:
        return date(month.year, 1, 1)
    return month


def calendar_navigation_offset(month_count: int, direction: int) -> int:
    return direction * (12 if month_count >= 12 else 1)


def calendar_column_count(month_count: int) -> int:
    if month_count >= 12:
        return 4
    if month_count >= 3:
        return 3
    return max(1, month_count)
