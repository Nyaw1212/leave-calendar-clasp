import unittest
import threading
from datetime import date

from leave_calendar.philippine_holidays import (
    REGULAR_HOLIDAY,
    SPECIAL_NON_WORKING_HOLIDAY,
    SPECIAL_WORKING_HOLIDAY,
    holidays_for_year,
    local_holidays,
    regular_holidays_for_year,
    timeanddate_calendar_url,
)
from leave_calendar.models import Holiday
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

    def test_full_calendar_history_is_supported(self) -> None:
        self.assertEqual(len(regular_holidays_for_year(1975)), 10)
        self.assertGreaterEqual(len(regular_holidays_for_year(2002)), 11)
        self.assertEqual(regular_holidays_for_year(1974), ())
        self.assertEqual(regular_holidays_for_year(2027), ())

    def test_complete_local_calendar_covers_the_supported_range(self) -> None:
        holidays = local_holidays()
        years = {item.day.year for item in holidays}
        self.assertEqual(min(years), 1975)
        self.assertEqual(max(years), 2026)
        self.assertEqual(len(years), 52)

    def test_1975_matches_historical_timeanddate_calendar(self) -> None:
        holidays = regular_holidays_for_year(1975)
        self.assertIn((date(1975, 3, 27), "Maundy Thursday"), holidays)
        self.assertIn((date(1975, 4, 28), "Labor Day"), holidays)
        self.assertIn((date(1975, 8, 25), "National Heroes Day"), holidays)

    def test_historical_observed_date_exceptions(self) -> None:
        holidays_2008 = regular_holidays_for_year(2008)
        self.assertIn((date(2008, 12, 1), "Bonifacio Day"), holidays_2008)
        self.assertIn((date(2008, 12, 29), "Rizal Day"), holidays_2008)
        self.assertIn((date(2010, 5, 3), "Labor Day"), regular_holidays_for_year(2010))
        self.assertIn((date(2012, 5, 1), "Labor Day"), regular_holidays_for_year(2012))

    def test_confirmed_eid_regular_holidays_are_included(self) -> None:
        self.assertIn(
            (date(2002, 12, 6), "Eid al-Fitr"),
            regular_holidays_for_year(2002),
        )
        self.assertIn(
            (date(2009, 11, 28), "Eid al-Adha"),
            regular_holidays_for_year(2009),
        )

    def test_2023_august_includes_regular_and_special_holidays(self) -> None:
        holidays = holidays_for_year(2023)
        self.assertIn(
            Holiday(date(2023, 8, 21), "Ninoy Aquino Day", SPECIAL_NON_WORKING_HOLIDAY),
            holidays,
        )
        self.assertIn(
            Holiday(date(2023, 8, 28), "National Heroes Day", REGULAR_HOLIDAY),
            holidays,
        )

    def test_2023_matches_timeanddate_nationwide_and_working_dates(self) -> None:
        holidays = holidays_for_year(2023)
        self.assertEqual(len(holidays), 28)
        self.assertIn(
            Holiday(
                date(2023, 2, 25),
                "People Power Anniversary",
                SPECIAL_NON_WORKING_HOLIDAY,
            ),
            holidays,
        )
        self.assertIn(
            Holiday(date(2023, 12, 24), "Christmas Eve", SPECIAL_NON_WORKING_HOLIDAY),
            holidays,
        )
        for day, name in (
            (date(2023, 1, 23), "First Philippine Republic Day"),
            (date(2023, 9, 3), "Yamashita Surrender Day"),
            (date(2023, 9, 8), "Feast of the Nativity of Mary"),
        ):
            self.assertIn(Holiday(day, name, SPECIAL_WORKING_HOLIDAY), holidays)

    def test_all_three_holiday_types_are_available(self) -> None:
        holiday_types = {item.holiday_type for item in holidays_for_year(2026)}
        self.assertEqual(
            holiday_types,
            {REGULAR_HOLIDAY, SPECIAL_NON_WORKING_HOLIDAY, SPECIAL_WORKING_HOLIDAY},
        )
        self.assertIn(
            Holiday(date(2026, 2, 17), "Chinese New Year", SPECIAL_NON_WORKING_HOLIDAY),
            holidays_for_year(2026),
        )

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

    def test_loading_an_already_matching_year_does_not_write_again(self) -> None:
        worksheet = _Worksheet()
        repository = SheetsRepository.__new__(SheetsRepository)
        repository._lock = threading.RLock()
        repository._cache = {}
        repository._worksheet = lambda _title: worksheet
        repository._values = lambda _title, force=False: [
            ["Date", "Holiday Name", "Holiday Type", "Year", "Source", "Imported At"],
            ["2026-01-01", "New Year's Day", "Regular Holiday", "2026", "", ""],
            ["2026-04-09", "Araw ng Kagitingan", "Regular Holiday", "2026", "", ""],
        ]

        count = repository.replace_regular_holidays(
            2026,
            (
                (date(2026, 1, 1), "New Year's Day"),
                (date(2026, 4, 9), "Araw ng Kagitingan"),
            ),
        )

        self.assertEqual(count, 2)
        self.assertEqual(worksheet.deleted, [])
        self.assertEqual(worksheet.appended, [])

    def test_typed_holiday_import_writes_every_category(self) -> None:
        worksheet = _Worksheet()
        repository = SheetsRepository.__new__(SheetsRepository)
        repository._lock = threading.RLock()
        repository._cache = {}
        repository._worksheet = lambda _title: worksheet
        repository._values = lambda _title, force=False: [
            ["Date", "Holiday Name", "Holiday Type", "Year", "Source", "Imported At"],
        ]
        holidays = (
            Holiday(date(2023, 8, 21), "Ninoy Aquino Day", SPECIAL_NON_WORKING_HOLIDAY),
            Holiday(date(2023, 8, 28), "National Heroes Day", REGULAR_HOLIDAY),
            Holiday(date(2023, 7, 27), "INC Anniversary", SPECIAL_WORKING_HOLIDAY),
        )

        count = repository.replace_holidays(2023, holidays)

        self.assertEqual(count, 3)
        self.assertEqual(
            {row[2] for row in worksheet.appended},
            {REGULAR_HOLIDAY, SPECIAL_NON_WORKING_HOLIDAY, SPECIAL_WORKING_HOLIDAY},
        )

    def test_upgrade_appends_missing_special_days_without_deleting_regular_days(self) -> None:
        worksheet = _Worksheet()
        repository = SheetsRepository.__new__(SheetsRepository)
        repository._lock = threading.RLock()
        repository._cache = {}
        repository._worksheet = lambda _title: worksheet
        repository._values = lambda _title, force=False: [
            ["Date", "Holiday Name", "Holiday Type", "Year", "Source", "Imported At"],
            ["2023-08-28", "National Heroes Day", REGULAR_HOLIDAY, "2023", "", ""],
        ]

        count = repository.replace_holidays(
            2023,
            (
                Holiday(
                    date(2023, 8, 21),
                    "Ninoy Aquino Day",
                    SPECIAL_NON_WORKING_HOLIDAY,
                ),
                Holiday(date(2023, 8, 28), "National Heroes Day", REGULAR_HOLIDAY),
            ),
        )

        self.assertEqual(count, 2)
        self.assertEqual(worksheet.deleted, [])
        self.assertEqual(len(worksheet.appended), 1)
        self.assertEqual(worksheet.appended[0][0], "2023-08-21")


if __name__ == "__main__":
    unittest.main()
