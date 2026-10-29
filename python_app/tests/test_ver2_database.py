import tempfile
import unittest
from pathlib import Path

from leave_calendar.ver2_database import Ver2Database


class Ver2DatabaseTests(unittest.TestCase):
    def test_import_preserves_repeated_rows_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Ver2Database(Path(folder) / "db.sqlite")
            rows = [["Emp_Name", "start_at", "end_at", "TYPE"],
                    ["Smith, Jane", "2026-09-01", "2026-09-02", "VL"],
                    ["Smith, Jane", "2026-09-01", "2026-09-02", "VL"]]
            self.assertEqual(db.import_sheet("VL", "sept.xls", "Sheet1", rows), (2, []))
            self.assertEqual(db.import_sheet("VL", "sept.xls", "Sheet1", rows), (0, []))
            self.assertEqual(len(db.records()), 2)
            self.assertEqual(db.records()[0]["status"], "")

    def test_invalid_rows_are_reported_and_not_imported(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Ver2Database(Path(folder) / "db.sqlite")
            rows = [["Emp_Name", "start_at", "end_at", "TYPE"],
                    ["Smith, Jane", "2026-09-05", "2026-09-01", "VL"],
                    ["Smith, Jane", "2026-09-01", "2026-09-02", "SL"]]
            added, errors = db.import_sheet("VL", "sept.xls", "Sheet1", rows)
            self.assertEqual(added, 0)
            self.assertEqual(len(errors), 2)
            self.assertEqual(db.records(), [])


if __name__ == "__main__":
    unittest.main()
