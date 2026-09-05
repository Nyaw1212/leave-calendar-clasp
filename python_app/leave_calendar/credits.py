from __future__ import annotations

from dataclasses import dataclass


MONTH_NAMES = (
    "JANUARY",
    "FEBRUARY",
    "MARCH",
    "APRIL",
    "MAY",
    "JUNE",
    "JULY",
    "AUGUST",
    "SEPTEMBER",
    "OCTOBER",
    "NOVEMBER",
    "DECEMBER",
)


class CreditOrderError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CreditCalculation:
    month: int
    year: int
    vl_earned: float
    sl_earned: float
    month_gap: int


def calculate_credit_entry(
    month: int,
    starting_year: int,
    rate: float = 1.25,
    previous_month: int | None = None,
    previous_year: int | None = None,
) -> CreditCalculation:
    if not 1 <= int(month) <= 12:
        raise ValueError("Month must be from 1 through 12.")
    if int(starting_year) < 1:
        raise ValueError("Enter a valid starting year.")
    if float(rate) < 0:
        raise ValueError("Credits per month cannot be negative.")

    month = int(month)
    rate = round(float(rate), 3)
    if previous_month is None or previous_year is None:
        return CreditCalculation(month, int(starting_year), rate, rate, 1)

    previous_month = int(previous_month)
    previous_year = int(previous_year)
    year = previous_year + (1 if month < previous_month else 0)
    month_gap = 12 * (year - previous_year) + month - previous_month
    if month_gap <= 0:
        raise CreditOrderError(
            "This month does not come after the previous credit row."
        )
    earned = round(month_gap * rate, 3)
    return CreditCalculation(month, year, earned, earned, month_gap)


def month_name(month: int) -> str:
    return MONTH_NAMES[int(month) - 1]
