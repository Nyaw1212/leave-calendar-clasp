from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import floor


MONE_AUTO_LEVELS: tuple[float, ...] = (30.0, 25.0, 20.0, 15.0, 10.0)
MONE_MINIMUM_VL = 5.0
MONE_MINIMUM_SL = 5.0


def parse_mone_balance_fast_entry(
    value: str,
    *,
    current_year: int | None = None,
) -> tuple[float, float, int | None, int | None]:
    """Parse the compact MONE balance input.

    ``VL SL MONTH`` uses the current year, while ``VL SL MONTH YEAR`` uses the
    supplied year. The older ``VLSL MONTH YEAR`` form remains valid when the
    third value cannot be a month, for example ``10 10 25``.
    """
    pieces = str(value or "").replace(",", " ").split()
    if len(pieces) not in {2, 3, 4}:
        raise ValueError(
            "Enter VL SL, VL SL month, or VL SL month year. "
            "Examples: 4 6 · 4 6 7 · 4 6 7 25."
        )

    def credit(piece: str, label: str) -> float:
        try:
            number = round(float(piece), 3)
        except ValueError as error:
            raise ValueError(f"{label} must be a number.") from error
        if number < 0:
            raise ValueError("VL and SL cannot be negative.")
        return number

    def whole_number(piece: str, label: str) -> int:
        try:
            return int(piece)
        except ValueError as error:
            raise ValueError(f"{label} must be a whole number.") from error

    def normalize_year(raw_year: int) -> int:
        year = raw_year + (2000 if raw_year < 70 else 1900) if raw_year < 100 else raw_year
        if year < 1900:
            raise ValueError("Use a valid last credited year, for example 25.")
        return year

    def with_matching_fraction(
        vl: float, sl: float, vl_text: str, sl_text: str
    ) -> tuple[float, float]:
        # A whole-number SL value may omit the same fractional credit already
        # entered for VL: "10.167 12" means "10.167 12.167".
        if "." in vl_text and "." not in sl_text:
            sl = round(sl + (vl - int(vl)), 3)
        return vl, sl

    if len(pieces) == 2:
        vl, sl = with_matching_fraction(
            credit(pieces[0], "VL"), credit(pieces[1], "SL"), pieces[0], pieces[1]
        )
        return vl, sl, None, None

    if len(pieces) == 3:
        third_value = whole_number(pieces[2], "Month or year")
        if 1 <= third_value <= 12:
            vl, sl = with_matching_fraction(
                credit(pieces[0], "VL"), credit(pieces[1], "SL"), pieces[0], pieces[1]
            )
            return vl, sl, third_value, current_year or date.today().year

        # Keep the earlier one-balance shortcut working: VLSL MONTH YEAR.
        shared = credit(pieces[0], "VL/SL")
        month = whole_number(pieces[1], "Last credited month")
        year = normalize_year(third_value)
        if not 1 <= month <= 12:
            raise ValueError("Use a valid last credited month, for example 7.")
        return shared, shared, month, year

    vl, sl = with_matching_fraction(
        credit(pieces[0], "VL"), credit(pieces[1], "SL"), pieces[0], pieces[1]
    )
    month = whole_number(pieces[2], "Last credited month")
    year = normalize_year(whole_number(pieces[3], "Last credited year"))
    if not 1 <= month <= 12:
        raise ValueError("Use a valid last credited month, for example 7.")
    return vl, sl, month, year


@dataclass(frozen=True, slots=True)
class MoneSuggestion:
    """A safe MONE recommendation that keeps the required leave balances."""

    requested: float | None
    target: float
    mvl: float
    msl: float
    available_vl: float
    available_sl: float

    @property
    def is_requested_limited(self) -> bool:
        return self.requested is not None and self.target < self.requested


