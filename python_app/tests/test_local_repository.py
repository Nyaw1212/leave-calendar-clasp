import tempfile
import unittest
from datetime import date
from pathlib import Path

from leave_calendar.local_repository import LocalRepository
from leave_calendar.models import DraftEntry, LeaveDay


class LocalRepositoryTests(unittest.TestCase):
    def test_employee_and_leave_history_persist_in_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "leave_calendar.db"
            repository = LocalRepository(database)
            repository.connect()

            employee, created = repository.get_or_create_employee("Sample Employee")
            self.assertTrue(created)
            employee = repository.save_employee_profile(
                employee.employee_id,
                date(2021, 9, 21),
            )
            result = repository.save_draft(
                employee,
                [
                    DraftEntry(
                        entry_id="draft-1",
                        leave_type="Vacation Leave",
                        days=(
                            LeaveDay(date(2026, 7, 7), 1.0),
                            LeaveDay(date(2026, 7, 8), 1.0),
                        ),
                    )
                ],
            )

            self.assertEqual(result.rows_written, 1)
            self.assertEqual(result.dates_added, 2)

            reopened = LocalRepository(database)
            reopened.connect()
            employees = reopened.employees()
            records = reopened.leave_records()

            self.assertEqual(len(employees), 1)
            self.assertEqual(employees[0].assumption_date, date(2021, 9, 21))
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].calendar_dates, (date(2026, 7, 7), date(2026, 7, 8)))
            self.assertEqual(records[0].vl, 2.0)

    def test_local_leave_type_shortcuts_are_unique(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(Path(temporary_directory) / "leave_calendar.db")
            repository.connect()
            options = repository.leave_types()

            shortcuts = [option.shortcut for option in options if option.shortcut]
            self.assertEqual(len(shortcuts), len(set(shortcuts)))
            self.assertIn("Vacation Leave", {option.name for option in options})
            self.assertIn("MONE", {option.name for option in options})

    def test_mone_saves_vl_and_automatic_sl_remainder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(
                Path(temporary_directory) / "leave_calendar.db"
            )
            repository.connect()
            employee, _created = repository.get_or_create_employee("MONE Sample")
            weekdays = tuple(
                LeaveDay(date(2026, 9, day), 1.0) for day in range(7, 12)
            )

            result = repository.save_draft(
                employee,
                [
                    DraftEntry(
                        entry_id="mone-draft",
                        leave_type="MONE",
                        days=weekdays,
                        vl_allocation=2.0,
                        sl_allocation=3.0,
                    )
                ],
            )

            record = repository.leave_records(employee.employee_id)[0]
            self.assertEqual(record.leave_type, "MONE")
            self.assertEqual(record.vl, 2.0)
            self.assertEqual(record.sl, 3.0)
            self.assertEqual(result.magclip_rows[0][4:], ("2.000", "3.000", "0.000"))

    def test_mone_counts_weekends_in_saved_allocation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(
                Path(temporary_directory) / "leave_calendar.db"
            )
            repository.connect()
            employee, _created = repository.get_or_create_employee("MONE Weekend")
            friday_to_sunday = tuple(
                LeaveDay(date(2026, 9, day), 1.0) for day in range(4, 7)
            )

            repository.save_draft(
                employee,
                [
                    DraftEntry(
                        entry_id="mone-weekend",
                        leave_type="MONE",
                        days=friday_to_sunday,
                        vl_allocation=1.0,
                        sl_allocation=2.0,
                    )
                ],
            )

            record = repository.leave_records(employee.employee_id)[0]
            self.assertEqual(record.total_credits, 3.0)
            self.assertEqual(record.vl, 1.0)
            self.assertEqual(record.sl, 2.0)

    def test_saved_leave_can_be_deleted_by_exact_record_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(
                Path(temporary_directory) / "leave_calendar.db"
            )
            repository.connect()
            employee, _created = repository.get_or_create_employee("Delete Sample")
            repository.save_draft(
                employee,
                [
                    DraftEntry(
                        entry_id="delete-draft",
                        leave_type="Vacation Leave",
                        days=(LeaveDay(date(2026, 7, 7), 1.0),),
                    )
                ],
            )
            record = repository.leave_records(employee.employee_id)[0]

            self.assertTrue(
                repository.delete_leave_record(record.record_id, employee.employee_id)
            )
            self.assertEqual(repository.leave_records(employee.employee_id), [])
            self.assertFalse(
                repository.delete_leave_record(record.record_id, employee.employee_id)
            )


if __name__ == "__main__":
    unittest.main()
