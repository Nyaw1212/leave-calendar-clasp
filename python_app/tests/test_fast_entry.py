import unittest
from datetime import date

from leave_calendar.fast_entry import FastDateError, parse_fast_end, parse_fast_start


class FastEntryTests(unittest.TestCase):
    def test_space_separated_start_uses_working_year(self) -> None:
        self.assertEqual(parse_fast_start("9 1", 2019), date(2019, 9, 1))

    def test_earlier_month_rolls_into_next_year(self) -> None:
        self.assertEqual(
            parse_fast_start("1 4", 2019, date(2019, 9, 1)),
            date(2020, 1, 4),
        )

    def test_later_month_stays_in_working_year(self) -> None:
        self.assertEqual(
            parse_fast_start("11 2", 2019, date(2019, 9, 1)),
            date(2019, 11, 2),
        )

    def test_day_only_end_reuses_start_month_and_year(self) -> None:
        start = date(2019, 9, 1)
        self.assertEqual(parse_fast_end("3", start), date(2019, 9, 3))

    def test_month_day_end_can_cross_new_year(self) -> None:
        start = date(2019, 12, 30)
        self.assertEqual(parse_fast_end("1 2", start), date(2020, 1, 2))

    def test_end_before_start_is_rejected(self) -> None:
        with self.assertRaises(FastDateError):
            parse_fast_end("1", date(2019, 9, 2))


if __name__ == "__main__":
    unittest.main()
