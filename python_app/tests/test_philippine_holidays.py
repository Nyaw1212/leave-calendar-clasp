import unittest
from datetime import date

from leave_calendar.philippine_holidays import (
    regular_holidays_for_year,
    timeanddate_calendar_url,
)


class PhilippineHolidayTests(unittest.TestCase):
    def test_2026_contains_only_the_twelve_regular_holidays(self) -> None:
        holidays = regular_holidays_for_year(2026)
        self.assertEqual(len(holidays), 12)
        self.assertIn((date(2026, 1, 1), "New Year's Day"), holidays)
        self.assertIn((date(2026, 12, 30), "Rizal Day"), holidays)

    def test_unreviewed_year_is_empty(self) -> None:
        self.assertEqual(regular_holidays_for_year(2027), ())

    def test_source_url_tracks_the_calendar_year(self) -> None:
        url = timeanddate_calendar_url(2026)
        self.assertIn("year=2026", url)
        self.assertIn("country=67", url)
        self.assertIn("hol=4260121", url)


if __name__ == "__main__":
    unittest.main()
