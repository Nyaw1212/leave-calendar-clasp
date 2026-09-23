import tempfile
import unittest
import sqlite3
from datetime import date
from pathlib import Path

from leave_calendar.local_repository import LocalRepository
from leave_calendar.models import DraftEntry, LeaveDay


class LocalRepositoryTests(unittest.TestCase):
    def test_existing_database_is_upgraded_with_mone_order_column(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "leave_calendar.db"
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TABLE leave_records (
                    record_id TEXT PRIMARY KEY,
                    leave_type TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'A',
                    vl REAL NOT NULL DEFAULT 0,
                    sl REAL NOT NULL DEFAULT 0,
                    lwop REAL NOT NULL DEFAULT 0,
                    employee_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    remarks TEXT NOT NULL DEFAULT '',
                    timestamp TEXT NOT NULL
                )
                """
            )
            connection.commit()
            connection.close()

            repository = LocalRepository(database)
            repository.connect()

            columns = {
                row[1]
                for row in repository._db().execute("PRAGMA table_info(leave_records)")
            }
            self.assertIn("mone_code", columns)

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

    def test_employee_creation_log_includes_name_and_created_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(Path(temporary_directory) / "leave_calendar.db")
            repository.connect()
            repository.get_or_create_employee("Accomplishment Sample")

            log_rows = repository.employee_creation_log()

            self.assertEqual(log_rows[0][0], "Accomplishment Sample")
            self.assertTrue(log_rows[0][1])

    def test_bis_employee_uses_bis_number_and_saves_magclip_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(Path(temporary_directory) / "leave_calendar.db")
            repository.connect()
            from leave_calendar.models import BisPersonnel

            employee, created = repository.get_or_create_bis_employee(
                BisPersonnel("3819-1123", "AABLING, JOYCE JUAREZ", "CO1")
            )
            saved = repository.save_magclip_name(employee.employee_id, "JOYCE JUAREZ")

            self.assertTrue(created)
            self.assertEqual(employee.employee_id, "3819-1123")
            self.assertEqual(saved.magclip_name, "JOYCE JUAREZ")

    def test_exact_bis_link_replaces_man_id_and_preserves_leave_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(Path(temporary_directory) / "leave_calendar.db")
            repository.connect()
            employee, _created = repository.get_or_create_employee("BIS SAMPLE")
            repository.save_magclip_name(employee.employee_id, "MAGCLIP SAMPLE")
            repository.save_draft(
                employee,
                [
                    DraftEntry(
                        entry_id="bis-link-history",
                        leave_type="Sick Leave",
                        days=(LeaveDay(date(2026, 7, 7), 1.0),),
                    )
                ],
            )
            repository._db().execute(
                """
                INSERT INTO bis_personnel (
                    employee_number, name, rank, gender, office, imported_at
                ) VALUES (?, ?, '', '', '', '2026-01-01 00:00:00')
                """,
                ("BIS-123", "BIS SAMPLE"),
            )
            repository._db().commit()

            linked, skipped, remapped = repository.link_manual_employees_to_bis()

            self.assertEqual((linked, skipped), (1, 0))
            self.assertEqual(remapped[employee.employee_id], "BIS-123")
            linked_employee = repository.employee_by_id("BIS-123")
            self.assertIsNotNone(linked_employee)
            assert linked_employee is not None
            self.assertEqual(linked_employee.magclip_name, "MAGCLIP SAMPLE")
            self.assertEqual(repository.leave_records("BIS-123")[0].employee_id, "BIS-123")

    def test_manual_bis_id_assignment_moves_existing_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(Path(temporary_directory) / "leave_calendar.db")
            repository.connect()
            employee, _created = repository.get_or_create_employee("PREVIOUS JOB")
            repository.save_draft(
                employee,
                [
                    DraftEntry(
                        entry_id="manual-bis-link",
                        leave_type="Sick Leave",
                        days=(LeaveDay(date(2026, 7, 7), 1.0),),
                    )
                ],
            )
            repository._db().execute(
                """
                INSERT INTO bis_personnel (
                    employee_number, name, rank, gender, office, imported_at
                ) VALUES (?, ?, '', '', '', '2026-01-01 00:00:00')
                """,
                ("BIS-456", "BIS CORRECTED NAME"),
            )
            repository._db().commit()

            moved = repository.assign_employee_to_bis_id(employee.employee_id, "BIS-456")

            self.assertEqual(moved.employee_id, "BIS-456")
            self.assertEqual(moved.name, "BIS CORRECTED NAME")
            self.assertEqual(repository.leave_records("BIS-456")[0].employee_id, "BIS-456")

    def test_rename_employee_keeps_id_and_updates_saved_history_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(Path(temporary_directory) / "leave_calendar.db")
            repository.connect()
            employee, _created = repository.get_or_create_employee("Original Name")
            repository.save_draft(
                employee,
                [
                    DraftEntry(
                        entry_id="rename-history",
                        leave_type="Sick Leave",
                        days=(LeaveDay(date(2026, 7, 7), 1.0),),
                    )
                ],
            )

            renamed = repository.rename_employee(employee.employee_id, "Corrected Name")

            self.assertEqual(renamed.employee_id, employee.employee_id)
            self.assertEqual(renamed.name, "Corrected Name")
            self.assertEqual(
                repository.leave_records(employee.employee_id)[0].name,
                "Corrected Name",
            )

    def test_local_leave_type_shortcuts_are_unique(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(Path(temporary_directory) / "leave_calendar.db")
            repository.connect()
            options = repository.leave_types()

            shortcuts = [option.shortcut for option in options if option.shortcut]
            self.assertEqual(len(shortcuts), len(set(shortcuts)))
            self.assertIn("Vacation Leave", {option.name for option in options})
            self.assertIn("MONE", {option.name for option in options})

    def test_mandatory_leave_persists_and_reduces_current_balances(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(
                Path(temporary_directory) / "leave_calendar.db"
            )
            repository.connect()
            employee, _created = repository.get_or_create_employee("Mandatory Sample")
            employee = repository.save_employee_profile(
                employee.employee_id,
                date(2025, 1, 1),
            )

            saved = repository.save_mandatory_leave(
                employee,
                [(2025, 5.0, 2.0), (2026, 3.0, 1.0)],
            )
            profile = repository.employee_profile(
                employee,
                as_of_date=date(2026, 9, 1),
            )

            self.assertEqual([record.year for record in saved], [2025, 2026])
            self.assertEqual(profile.used_vl, 8.0)
            self.assertEqual(profile.used_sl, 3.0)
            self.assertEqual(
                [(record.vl, record.sl) for record in repository.mandatory_leave_records(
                    employee.employee_id
                )],
                [(5.0, 2.0), (3.0, 1.0)],
            )

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

    def test_mone_amounts_are_independent_of_fixed_order_date_span(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(
                Path(temporary_directory) / "leave_calendar.db"
            )
            repository.connect()
            employee, _created = repository.get_or_create_employee("MONE Register")
            days = tuple(
                LeaveDay(date(2023, 11, day), 0.0) for day in range(1, 31)
            )

            result = repository.save_draft(
                employee,
                [
                    DraftEntry(
                        entry_id="mone-order",
                        leave_type="MONE",
                        days=days,
                        vl_allocation=2.0,
                        sl_allocation=13.0,
                        mone_code="MC# 41-98",
                    )
                ],
            )

            record = repository.leave_records(employee.employee_id)[0]
            self.assertEqual((record.start, record.end), (date(2023, 11, 1), date(2023, 11, 30)))
            self.assertEqual((record.vl, record.sl), (2.0, 13.0))
            self.assertEqual(record.mone_code, "MC# 41-98")
            self.assertEqual(result.zero_credit_dates, 0)
            self.assertEqual(result.magclip_rows[0][0], "MC# 41-98")

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

    def test_saved_leave_type_and_dates_can_be_edited_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(
                Path(temporary_directory) / "leave_calendar.db"
            )
            repository.connect()
            employee, _created = repository.get_or_create_employee("Edit Sample")
            repository.save_draft(
                employee,
                [
                    DraftEntry(
                        entry_id="edit-draft",
                        leave_type="Sick Leave",
                        days=tuple(
                            LeaveDay(date(2023, 11, day), 1.0)
                            for day in range(24, 29)
                        ),
                    )
                ],
            )
            original = repository.leave_records(employee.employee_id)[0]
            self.assertEqual(original.sl, 2.0)

            self.assertTrue(
                repository.update_leave_record(
                    original.record_id,
                    employee.employee_id,
                    "Forced Leave",
                    date(2023, 11, 28),
                    date(2023, 11, 29),
                )
            )
            updated = repository.leave_records(employee.employee_id)[0]

            self.assertEqual(updated.record_id, original.record_id)
            self.assertEqual(updated.leave_type, "Forced Leave")
            self.assertEqual(
                (updated.start, updated.end),
                (date(2023, 11, 28), date(2023, 11, 29)),
            )
            self.assertEqual((updated.vl, updated.sl), (2.0, 0.0))

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

    def test_current_balances_ignore_manual_credit_ledger(self) -> None:
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
            repository.add_credit_entry(employee.employee_id, 11, 2018)

            profile = repository.employee_profile(
                employee,
                as_of_date=date(2018, 12, 1),
            )

            self.assertEqual(repository.credit_opening(employee.employee_id), (1.25, 1.25))
            self.assertEqual(profile.opening_vl, 1.25)
            self.assertEqual(profile.opening_sl, 1.25)
            self.assertEqual(profile.earned_vl, 3.75)
            self.assertEqual(profile.earned_sl, 3.75)
            self.assertEqual(profile.balance_vl, 3.75)
            self.assertEqual(profile.balance_sl, 3.75)

    def test_credit_magclip_starts_with_assumption_month_opening(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(
                Path(temporary_directory) / "leave_calendar.db"
            )
            repository.connect()
            employee, _created = repository.get_or_create_employee("MAGCLIP Opening")
            employee = repository.save_employee_profile(
                employee.employee_id,
                date(2019, 11, 9),
            )
            repository.add_credit_entry(employee.employee_id, 12, 2019)

            rows = repository.credit_magclip_entries(employee.employee_id)

            self.assertEqual(len(rows), 2)
            self.assertEqual((rows[0].month, rows[0].year), (11, 2019))
            self.assertEqual((rows[0].vl_earned, rows[0].sl_earned), (0.917, 0.917))
            self.assertEqual((rows[1].month, rows[1].year), (12, 2019))

    def test_changing_assumption_month_recalculates_existing_credits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = LocalRepository(
                Path(temporary_directory) / "leave_calendar.db"
            )
            repository.connect()
            employee, _created = repository.get_or_create_employee("Recalculation")
            employee = repository.save_employee_profile(
                employee.employee_id,
                date(2019, 7, 1),
            )
            original = repository.add_credit_entry(employee.employee_id, 12, 2019)
            self.assertEqual(original.vl_earned, 6.25)

            repository.save_employee_profile(employee.employee_id, date(2019, 11, 9))
            recalculated = repository.credit_entries(employee.employee_id)[0]

            self.assertEqual((recalculated.month, recalculated.year), (12, 2019))
            self.assertEqual(recalculated.vl_earned, 1.25)
            self.assertEqual(recalculated.sl_earned, 1.25)

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