def suggest_mone_credits(
    final_vl: float,
    final_sl: float,
    requested: float | None = None,
) -> MoneSuggestion:
    """Suggest MONE credits with SL used before VL.

    Automatic recommendations use the approved 30/25/20/15/10 ladder.  An
    employee request replaces that ladder, but it can never consume the
    protected five VL or five SL credits.
    """
    vl = max(0.0, round(float(final_vl), 3))
    sl = max(0.0, round(float(final_sl), 3))
    available_vl = max(0.0, round(vl - MONE_MINIMUM_VL, 3))
    available_sl = max(0.0, round(sl - MONE_MINIMUM_SL, 3))
    # MONE allocations are whole leave days in increments of five.  Round each
    # source down separately so SL-first allocation can never overdraw a side.
    usable_vl = float(floor(available_vl / 5.0) * 5)
    usable_sl = float(floor(available_sl / 5.0) * 5)
    available_total = usable_vl + usable_sl
    normalized_request = (
        None if requested is None else max(0.0, round(float(requested), 3))
    )
    if normalized_request is None:
        target = next(
            (level for level in MONE_AUTO_LEVELS if available_total >= level),
            0.0,
        )
    else:
        target = float(floor(min(normalized_request, available_total) / 5.0) * 5)

    # SL is consumed first because unused VL can be converted to SL, but the
    # reverse conversion is not available.
    msl = min(usable_sl, target)
    mvl = min(usable_vl, max(0.0, target - msl))
    return MoneSuggestion(
        requested=normalized_request,
        target=round(target, 3),
        mvl=round(mvl, 3),
        msl=round(msl, 3),
        available_vl=available_vl,
        available_sl=available_sl,
    )


@dataclass(frozen=True, slots=True)
class MonePreset:
    order: str
    start: date
    end: date

    @property
    def key(self) -> tuple[str, date, date]:
        return self.order, self.start, self.end


# Fixed MONE order periods transcribed from the supplied MONE workbook.
# VL and SL are deliberately not stored here because they vary by employee.
MONE_PRESETS: tuple[MonePreset, ...] = (
    MonePreset("MC# 41-98", date(2003, 3, 1), date(2003, 3, 10)),
    MonePreset("MC# 41-98", date(2005, 4, 1), date(2005, 4, 10)),
    MonePreset("MC# 41-98", date(2006, 3, 1), date(2006, 3, 15)),
    MonePreset("MC# 41-98", date(2006, 12, 1), date(2006, 12, 15)),
    MonePreset("MC# 41-98", date(2007, 5, 1), date(2007, 5, 10)),
    MonePreset("MC# 41-98", date(2007, 7, 15), date(2007, 7, 31)),
    MonePreset("MC# 41-98", date(2008, 3, 1), date(2008, 3, 15)),
    MonePreset("MC# 41-98", date(2009, 3, 1), date(2009, 3, 20)),
    MonePreset("MC# 41-98", date(2010, 3, 1), date(2010, 3, 20)),
    MonePreset("MC# 41-98", date(2011, 2, 1), date(2011, 2, 20)),
    MonePreset("MC# 41-98", date(2012, 11, 1), date(2012, 11, 15)),
    MonePreset("MC# 41-98", date(2013, 4, 16), date(2013, 4, 30)),
    MonePreset("MC# 14-99", date(2014, 3, 20), date(2014, 3, 30)),
    MonePreset("MC# 41-98", date(2016, 9, 1), date(2016, 9, 30)),
    MonePreset("MC# 41-98", date(2017, 6, 1), date(2017, 6, 30)),
    MonePreset("MC# 41-98", date(2018, 9, 1), date(2018, 9, 30)),
    MonePreset("MC# 16", date(2020, 8, 1), date(2020, 8, 30)),
    MonePreset("MC# 16", date(2021, 6, 1), date(2021, 7, 20)),
    MonePreset("MC# 41-98", date(2022, 11, 21), date(2022, 12, 20)),
    MonePreset("MC# 41-98", date(2023, 11, 1), date(2023, 11, 30)),
    MonePreset("MC# 41-98", date(2024, 10, 1), date(2024, 10, 30)),
    MonePreset("MC# 41-98", date(2025, 11, 16), date(2025, 11, 30)),
)


def mone_display_type(order: str) -> str:
    clean_order = " ".join(str(order or "").split())
    return f"MONE · {clean_order}" if clean_order else "MONE"
