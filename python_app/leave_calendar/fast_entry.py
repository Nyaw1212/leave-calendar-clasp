from __future__ import annotations

from datetime import date


class FastDateError(ValueError):
    pass


def _numbers(value: str) -> list[int]:
    parts = value.strip().split()
    if not parts or any(not part.isdigit() for part in parts):
        raise FastDateError("Use numbers separated by spaces, such as 9 1.")
    return [int(part) for part in parts]


def _date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError as error:
        raise FastDateError(str(error).capitalize() + ".") from error


def parse_fast_start(
    value: str,
    working_year: int,
    previous_start: date | None = None,
) -> date:
    """Parse `month day` and roll the year forward for chronological entry."""
    numbers = _numbers(value)
    if len(numbers) == 2:
        month, day = numbers
        year = working_year
        if previous_start and month < previous_start.month:
            year = max(year, previous_start.year + 1)
        return _date(year, month, day)
    if len(numbers) == 3:
        month, day, year = numbers
        return _date(year, month, day)
    raise FastDateError("Enter the start as month day, such as 9 1.")


def parse_fast_end(value: str, start: date) -> date:
    """Parse a day, `month day`, or `month day year` relative to the start."""
    numbers = _numbers(value)
    if len(numbers) == 1:
        result = _date(start.year, start.month, numbers[0])
    elif len(numbers) == 2:
        month, day = numbers
        year = start.year + (1 if month < start.month else 0)
        result = _date(year, month, day)
    elif len(numbers) == 3:
        month, day, year = numbers
        result = _date(year, month, day)
    else:
        raise FastDateError("Enter the end as day only or month day.")
    if result < start:
        raise FastDateError("The end date cannot be before the start date.")
    return result


def parse_fast_range(
    value: str,
    working_year: int,
    previous_start: date | None = None,
) -> tuple[date, date]:
    """Parse `month start-day end-day` from one Fast Encode textbox."""
    numbers = _numbers(value)
    if len(numbers) != 3:
        raise FastDateError(
            "Enter month, start day, and end day, such as 9 1 3."
        )
    month, start_day, end_day = numbers
    start = parse_fast_start(
        f"{month} {start_day}",
        working_year,
        previous_start,
    )
    end = _date(start.year, start.month, end_day)
    if end < start:
        raise FastDateError("The end date cannot be before the start date.")
    return start, end
