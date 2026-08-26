import unittest
from datetime import date

from leave_calendar.calendar_navigation import (
    add_months,
    calendar_column_count,
    clamp_calendar_month,
)


class CalendarNavigationTests(unittest.TestCase):
    def test_calendar_can_start_in_1975(self) -> None:
        self.assertEqual(clamp_calendar_month(date(1975, 1, 31)), date(1975, 1, 1))

    def test_calendar_does_not_move_before_1975(self) -> None:
        previous = add_months(date(1975, 1, 1), -1)
        self.assertEqual(clamp_calendar_month(previous), date(1975, 1, 1))

    def test_calendar_keeps_historical_month(self) -> None:
        self.assertEqual(clamp_calendar_month(date(1984, 7, 12)), date(1984, 7, 1))

    def test_add_months_crosses_year_boundary(self) -> None:
        self.assertEqual(add_months(date(1975, 12, 1), 1), date(1976, 1, 1))

    def test_twelve_month_view_uses_four_columns(self) -> None:
        self.assertEqual(calendar_column_count(12), 4)
        self.assertEqual(calendar_column_count(6), 3)


if __name__ == "__main__":
    unittest.main()
