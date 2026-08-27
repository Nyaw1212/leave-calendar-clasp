from __future__ import annotations

from datetime import date


TIMEANDDATE_CALENDAR_URL = (
    "https://www.timeanddate.com/calendar/custom.html?"
    "year={year}&country=67&cols=3&df=1&hol=4260121"
)


_REGULAR_HOLIDAYS: dict[int, tuple[tuple[date, str], ...]] = {
    2026: (
        (date(2026, 1, 1), "New Year's Day"),
        (date(2026, 3, 20), "Eid al-Fitr Holiday"),
        (date(2026, 4, 2), "Maundy Thursday"),
        (date(2026, 4, 3), "Good Friday"),
        (date(2026, 4, 9), "The Day of Valor"),
        (date(2026, 5, 1), "Labor Day"),
        (date(2026, 5, 27), "Eid al-Adha"),
        (date(2026, 6, 12), "Independence Day"),
        (date(2026, 8, 31), "National Heroes Day"),
        (date(2026, 11, 30), "Bonifacio Day"),
        (date(2026, 12, 25), "Christmas Day"),
        (date(2026, 12, 30), "Rizal Day"),
    ),
}


def timeanddate_calendar_url(year: int) -> str:
    return TIMEANDDATE_CALENDAR_URL.format(year=int(year))


def regular_holidays_for_year(year: int) -> tuple[tuple[date, str], ...]:
    """Return the reviewed Timeanddate regular-holiday rows bundled with the app."""
    return _REGULAR_HOLIDAYS.get(int(year), ())
