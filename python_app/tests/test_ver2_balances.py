import sqlite3
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from leave_calendar.ver2_balances import BalanceLinks, balance_rows, project_balance, suggested_balance_candidates


class BalanceTests(unittest.TestCase):
    def test_parse_zero_missing_invalid_and_name_suggestion(self):
        rows = [["NAME", "VL", "SL"], ["AABLING, JOYCE", 0, 18.75], ["OTHER, PERSON", None, "bad"]]
        data, issues = balance_rows("credits.xlsx", "Sheet1", rows)
        self.assertEqual(data[0]["vl"], Decimal("0"))
        self.assertIsNone(data[1]["vl"])
        self.assertIsNone(data[1]["sl"])
        self.assertEqual(len(issues), 1)
        self.assertEqual(suggested_balance_candidates("AABLING, JOYCE JUAREZ", data), [data[0]])

    def test_cutoff_status_duplicate_and_weekend(self):
        balance = {"vl": Decimal("10.500"), "sl": Decimal("15")}
        rows = [
            {"record_key": "a", "start_date": "2026-08-31", "end_date": "2026-09-02", "leave_type": "VL", "status": ""},
            {"record_key": "b", "start_date": "2026-09-01", "end_date": "2026-09-02", "leave_type": "VL", "status": ""},
            {"record_key": "c", "start_date": "2026-09-05", "end_date": "2026-09-07", "leave_type": "SL", "status": ""},
            {"record_key": "cancel", "start_date": "2026-09-08", "end_date": "2026-09-08", "leave_type": "SL", "status": "C"},
            {"record_key": "future", "start_date": "2026-10-01", "end_date": "2026-10-02", "leave_type": "SL", "status": "A"},
        ]
        result = project_balance(balance, rows, {date(2026, 9, 2)}, 1975, 2026, date(2026, 9, 30))
        self.assertEqual((result["used_vl"], result["used_sl"]), (Decimal("1"), Decimal("1")))
        self.assertEqual((result["vl"], result["sl"]), (Decimal("9.500"), Decimal("14")))

    def test_mixed_type_conflict_and_holiday_limit_block_balance(self):
        base = {"vl": Decimal("10"), "sl": Decimal("10")}
        rows = [{"record_key": "a", "start_date": "2026-09-01", "end_date": "2026-09-01", "leave_type": "SL", "status": ""},
                {"record_key": "b", "start_date": "2026-09-01", "end_date": "2026-09-01", "leave_type": "VL", "status": "A"}]
        result = project_balance(base, rows, set(), 1975, 2026, date(2026, 10, 1))
        self.assertTrue(result["review"])
        self.assertIsNone(result["vl"])
        rows = [{"record_key": "f", "start_date": "2027-01-01", "end_date": "2027-01-01", "leave_type": "VL", "status": "A"}]
        self.assertTrue(project_balance(base, rows, set(), 1975, 2026, date(2027, 1, 2))["review"])

    def test_unique_persistent_manual_balance_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = BalanceLinks(Path(tmp) / "test.sqlite")
            db.assign("EMP-1", "source-1")
            with self.assertRaises(ValueError):
                db.assign("EMP-2", "source-1")
            self.assertEqual(db.all(), {"EMP-1": "source-1"})
            db.assign("EMP-1", "source-2")
            self.assertEqual(db.all(), {"EMP-1": "source-2"})


if __name__ == "__main__":
    unittest.main()
