from __future__ import annotations

import re
from datetime import date


class DateInputError(ValueError):
    pass


def _expand_year(value: int) -> int:
    if 0 <= value <= 69:
        return 2000 + value
    if 70 <= value <= 99:
        return 1900 + value
    if 1000 <= value <= 9999:
        return value
    raise DateInputError("Enter a two-digit or four-digit year.")


def parse_assumption_date(value: str) -> date:
    text = value.strip()
    if not text:
        raise DateInputError("Enter a Date of Assumption.")

    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    parts = [part for part in re.split(r"[\s/.-]+", text) if part]
    if len(parts) != 3:
        raise DateInputError("Use MONTH DAY YEAR, for example: 10 1 19.")
    try:
        month, day, year_value = (int(part) for part in parts)
        return date(_expand_year(year_value), month, day)
    except (ValueError, DateInputError) as error:
        if isinstance(error, DateInputError):
            raise
        raise DateInputError(f"Invalid Date of Assumption: {error}") from error
