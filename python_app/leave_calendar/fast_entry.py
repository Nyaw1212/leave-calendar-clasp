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
    """Parse b<VL> <SL> as a MONE allocation, e.g. b20 10."""
    match = re.fullmatch(
        r"b\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)",
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
    """Parse Mandatory Leave VL, e.g. ``5`` or ``mm2`` for 2 VL and 0 SL."""
    match = re.fullmatch(
        r"(?:mm\s*)?(\d+(?:\.\d+)?)",
        value.strip(),
        flags=re.IGNORECASE,
    )
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
    """Separate an optional leading or trailing Fast Encode leave code.

    Supported codes: v for VL, s for SL, w for WL, ss for SPL, f for FL, and
    hq for Home Quarantine. VS is Vacation Leave charged to SL, and SV is
    Sick Leave with a manually distributed VL/SL credit.
    Examples: v5 5 and 5 5v both mean May 5 as Vacation Leave.
    """
    text = value.strip()
    codes = {
        "v": "VL", "s": "SL", "w": "WL", "ss": "SPL", "f": "FL",
        "hq": "HQ", "vs": "VS", "sv": "SV",
    }
    leading = re.fullmatch(
        r"(vs|sv|ss|hq|v|s|w|f)(?:\s+(.+)|(\d.*))",
        text,
        flags=re.IGNORECASE,
    )
    if leading:
        prefix, spaced_date_text, attached_date_text = leading.groups()
        return (spaced_date_text or attached_date_text), codes[prefix.casefold()]

    trailing = re.fullmatch(
        r"(.+?)(vs|sv|ss|hq|v|s|w|f)",
        text,
        flags=re.IGNORECASE,
    )
    if not trailing:
        return text, None
    date_text, suffix = trailing.groups()
    return date_text.strip(), codes[suffix.casefold()]


def parse_fast_individual_dates(
    value: str,
    working_year: int,
    previous_start: date | None = None,
) -> tuple[tuple[date, ...], str] | None:
    """Parse a leading-code same-month list or comma-separated ranges.

    Without commas, f10 11 14 17 20 means individual October dates 11, 14,
    17, and 20. Exactly four numbers remain a cross-month range, so
    v9 27 10 7 means September 27 through October 7. With commas,
    f5 10 11, 13 15 means May 10–11 and May 13–15.
    """
    date_text, leave_code = split_fast_leave_code(value)
    if leave_code is None or leave_code == "SV":
        return None

    if "," in date_text:
        groups = [group.strip() for group in date_text.split(",")]
        if not groups or any(not group for group in groups):
            raise FastDateError("Use comma-separated ranges, such as f5 10 11, 13 15.")
        first_numbers = _numbers(groups[0])
        if len(first_numbers) != 3:
            raise FastDateError(
                "Start with month and a date range, such as f5 10 11, 13 15."
            )
        month, first_start_day, first_end_day = first_numbers
        start = parse_fast_start(
            f"{month} {first_start_day}",
            working_year,
            previous_start,
        )
        range_pairs = [(first_start_day, first_end_day)]
        for group in groups[1:]:
            days = _numbers(group)
            if len(days) != 2:
                raise FastDateError(
                    "Each comma section needs a start and end day, such as 13 15."
                )
            range_pairs.append((days[0], days[1]))

        dates: list[date] = []
        for range_start_day, range_end_day in range_pairs:
            range_start = _date(start.year, month, range_start_day)
            range_end = _date(start.year, month, range_end_day)
            if range_end < range_start:
                raise FastDateError("A comma-separated range cannot end before it starts.")
            dates.extend(
                _date(start.year, month, day)
                for day in range(range_start_day, range_end_day + 1)
            )
        return tuple(sorted(set(dates))), leave_code

    numbers = _numbers(date_text)
    # Four numbers are the established month/start/end-month/end-day format.
    # Individual dates begin at five numbers: month plus at least four days.
    if len(numbers) < 5:
        return None
    month, first_day, *remaining_days = numbers
    start = parse_fast_start(
        f"{month} {first_day}",
        working_year,
        previous_start,
    )
    dates = tuple(_date(start.year, month, day) for day in (first_day, *remaining_days))
    return tuple(sorted(set(dates))), leave_code


def parse_fast_entry(
    value: str,
    working_year: int,
    previous_start: date | None = None,
) -> tuple[date, date, str | None]:
    """Parse a Fast Encode range plus its optional leading leave-type code."""
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
