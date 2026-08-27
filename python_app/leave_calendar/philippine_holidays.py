from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from .models import Holiday


HOLIDAY_MIN_YEAR = 1975
HOLIDAY_MAX_YEAR = 2026
REGULAR_HOLIDAY = "Regular Holiday"
SPECIAL_NON_WORKING_HOLIDAY = "Special Non-Working Holiday"
SPECIAL_WORKING_HOLIDAY = "Special Working Holiday"
TIMEANDDATE_CALENDAR_URL = (
    "https://www.timeanddate.com/calendar/custom.html?"
    "year={year}&country=67&cols=3&df=1&hol=4260121"
)


# Confirmed nationwide regular-holiday dates. Eid al-Fitr became a national
# regular holiday in 2002; Eid al-Adha first appears as regular in the linked
# Timeanddate Philippines history in 2009.
_EID_AL_FITR = {
    2002: (12, 6), 2003: (11, 26), 2004: (11, 14), 2005: (11, 4),
    2006: (10, 24), 2007: (10, 12), 2008: (10, 1), 2009: (9, 21),
    2010: (9, 10), 2011: (8, 30), 2012: (8, 20), 2013: (8, 9),
    2014: (7, 29), 2015: (7, 17), 2016: (7, 7), 2017: (6, 26),
    2018: (6, 15), 2019: (6, 5), 2020: (5, 25), 2021: (5, 13),
    2022: (5, 3), 2023: (4, 21), 2024: (4, 10), 2025: (4, 1),
    2026: (3, 20),
}
_EID_AL_ADHA = {
    2009: (11, 28), 2010: (11, 17), 2011: (11, 7), 2012: (10, 26),
    2013: (10, 15), 2014: (10, 6), 2015: (9, 25), 2016: (9, 10),
    2017: (9, 2), 2018: (8, 21), 2019: (8, 12), 2020: (7, 31),
    2021: (7, 20), 2022: (7, 9), 2023: (6, 28), 2024: (6, 17),
    2025: (6, 6), 2026: (5, 27),
}

# Nationwide special-day dates aligned with the Philippines rules and
# proclamation exceptions catalogued by the `holidays` project. These dates
# are displayed for audit purposes but do not change VL/SL credit calculations.
_CHINESE_NEW_YEAR = {
    2012: (1, 23), 2013: (2, 10), 2014: (1, 31), 2015: (2, 19),
    2016: (2, 8), 2017: (1, 28), 2018: (2, 16), 2019: (2, 5),
    2020: (1, 25), 2021: (2, 12), 2022: (2, 1), 2024: (2, 10),
    2025: (1, 29), 2026: (2, 17),
}
_ADDITIONAL_SPECIAL_NON_WORKING = {
    2008: ((12, 26, "Additional special (non-working) day"),
           (12, 29, "Additional special (non-working) day")),
    2009: ((11, 2, "Additional special (non-working) day"),
           (12, 24, "Additional special (non-working) day")),
    2010: ((12, 24, "Additional special (non-working) day"),),
    2012: ((11, 2, "Additional special (non-working) day"),),
    2013: ((11, 2, "Additional special (non-working) day"),
           (12, 24, "Additional special (non-working) day")),
    2014: ((12, 24, "Additional special (non-working) day"),
           (12, 26, "Additional special (non-working) day")),
    2015: ((1, 2, "Additional special (non-working) day"),
           (12, 24, "Additional special (non-working) day")),
    2016: ((1, 2, "Additional special (non-working) day"),
           (10, 31, "Additional special (non-working) day"),
           (12, 24, "Additional special (non-working) day")),
    2017: ((1, 2, "Additional special (non-working) day"),
           (10, 31, "Additional special (non-working) day")),
    2018: ((5, 14, "Elections special (non-working) day"),
           (11, 2, "Additional special (non-working) day"),
           (12, 24, "Additional special (non-working) day")),
    2019: ((5, 13, "Elections special (non-working) day"),
           (11, 2, "Additional special (non-working) day"),
           (12, 24, "Additional special (non-working) day")),
    2020: ((11, 2, "Additional special (non-working) day"),
           (12, 24, "Additional special (non-working) day")),
    2022: ((5, 9, "Elections special (non-working) day"),
           (10, 31, "Additional special (non-working) day")),
    2023: ((1, 2, "Additional special (non-working) day"),
           (2, 25, "People Power Anniversary"),
           (10, 30, "Elections special (non-working) day"),
           (11, 2, "Additional special (non-working) day"),
           (12, 24, "Christmas Eve"),
           (12, 26, "Additional special (non-working) day")),
    2024: ((2, 9, "Additional special (non-working) day"),
           (11, 2, "Additional special (non-working) day"),
           (12, 24, "Additional special (non-working) day")),
    2025: ((5, 12, "Elections special (non-working) day"),
           (7, 27, "Founding Anniversary of Iglesia ni Cristo"),
           (10, 31, "All Saints' Day Eve"),
           (12, 24, "Christmas Eve")),
    2026: ((11, 2, "All Souls' Day"), (12, 24, "Christmas Eve")),
}

# Timeanddate also lists nationwide special working days. Keep these separate
# from non-working holidays so they are visible without affecting leave credit.
_SPECIAL_WORKING_DAYS = {
    2023: (
        (1, 23, "First Philippine Republic Day"),
        (7, 27, "Founding Anniversary of Iglesia ni Cristo"),
        (9, 3, "Yamashita Surrender Day"),
        (9, 8, "Feast of the Nativity of Mary"),
    ),
}


