import tempfile
import unittest
from pathlib import Path

from leave_calendar.history_import import HistoryImportError, parse_history_text
from leave_calendar.local_repository import LocalRepository


class HistoryImportTests(unittest.TestCase):
    def test_parses_headerless_magclip_rows(self) -> None:
        records = parse_history_text(
            "Chiao\tVacation Leave\t7/14/2026\t7/16/2026\t3\t0\t0\tA"
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].name, "Chiao")
        self.assertEqual(records[0].start.isoformat(), "2026-07-14")
        self.assertEqual(records[0].vl, 3.0)
        self.assertEqual(records[0].status, "A")

    def test_header_can_place_status_before_credits(self) -> None:
        records = parse_history_text(
            "NAME\tTYPE\tSTART\tEND\tSTATUS\tVL\tSL\tLWOP\n"
            "Chiao\tSL\t12/7/2026\t12/8/2026\tA\t0\t2\t0"
        )
        self.assertEqual(records[0].leave_type, "Sick Leave")
        self.assertEqual(records[0].sl, 2.0)

    def test_seven_columns_use_selected_employee(self) -> None:
        records = parse_history_text(
            "VL\t1/2/2012\t1/2/2012\t1\t0\t0\tA",
            default_name="Manual Name",
        )
        self.assertEqual(records[0].name, "Manual Name")

    def test_missing_name_is_rejected_without_selected_employee(self) -> None:
        with self.assertRaisesRegex(HistoryImportError, "NAME is blank"):
            parse_history_text("VL\t1/2/2012\t1/2/2012\t1\t0\t0\tA")

    def test_repository_creates_employee_and_skips_exact_duplicate(self) -> None:
        records = parse_history_text(
            "Chiao\tVacation Leave\t7/14/2026\t7/16/2026\t3\t0\t0\tA"
        )
        with tempfile.TemporaryDirectory() as folder:
            repository = LocalRepository(Path(folder) / "leave.db")
            repository.connect()
            self.assertEqual(repository.import_leave_records(records), (1, 0))
            self.assertEqual(repository.import_leave_records(records), (0, 1))
            employees = repository.employees()
            saved = repository.leave_records(employees[0].employee_id)

        self.assertEqual(len(employees), 1)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].vl, 3.0)


if __name__ == "__main__":
    unittest.main()
