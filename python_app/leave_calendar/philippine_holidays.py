from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta


HOLIDAY_MIN_YEAR = 1975
HOLIDAY_MAX_YEAR = 2026
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


def timeanddate_calendar_url(year: int) -> str:
    return TIMEANDDATE_CALENDAR_URL.format(year=int(year))


def regular_holidays_for_year(year: int) -> tuple[tuple[date, str], ...]:
    """Return Timeanddate-aligned Philippine regular holidays for 1975–2026."""
    year = int(year)
    if not HOLIDAY_MIN_YEAR <= year <= HOLIDAY_MAX_YEAR:
        return ()

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