def timeanddate_calendar_url(year: int) -> str:
    return TIMEANDDATE_CALENDAR_URL.format(year=int(year))


def local_holidays() -> tuple[Holiday, ...]:
    """Return the complete bundled holiday calendar used by the desktop app."""
    return tuple(
        holiday
        for year in range(HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR + 1)
        for holiday in holidays_for_year(year)
    )


def holidays_for_year(year: int) -> tuple[Holiday, ...]:
    """Return nationwide regular, special non-working, and working holidays."""
    year = int(year)
    if not HOLIDAY_MIN_YEAR <= year <= HOLIDAY_MAX_YEAR:
        return ()

    holidays = [
        Holiday(day, name, REGULAR_HOLIDAY)
        for day, name in _regular_holiday_rows(year)
    ]
    easter = _easter_sunday(year)

    def add_special(day: date, name: str) -> None:
        holidays.append(Holiday(day, name, SPECIAL_NON_WORKING_HOLIDAY))

    if year in _CHINESE_NEW_YEAR:
        month, day = _CHINESE_NEW_YEAR[year]
        add_special(date(year, month, day), "Chinese New Year")

    if 2016 <= year <= 2023 and year != 2017:
        month, day = (2, 24) if year == 2023 else (2, 25)
        add_special(date(year, month, day), "EDSA People Power Revolution Anniversary")

    if year >= 2013:
        add_special(easter - timedelta(days=1), "Black Saturday")

    if year >= 2004:
        exceptions = {2007: (8, 20), 2008: (8, 18), 2010: (8, 23), 2024: (8, 23)}
        month, day = exceptions.get(year, (8, 21))
        add_special(date(year, month, day), "Ninoy Aquino Day")

    add_special(date(year, 11, 1), "All Saints' Day")
    if year >= 2019:
        add_special(date(year, 12, 8), "Feast of the Immaculate Conception of Mary")
    if year not in {2021, 2022}:
        add_special(date(year, 12, 31), "Last Day of the Year")

    for month, day, name in _ADDITIONAL_SPECIAL_NON_WORKING.get(year, ()):
        add_special(date(year, month, day), name)

    special_working_days = list(_SPECIAL_WORKING_DAYS.get(year, ()))
    if 2009 <= year <= 2024 and year not in _SPECIAL_WORKING_DAYS:
        special_working_days.append(
            (7, 27, "Founding Anniversary of Iglesia ni Cristo")
        )
    for month, day, name in special_working_days:
        holidays.append(
            Holiday(
                date(year, month, day),
                name,
                SPECIAL_WORKING_HOLIDAY,
            )
        )
    if year >= 2025:
        holidays.append(
            Holiday(
                date(year, 2, 25),
                "EDSA People Power Revolution Anniversary",
                SPECIAL_WORKING_HOLIDAY,
            )
        )

    return tuple(
        sorted(
            set(holidays),
            key=lambda item: (item.day, item.holiday_type, item.name),
        )
    )


def regular_holidays_for_year(year: int) -> tuple[tuple[date, str], ...]:
    """Return Timeanddate-aligned Philippine regular holidays for 1975–2026."""
    year = int(year)
    if not HOLIDAY_MIN_YEAR <= year <= HOLIDAY_MAX_YEAR:
        return ()

    return tuple(_regular_holiday_rows(year))


def _regular_holiday_rows(year: int) -> tuple[tuple[date, str], ...]:

    easter = _easter_sunday(year)
    labor_day = _nearest_monday(date(year, 5, 1)) if year <= 2011 else date(year, 5, 1)
    holidays = [
        (date(year, 1, 1), "New Year's Day"),
        (easter - timedelta(days=3), "Maundy Thursday"),
        (easter - timedelta(days=2), "Good Friday"),
        (date(year, 4, 10) if year == 2023 else date(year, 4, 9), "The Day of Valor"),
        (labor_day, "Labor Day"),
        (date(year, 6, 12), "Independence Day"),
        (_last_monday(year, 8), "National Heroes Day"),
        (_observed_bonifacio_day(year), "Bonifacio Day"),
        (date(year, 12, 25), "Christmas Day"),
        (_observed_rizal_day(year), "Rizal Day"),
    ]

    if year in _EID_AL_FITR:
        month, day = _EID_AL_FITR[year]
        holidays.append((date(year, month, day), "Eid al-Fitr"))
    if year in _EID_AL_ADHA:
        month, day = _EID_AL_ADHA[year]
        holidays.append((date(year, month, day), "Eid al-Adha"))

    return tuple(sorted(holidays, key=lambda item: (item[0], item[1])))


def _nearest_monday(day: date) -> date:
    previous = day - timedelta(days=day.weekday())
    following = previous + timedelta(days=7)
    return previous if day - previous < following - day else following


def _last_monday(year: int, month: int) -> date:
    day = date(year, month, monthrange(year, month)[1])
    return day - timedelta(days=day.weekday())


def _observed_bonifacio_day(year: int) -> date:
    exceptions = {2008: (12, 1), 2010: (11, 29), 2023: (11, 27)}
    month, day = exceptions.get(year, (11, 30))
    return date(year, month, day)


def _observed_rizal_day(year: int) -> date:
    exceptions = {2008: (12, 29), 2009: (12, 28), 2010: (12, 27)}
    month, day = exceptions.get(year, (12, 30))
    return date(year, month, day)


def _easter_sunday(year: int) -> date:
    """Gregorian computus, valid throughout the app's supported date range."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ell = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ell) // 451
    month, day_offset = divmod(h + ell - 7 * m + 114, 31)
    return date(year, month, day_offset + 1)
