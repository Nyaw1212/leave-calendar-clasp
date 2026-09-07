import unittest
from datetime import date

from leave_calendar.date_input import DateInputError, parse_assumption_date


class DateInputTests(unittest.TestCase):
    def test_space_separated_short_date(self) -> None:
        self.assertEqual(parse_assumption_date("10 1 19"), date(2019, 10, 1))

    def test_existing_iso_format_still_works(self) -> None:
        self.assertEqual(parse_assumption_date("2019-10-01"), date(2019, 10, 1))

    def test_four_digit_year_and_slashes_work(self) -> None:
        self.assertEqual(parse_assumption_date("10/1/2019"), date(2019, 10, 1))

    def test_invalid_date_is_rejected(self) -> None:
        with self.assertRaises(DateInputError):
            parse_assumption_date("13 40 19")


if __name__ == "__main__":
    unittest.main()
