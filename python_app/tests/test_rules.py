import unittest
from datetime import date

from leave_calendar.rules import (
    compute_csc_accrual,
    compute_opening_credit,
    credit_for_day,
    group_consecutive_dates,
    normalize_leave_type,
)


class LeaveRulesTests(unittest.TestCase):
    def test_normalizes_magclip_leave_codes(self) -> None:
        self.assertEqual(normalize_leave_type("VL"), "Vacation Leave")
        self.assertEqual(normalize_leave_type("SL"), "Sick Leave")
        self.assertEqual(normalize_leave_type("CTO"), "Compensatory Time Off")

    def test_only_vl_and_sl_carry_credit(self) -> None:
        monday = date(2026, 8, 24)
        self.assertEqual(credit_for_day(monday, "Vacation Leave", 1, set()), 1)
        self.assertEqual(credit_for_day(monday, "Sick Leave", 0.5, set()), 0.5)
        self.assertEqual(credit_for_day(monday, "Forced Leave", 1, set()), 0)

    def test_weekends_and_regular_holidays_are_zero(self) -> None:
        saturday = date(2026, 8, 22)
        monday = date(2026, 8, 24)
        self.assertEqual(credit_for_day(saturday, "Vacation Leave", 1, set()), 0)
        self.assertEqual(credit_for_day(monday, "Vacation Leave", 1, {monday}), 0)

    def test_groups_consecutive_dates(self) -> None:
        values = [date(2026, 8, 1), date(2026, 8, 2), date(2026, 8, 4)]
        groups = group_consecutive_dates(values)
        self.assertEqual(groups, [[values[0], values[1]], [values[2]]])

    def test_csc_accrual_matches_apps_script_basis(self) -> None:
        self.assertEqual(compute_opening_credit(date(2026, 8, 1)), 1.25)
        self.assertEqual(compute_csc_accrual(date(2026, 8, 1), date(2026, 8, 24)), 1.0)
        self.assertEqual(compute_csc_accrual(date(2026, 7, 1), date(2026, 8, 24)), 2.25)


if __name__ == "__main__":
    unittest.main()
