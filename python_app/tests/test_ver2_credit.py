import unittest
from datetime import date
from leave_calendar.ver2_credit import estimate_leave_charge


class EstimateTests(unittest.TestCase):
    def test_dates_include_end_and_exclude_weekends_and_regular_holiday(self):
        result = estimate_leave_charge(date(2026, 9, 12), date(2026, 9, 22), "SL", {date(2026, 9, 16)}, 1975, 2026)
        self.assertEqual(result, (11, 6, 0.0, 6.0))

    def test_forced_leave_charges_vl(self):
        result = estimate_leave_charge(date(2026, 9, 21), date(2026, 9, 22), "FL", set(), 1975, 2026)
        self.assertEqual(result, (2, 2, 2.0, 0.0))

    def test_weekend_only_and_missing_holiday_year(self):
        self.assertEqual(estimate_leave_charge(date(2026, 9, 26), date(2026, 9, 27), "VL", set(), 1975, 2026), (2, 0, 0.0, 0.0))
        self.assertEqual(estimate_leave_charge(date(2026, 12, 31), date(2027, 1, 2), "VL", set(), 1975, 2026), (3, None, None, None))


if __name__ == "__main__":
    unittest.main()
