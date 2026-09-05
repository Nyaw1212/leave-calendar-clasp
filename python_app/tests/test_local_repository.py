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

    def test_credit_entries_persist_and_follow_sheet_month_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "leave_calendar.db"
            repository = LocalRepository(database)
            repository.connect()
            employee, _created = repository.get_or_create_employee("Credit Sample")

            october = repository.add_credit_entry(employee.employee_id, 10, 2018)
            december = repository.add_credit_entry(employee.employee_id, 12, 2018)
            september = repository.add_credit_entry(employee.employee_id, 9, 2018)

            self.assertEqual(october.vl_earned, 1.25)
            self.assertEqual(december.vl_earned, 2.5)
            self.assertEqual((september.year, september.vl_earned), (2019, 11.25))

            reopened = LocalRepository(database)
            reopened.connect()
            rows = reopened.credit_entries(employee.employee_id)
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[-1], september)
            self.assertTrue(reopened.delete_last_credit_entry(employee.employee_id))
            self.assertEqual(len(reopened.credit_entries(employee.employee_id)), 2)

    def test_opening_and_monthly_credits_drive_current_balances(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(
                Path(temporary_directory) / "leave_calendar.db"
            )
            repository.connect()
            employee, _created = repository.get_or_create_employee("Opening Sample")
            employee = repository.save_employee_profile(
                employee.employee_id,
                date(2018, 10, 1),
            )
            repository.add_credit_entry(employee.employee_id, 12, 2018)

            profile = repository.employee_profile(employee)

            self.assertEqual(repository.credit_opening(employee.employee_id), (1.25, 1.25))
            self.assertEqual(profile.opening_vl, 1.25)
            self.assertEqual(profile.opening_sl, 1.25)
            self.assertEqual(profile.earned_vl, 2.5)
            self.assertEqual(profile.earned_sl, 2.5)
            self.assertEqual(profile.balance_vl, 3.75)
            self.assertEqual(profile.balance_sl, 3.75)

    def test_first_credit_month_uses_assumption_month_as_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(
                Path(temporary_directory) / "leave_calendar.db"
            )
            repository.connect()
            employee, _created = repository.get_or_create_employee("Baseline Sample")
            employee = repository.save_employee_profile(
                employee.employee_id,
                date(2019, 10, 1),
            )

            november = repository.add_credit_entry(employee.employee_id, 11, 2019)

            self.assertEqual((november.month, november.year), (11, 2019))
            self.assertEqual(november.vl_earned, 1.25)

    def test_deleting_credit_row_recalculates_later_month_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(
                Path(temporary_directory) / "leave_calendar.db"
            )
            repository.connect()
            employee, _created = repository.get_or_create_employee("Delete Credit")
            employee = repository.save_employee_profile(
                employee.employee_id,
                date(2019, 10, 1),
            )
            november = repository.add_credit_entry(employee.employee_id, 11, 2019)
            repository.add_credit_entry(employee.employee_id, 1, 2019)

            self.assertTrue(
                repository.delete_credit_entry(employee.employee_id, november.entry_id)
            )

            remaining = repository.credit_entries(employee.employee_id)
            self.assertEqual(len(remaining), 1)
            self.assertEqual((remaining[0].month, remaining[0].year), (1, 2020))
            self.assertEqual(remaining[0].vl_earned, 3.75)


if __name__ == "__main__":
    unittest.main()
