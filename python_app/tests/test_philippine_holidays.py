import unittest
import threading
from datetime import date

from leave_calendar.philippine_holidays import (
    regular_holidays_for_year,
    timeanddate_calendar_url,
)
from leave_calendar.repository import SheetsRepository


class _Worksheet:
    def __init__(self) -> None:
        self.deleted: list[int] = []
        self.appended: list[list[str]] = []
        self.value_input_option = ""

    def delete_rows(self, row_number: int) -> None:
        self.deleted.append(row_number)

    def append_rows(self, rows, value_input_option: str) -> None:
        self.appended = rows
        self.value_input_option = value_input_option


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

    def test_sheet_import_keeps_iso_dates_raw_to_avoid_timezone_shift(self) -> None:
        worksheet = _Worksheet()
        repository = SheetsRepository.__new__(SheetsRepository)
        repository._lock = threading.RLock()
        repository._cache = {}
        repository._worksheet = lambda _title: worksheet
        repository._values = lambda _title, force=False: [
            ["Date", "Holiday Name", "Holiday Type", "Year", "Source", "Imported At"],
            ["03/19/2026", "Old shifted date", "Regular Holiday", "2026", "", ""],
        ]

        count = repository.replace_regular_holidays(
            2026,
            ((date(2026, 3, 20), "Eid al-Fitr Holiday"),),
        )

        self.assertEqual(count, 1)
        self.assertEqual(worksheet.deleted, [2])
        self.assertEqual(worksheet.value_input_option, "RAW")
        self.assertEqual(worksheet.appended[0][0], "2026-03-20")


if __name__ == "__main__":
    unittest.main()
