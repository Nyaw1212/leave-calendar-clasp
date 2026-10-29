import unittest
from datetime import date
from leave_calendar.ver2_credit import estimate_leave_charge, audit_excluded_dates, duplicate_leave_overlaps


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

    def test_audit_shows_weekend_and_regular_holiday(self):
        hits = audit_excluded_dates(date(2026, 9, 19), date(2026, 9, 21), {date(2026, 9, 21)})
        self.assertEqual(hits, [(date(2026, 9, 19), "SAT"), (date(2026, 9, 20), "SUN"), (date(2026, 9, 21), "RH")])

    def test_overlaps_exclude_cancelled_records(self):
        records = [
            {"record_key": "one", "start_date": "2026-09-19", "end_date": "2026-09-22", "leave_type": "SL", "status": ""},
            {"record_key": "two", "start_date": "2026-09-22", "end_date": "2026-09-23", "leave_type": "VL", "status": "A"},
            {"record_key": "cancelled", "start_date": "2026-09-20", "end_date": "2026-09-20", "leave_type": "VL", "status": "C"},
        ]
        self.assertEqual(duplicate_leave_overlaps(records), {"one": [(date(2026, 9, 22), date(2026, 9, 22))], "two": [(date(2026, 9, 22), date(2026, 9, 22))]})


if __name__ == "__main__":
    unittest.main()
