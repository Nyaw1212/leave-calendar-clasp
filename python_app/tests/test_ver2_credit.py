import unittest
from datetime import date
from leave_calendar.ver2_credit import estimate_leave_charge, audit_excluded_dates, duplicate_leave_overlaps, allocate_unique_estimates


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

    def test_identical_and_partial_same_type_leave_counts_dates_once(self):
        rows = [
            {"record_key": "one", "start_date": "2026-09-28", "end_date": "2026-09-30", "leave_type": "SL", "status": "", "source_row": 2},
            {"record_key": "two", "start_date": "2026-09-28", "end_date": "2026-09-30", "leave_type": "SL", "status": "", "source_row": 3},
            {"record_key": "three", "start_date": "2026-09-30", "end_date": "2026-10-02", "leave_type": "SL", "status": "", "source_row": 4},
        ]
        result = allocate_unique_estimates(rows, set(), 1975, 2026)
        self.assertEqual(sum(row["sl"] for row in result.values()), 5.0)
        self.assertEqual(result["one"]["sl"], 3.0)
        self.assertEqual(result["two"]["sl"], 0.0)
        self.assertEqual(result["three"]["sl"], 2.0)

    def test_different_types_require_review_and_approved_wins_same_type(self):
        rows = [
            {"record_key": "unknown", "start_date": "2026-09-28", "end_date": "2026-09-29", "leave_type": "SL", "status": ""},
            {"record_key": "approved", "start_date": "2026-09-28", "end_date": "2026-09-29", "leave_type": "SL", "status": "A"},
            {"record_key": "vl", "start_date": "2026-09-29", "end_date": "2026-09-29", "leave_type": "VL", "status": "A"},
            {"record_key": "cancelled", "start_date": "2026-09-28", "end_date": "2026-09-29", "leave_type": "VL", "status": "C"},
        ]
        result = allocate_unique_estimates(rows, set(), 1975, 2026)
        self.assertEqual(result["approved"]["sl"], 1)
        self.assertEqual(result["unknown"]["sl"], 0)
        self.assertEqual(result["vl"]["conflicts"], [date(2026, 9, 29)])
        self.assertTrue(result["cancelled"]["excluded"])

    def test_unknown_holidays_do_not_steal_or_allocate_overlapping_days(self):
        rows = [
            {"record_key": "cross", "start_date": "2026-12-30", "end_date": "2027-01-02", "leave_type": "VL", "status": "A"},
            {"record_key": "inside", "start_date": "2026-12-30", "end_date": "2026-12-31", "leave_type": "VL", "status": "A"},
        ]
        result = allocate_unique_estimates(rows, set(), 1975, 2026)
        self.assertTrue(result["cross"]["unavailable"])
        self.assertTrue(result["inside"]["unavailable"])


if __name__ == "__main__":
    unittest.main()
