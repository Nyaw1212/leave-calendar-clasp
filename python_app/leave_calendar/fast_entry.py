from __future__ import annotations

import re
from datetime import date


class FastDateError(ValueError):
    pass


def _numbers(value: str) -> list[int]:
    parts = [part for part in re.split(r"[\s/]+", value.strip()) if part]
    if not parts or any(not part.isdigit() for part in parts):
        raise FastDateError("Use numbers separated by /, such as 9/1 or 9/1/3.")
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





def parse_fast_mone_allocation(value: str) -> tuple[float, float] | None:
    """Parse b<VL>/<SL> as a MONE allocation, e.g. b20/10."""
    match = re.fullmatch(
        r"b(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)",
        value.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def parse_fast_maternity_leave(
    value: str,
    working_year: int,
    previous_start: date | None = None,
) -> tuple[date, int] | None:
    """Parse month/day M90 or M105, e.g. 5/12M105."""
    match = re.fullmatch(r"(.+?)m(90|105)", value.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    start_text, duration_text = match.groups()
    start = parse_fast_start(start_text, working_year, previous_start)
    return start, int(duration_text)


def parse_fast_mandatory_vl(value: str) -> float | None:
    """Parse a lone amount as Mandatory Leave, e.g. ``5`` for 5 VL and 0 SL."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)", value.strip())
    return float(match.group(1)) if match else None


def parse_fast_ut_entry(value: str, working_year: int) -> tuple[int, int, float, float] | None:
    """Parse ``month u VL SL``, e.g. ``1 u .004 0`` for January."""
    match = re.fullmatch(
        r"(\d{1,2})\s*u\s*((?:\d+(?:\.\d+)?)|(?:\.\d+))\s*[ /]\s*((?:\d+(?:\.\d+)?)|(?:\.\d+))",
        value.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    month, vl, sl = match.groups()
    return int(month), working_year, float(vl), float(sl)

def split_fast_leave_code(value: str) -> tuple[str, str | None]:
    """Separate an optional Fast Encode leave suffix from the date text.

    Supported suffixes: v for VL, s for SL, w for WL, ss for SPL, f for FL,
    VS for Vacation Leave charged to SL, and SV for Sick Leave charged to VL.
    Example: 9/2/3v means September 2–3 as Vacation Leave.
    """
    text = value.strip()
    match = re.fullmatch(r"(.+?)(vs|sv|ss|v|s|w|f)", text, flags=re.IGNORECASE)
    if not match:
        return text, None
    date_text, suffix = match.groups()
    if not date_text[-1:].isdigit():
        return text, None
    return date_text, {
        "v": "VL", "s": "SL", "w": "WL", "ss": "SPL", "f": "FL",
        "vs": "VS", "sv": "SV",
    }[suffix.casefold()]


def parse_fast_entry(
    value: str,
    working_year: int,
    previous_start: date | None = None,
) -> tuple[date, date, str | None]:
    """Parse a Fast Encode range plus its optional leave-type suffix."""
    date_text, leave_code = split_fast_leave_code(value)
    start, end = parse_fast_range(date_text, working_year, previous_start)
    return start, end, leave_code

def parse_fast_range(
    value: str,
    working_year: int,
    previous_start: date | None = None,
) -> tuple[date, date]:
    """Parse a same- or cross-month Fast Encode range from one textbox."""
    numbers = _numbers(value)
    if len(numbers) not in (2, 3, 4):
        raise FastDateError(
            "Enter month/start day, month/start/end, or month/start/end-month/end-day, "
            "such as 9/1, 9/1/3, or 2/19/3/4."
        )
    month, start_day = numbers[:2]
    start = parse_fast_start(
        f"{month} {start_day}",
        working_year,
        previous_start,
    )
    if len(numbers) == 4:
        end_month, end_day = numbers[2:]
        end_year = start.year + (1 if end_month < start.month else 0)
        end = _date(end_year, end_month, end_day)
    else:
        end_day = numbers[2] if len(numbers) == 3 else start_day
        end = _date(start.year, start.month, end_day)
    if end < start:
        raise FastDateError("The end date cannot be before the start date.")
    return start, end
