import unittest

from leave_calendar.credits import CreditOrderError, calculate_credit_entry


class CreditCalculationTests(unittest.TestCase):
    def test_first_row_earns_one_month(self) -> None:
        row = calculate_credit_entry(10, 2018, 1.25)
        self.assertEqual((row.year, row.vl_earned, row.sl_earned), (2018, 1.25, 1.25))

    def test_sheet1_month_gaps_are_reproduced(self) -> None:
        december = calculate_credit_entry(12, 2018, 1.25, 10, 2018)
        september = calculate_credit_entry(9, 2018, 1.25, 12, 2018)
        self.assertEqual((december.year, december.vl_earned), (2018, 2.5))
        self.assertEqual((september.year, september.vl_earned), (2019, 11.25))

    def test_same_month_is_check_order(self) -> None:
        with self.assertRaises(CreditOrderError):
            calculate_credit_entry(9, 2019, 1.25, 9, 2019)


if __name__ == "__main__":
    unittest.main()
