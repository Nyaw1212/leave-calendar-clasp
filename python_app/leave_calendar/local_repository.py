from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

from .leave_types import LeaveTypeOption
from .credits import calculate_credit_entry
from .models import (
    CreditEntry,
    DraftEntry,
    Employee,
    EmployeeProfile,
    LeaveDay,
    LeaveRecord,
    MandatoryLeaveRecord,
    SaveResult,
)
from .philippine_holidays import local_holidays
from .rules import (
    carries_credit,
    compute_monthly_accrual_through_month,
    compute_opening_credit,
    credit_for_day,
    group_consecutive_dates,
    inclusive_dates,
    is_sl_charge,
    is_mone_charge,
    is_vl_charge,
    prorated_usage,
)
from .settings import app_data_dir


class LocalRepositoryError(RuntimeError):
    pass


LOCAL_LEAVE_TYPES = (
    LeaveTypeOption("Vacation Leave", "VL", "4", "Vacation Leave (VL)"),
    LeaveTypeOption("Forced Leave", "FL", "3", "Mandatory / Forced Leave (FL)"),
    LeaveTypeOption("Sick Leave", "SL", "5", "Sick Leave (SL)"),
    LeaveTypeOption("Maternity Leave", "ML", "6", "Maternity Leave"),
    LeaveTypeOption("Paternity Leave", "PL", "P", "Paternity Leave"),
    LeaveTypeOption("Special Privilege Leave", "SPL", "1", "Special Privilege Leave (SPL)"),
    LeaveTypeOption("Solo Parent Leave", "Solo Parent", "S", "Solo Parent Leave"),
    LeaveTypeOption("Study Leave", "Study", "Z", "Study Leave"),
    LeaveTypeOption("10-Day VAWC Leave", "VAWC", "9", "10-Day VAWC Leave"),
    LeaveTypeOption("Rehabilitation Privilege", "RP", "", "Rehabilitation Privilege"),
    LeaveTypeOption(
        "Special Leave Benefits for Women",
        "SLBW",
        "",
        "Special Leave Benefits for Women",
    ),
    LeaveTypeOption(
        "Special Emergency (Calamity) Leave",
        "SEL",
        "",
        "Special Emergency (Calamity) Leave",
    ),
    LeaveTypeOption("Adoption Leave", "AL", "", "Adoption Leave"),
    LeaveTypeOption("Wellness Leave", "WL", "2", "Wellness Leave (WL)"),
    LeaveTypeOption("Others", "Others", "", "Others"),
)


class LocalRepository:
    """SQLite-backed repository for fully offline desktop operation."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "leave_calendar.db"
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    @property
    def spreadsheet_title(self) -> str:
        return "Local Database ✓"

    def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(
                self.path,
                timeout=10,
                check_same_thread=False,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS employees (
                    employee_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE,
                    assumption_date TEXT,
                    earned_vl REAL NOT NULL DEFAULT 0,
                    earned_sl REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS employees_name_nocase
                    ON employees(name COLLATE NOCASE);

                CREATE TABLE IF NOT EXISTS leave_records (
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
                    mone_code TEXT NOT NULL DEFAULT '',
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
                );

                CREATE INDEX IF NOT EXISTS leave_records_employee_dates
                    ON leave_records(employee_id, start_date, end_date);

                CREATE TABLE IF NOT EXISTS credit_entries (
                    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT NOT NULL UNIQUE,
                    employee_id TEXT NOT NULL,
                    month INTEGER NOT NULL,
                    year INTEGER NOT NULL,
                    vl_earned REAL NOT NULL,
                    sl_earned REAL NOT NULL,
                    rate REAL NOT NULL DEFAULT 1.25,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
                );

                CREATE INDEX IF NOT EXISTS credit_entries_employee_sequence
                    ON credit_entries(employee_id, sequence_id);

                CREATE TABLE IF NOT EXISTS credit_openings (
                    employee_id TEXT PRIMARY KEY,
                    opening_vl REAL NOT NULL,
                    opening_sl REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
                );

                CREATE TABLE IF NOT EXISTS mandatory_leave_records (
                    record_id TEXT PRIMARY KEY,
                    employee_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    vl REAL NOT NULL DEFAULT 0,
                    sl REAL NOT NULL DEFAULT 0,
                    timestamp TEXT NOT NULL,
                    UNIQUE(employee_id, year),
                    FOREIGN KEY(employee_id) REFERENCES employees(employee_id)
                );

                CREATE INDEX IF NOT EXISTS mandatory_leave_employee_year
                    ON mandatory_leave_records(employee_id, year);
                """
            )
            leave_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(leave_records)")
            }
            if "mone_code" not in leave_columns:
                connection.execute(
                    "ALTER TABLE leave_records ADD COLUMN mone_code TEXT NOT NULL DEFAULT ''"
                )
            connection.commit()
            self._connection = connection
        except sqlite3.Error as error:
            raise LocalRepositoryError(f"Could not open the local database: {error}") from error

    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise LocalRepositoryError("The local database is not connected.")
        return self._connection

    def employees(self, force: bool = False) -> list[Employee]:
        del force
        with self._lock:
            rows = self._db().execute(
                """
                SELECT employee_id, name, assumption_date, earned_vl, earned_sl
                FROM employees
                ORDER BY name COLLATE NOCASE, employee_id
                """
            ).fetchall()
        return [self._employee_from_row(row) for row in rows]

    def employee_by_id(self, employee_id: str, force: bool = False) -> Employee | None:
        del force
        with self._lock:
            row = self._db().execute(
                """
                SELECT employee_id, name, assumption_date, earned_vl, earned_sl
                FROM employees WHERE employee_id = ?
                """,
                (str(employee_id),),
            ).fetchone()
        return self._employee_from_row(row) if row else None

    def get_or_create_employee(self, name: str) -> tuple[Employee, bool]:
        clean_name = " ".join(str(name or "").split())
        if not clean_name:
            raise LocalRepositoryError("Enter an employee name.")
        with self._lock:
            row = self._db().execute(
                """
                SELECT employee_id, name, assumption_date, earned_vl, earned_sl
                FROM employees WHERE name = ? COLLATE NOCASE
                """,
                (clean_name,),
            ).fetchone()
            if row:
                return self._employee_from_row(row), False

            employee = Employee(
                employee_id=f"MAN-{uuid.uuid4().hex[:8].upper()}",
                name=clean_name,
            )
            self._db().execute(
                """
                INSERT INTO employees (
                    employee_id, name, assumption_date, earned_vl, earned_sl, created_at
                ) VALUES (?, ?, NULL, 0, 0, ?)
                """,
                (
                    employee.employee_id,
                    employee.name,
                    datetime.now().isoformat(sep=" ", timespec="seconds"),
                ),
            )
            self._db().commit()
            return employee, True

    def rename_employee(self, employee_id: str, name: str) -> Employee:
        """Rename an employee without changing their stable generated ID."""
        clean_name = " ".join(str(name or "").split())
        if not clean_name:
            raise LocalRepositoryError("Enter an employee name.")
        with self._lock:
            database = self._db()
            try:
                duplicate = database.execute(
                    """
                    SELECT employee_id FROM employees
                    WHERE name = ? COLLATE NOCASE AND employee_id != ?
                    """,
                    (clean_name, employee_id),
                ).fetchone()
                if duplicate:
                    raise LocalRepositoryError("Another employee already uses that name.")
                cursor = database.execute(
                    "UPDATE employees SET name = ? WHERE employee_id = ?",
                    (clean_name, employee_id),
                )
                if cursor.rowcount != 1:
                    raise LocalRepositoryError("Employee was not found in the local database.")
                database.execute(
                    "UPDATE leave_records SET name = ? WHERE employee_id = ?",
                    (clean_name, employee_id),
                )
                database.execute(
                    "UPDATE mandatory_leave_records SET name = ? WHERE employee_id = ?",
                    (clean_name, employee_id),
                )
                database.commit()
            except LocalRepositoryError:
                database.rollback()
                raise
            except sqlite3.Error as error:
                database.rollback()
                raise LocalRepositoryError(f"Could not rename employee: {error}") from error
        employee = self.employee_by_id(employee_id)
        if employee is None:
            raise LocalRepositoryError("Employee could not be reloaded after renaming.")
        return employee

    def leave_types(self, force: bool = False) -> list[LeaveTypeOption]:
        del force
        return list(LOCAL_LEAVE_TYPES)

    def credit_entries(self, employee_id: str) -> list[CreditEntry]:
        with self._lock:
            rows = self._db().execute(
                """
                SELECT entry_id, employee_id, month, year,
                       vl_earned, sl_earned, rate
                FROM credit_entries
                WHERE employee_id = ?
                ORDER BY sequence_id
                """,
                (employee_id,),
            ).fetchall()
        return [
            CreditEntry(
                entry_id=str(row["entry_id"]),
                employee_id=str(row["employee_id"]),
                month=int(row["month"]),
                year=int(row["year"]),
                vl_earned=float(row["vl_earned"]),
                sl_earned=float(row["sl_earned"]),
                rate=float(row["rate"]),
            )
            for row in rows
        ]

    def credit_opening(self, employee_id: str) -> tuple[float, float] | None:
        with self._lock:
            row = self._db().execute(
                """
                SELECT assumption_date
                FROM employees WHERE employee_id = ?
                """,
                (employee_id,),
            ).fetchone()
        if row is None or not row["assumption_date"]:
            return None
        opening = compute_opening_credit(date.fromisoformat(str(row["assumption_date"])))
        return opening, opening

    def credit_magclip_entries(self, employee_id: str) -> list[CreditEntry]:
        """Return the assumption-month opening followed by monthly credit rows."""
        rows = self.credit_entries(employee_id)
        employee = self.employee_by_id(employee_id)
        opening = self.credit_opening(employee_id)
        if employee is None or employee.assumption_date is None or opening is None:
            return rows
        first = CreditEntry(
            entry_id=f"opening:{employee_id}",
            employee_id=employee_id,
            month=employee.assumption_date.month,
            year=employee.assumption_date.year,
            vl_earned=opening[0],
            sl_earned=opening[1],
            rate=opening[0],
        )
        return [first, *rows]

    def add_credit_entry(
        self,
        employee_id: str,
        month: int,
        starting_year: int,
        rate: float = 1.25,
    ) -> CreditEntry:
        with self._lock:
            database = self._db()
            previous = database.execute(
                """
                SELECT month, year FROM credit_entries
                WHERE employee_id = ?
                ORDER BY sequence_id DESC LIMIT 1
                """,
                (employee_id,),
            ).fetchone()
            assumption = None
            if previous is None:
                assumption = database.execute(
                    "SELECT assumption_date FROM employees WHERE employee_id = ?",
                    (employee_id,),
                ).fetchone()
            assumption_date = (
                date.fromisoformat(str(assumption["assumption_date"]))
                if assumption is not None and assumption["assumption_date"]
                else None
            )
            calculation = calculate_credit_entry(
                month,
                starting_year,
                rate,
                int(previous["month"])
                if previous
                else assumption_date.month if assumption_date else None,
                int(previous["year"])
                if previous
                else assumption_date.year if assumption_date else None,
            )
            entry = CreditEntry(
                entry_id=str(uuid.uuid4()),
                employee_id=employee_id,
                month=calculation.month,
                year=calculation.year,
                vl_earned=calculation.vl_earned,
                sl_earned=calculation.sl_earned,
                rate=round(float(rate), 3),
            )
            try:
                database.execute(
                    """
                    INSERT INTO credit_entries (
                        entry_id, employee_id, month, year,
                        vl_earned, sl_earned, rate, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.entry_id,
                        entry.employee_id,
                        entry.month,
                        entry.year,
                        entry.vl_earned,
                        entry.sl_earned,
                        entry.rate,
                        datetime.now().isoformat(sep=" ", timespec="seconds"),
                    ),
                )
                database.commit()
            except sqlite3.Error as error:
                database.rollback()
                raise LocalRepositoryError(
                    f"Could not save the credit entry: {error}"
                ) from error
        return entry

    def delete_last_credit_entry(self, employee_id: str) -> bool:
        with self._lock:
            database = self._db()
            try:
                cursor = database.execute(
                    """
                    DELETE FROM credit_entries
                    WHERE sequence_id = (
                        SELECT sequence_id FROM credit_entries
                        WHERE employee_id = ?
                        ORDER BY sequence_id DESC LIMIT 1
                    )
                    """,
                    (employee_id,),
                )
                database.commit()
            except sqlite3.Error as error:
                database.rollback()
                raise LocalRepositoryError(
                    f"Could not remove the last credit entry: {error}"
                ) from error
        return cursor.rowcount == 1

    def delete_credit_entry(self, employee_id: str, entry_id: str) -> bool:
        """Remove one credit row and recalculate every later row in sequence."""
        with self._lock:
            database = self._db()
            try:
                rows = database.execute(
                    """
                    SELECT sequence_id, entry_id, month, year, rate
                    FROM credit_entries
                    WHERE employee_id = ?
                    ORDER BY sequence_id
                    """,
                    (employee_id,),
                ).fetchall()
                if not any(str(row["entry_id"]) == entry_id for row in rows):
                    return False
                database.execute(
                    "DELETE FROM credit_entries WHERE employee_id = ? AND entry_id = ?",
                    (employee_id, entry_id),
                )
                remaining = [row for row in rows if str(row["entry_id"]) != entry_id]
                employee_row = database.execute(
                    "SELECT assumption_date FROM employees WHERE employee_id = ?",
                    (employee_id,),
                ).fetchone()
                assumption = (
                    date.fromisoformat(str(employee_row["assumption_date"]))
                    if employee_row is not None and employee_row["assumption_date"]
                    else None
                )
                previous_month = assumption.month if assumption else None
                previous_year = assumption.year if assumption else None
                for row in remaining:
                    starting_year = (
                        previous_year
                        if previous_year is not None
                        else int(row["year"])
                    )
                    calculation = calculate_credit_entry(
                        int(row["month"]),
                        starting_year,
                        float(row["rate"]),
                        previous_month,
                        previous_year,
                    )
                    database.execute(
                        """
                        UPDATE credit_entries
                        SET year = ?, vl_earned = ?, sl_earned = ?
                        WHERE entry_id = ? AND employee_id = ?
                        """,
                        (
                            calculation.year,
                            calculation.vl_earned,
                            calculation.sl_earned,
                            str(row["entry_id"]),
                            employee_id,
                        ),
                    )
                    previous_month = calculation.month
                    previous_year = calculation.year
                database.commit()
            except (sqlite3.Error, ValueError) as error:
                database.rollback()
                raise LocalRepositoryError(
                    f"Could not remove the credit entry: {error}"
                ) from error
        return True

    @staticmethod
    def _recalculate_credit_entries(
        database: sqlite3.Connection,
        employee_id: str,
        assumption_date: date,
    ) -> None:
        rows = database.execute(
            """
            SELECT entry_id, month, year, rate
            FROM credit_entries
            WHERE employee_id = ?
            ORDER BY sequence_id
            """,
            (employee_id,),
        ).fetchall()
        previous_month = assumption_date.month
        previous_year = assumption_date.year
        for row in rows:
            calculation = calculate_credit_entry(
                int(row["month"]),
                previous_year,
                float(row["rate"]),
                previous_month,
                previous_year,
            )
            database.execute(
                """
                UPDATE credit_entries
                SET year = ?, vl_earned = ?, sl_earned = ?
                WHERE entry_id = ? AND employee_id = ?
                """,
                (
                    calculation.year,
                    calculation.vl_earned,
                    calculation.sl_earned,
                    str(row["entry_id"]),
                    employee_id,
                ),
            )
            previous_month = calculation.month
            previous_year = calculation.year

    def leave_records(
        self,
        employee_id: str | None = None,
        force: bool = False,
    ) -> list[LeaveRecord]:
        del force
        where_clause = "WHERE employee_id = ?" if employee_id else ""
        parameters = (employee_id,) if employee_id else ()
        with self._lock:
            rows = self._db().execute(
                f"""
                SELECT leave_type, start_date, end_date, status, vl, sl, lwop,
                       record_id, employee_id, name, remarks, mone_code
                FROM leave_records
                {where_clause}
                ORDER BY start_date, end_date, record_id
                """,
                parameters,
            ).fetchall()
        return [
            LeaveRecord(
                leave_type=str(row["leave_type"]),
                start=date.fromisoformat(str(row["start_date"])),
                end=date.fromisoformat(str(row["end_date"])),
                vl=float(row["vl"]),
                sl=float(row["sl"]),
                lwop=float(row["lwop"]),
                record_id=str(row["record_id"]),
                employee_id=str(row["employee_id"]),
                name=str(row["name"]),
                remarks=str(row["remarks"] or ""),
                status=str(row["status"] or "A"),
                mone_code=str(row["mone_code"] or ""),
            )
            for row in rows
        ]

    def employee_profile(
        self,
        employee: Employee,
        as_of_date: date | None = None,
        force: bool = False,
        records: tuple[LeaveRecord, ...] | list[LeaveRecord] | None = None,
    ) -> EmployeeProfile:
        del force
        as_of = as_of_date or date.today()
        if not employee.assumption_date:
            return EmployeeProfile(
                employee.employee_id,
                employee.name,
                None,
                as_of,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            )

        earned = compute_monthly_accrual_through_month(
            employee.assumption_date,
            as_of,
        )
        opening = compute_opening_credit(employee.assumption_date)
        used_vl = 0.0
        used_sl = 0.0
        employee_records = (
            records
            if records is not None
            else self.leave_records(employee.employee_id)
        )
        for record in employee_records:
            used_vl += prorated_usage(record.start, record.end, as_of, record.vl)
            used_sl += prorated_usage(record.start, record.end, as_of, record.sl)
        for record in self.mandatory_leave_records(employee.employee_id):
            if record.year <= as_of.year:
                used_vl += record.vl
                used_sl += record.sl
        return EmployeeProfile(
            employee.employee_id,
            employee.name,
            employee.assumption_date,
            as_of,
            round(opening, 3),
            round(opening, 3),
            round(earned, 3),
            round(earned, 3),
            round(used_vl, 3),
            round(used_sl, 3),
            round(earned - used_vl, 3),
            round(earned - used_sl, 3),
        )

    def mandatory_leave_records(
        self,
        employee_id: str,
    ) -> list[MandatoryLeaveRecord]:
        with self._lock:
            rows = self._db().execute(
                """
                SELECT record_id, employee_id, name, year, vl, sl
                FROM mandatory_leave_records
                WHERE employee_id = ?
                ORDER BY year
                """,
                (employee_id,),
            ).fetchall()
        return [
            MandatoryLeaveRecord(
                record_id=str(row["record_id"]),
                employee_id=str(row["employee_id"]),
                name=str(row["name"]),
                year=int(row["year"]),
                vl=float(row["vl"]),
                sl=float(row["sl"]),
            )
            for row in rows
        ]

    def save_mandatory_leave(
        self,
        employee: Employee,
        entries: list[tuple[int, float, float]],
    ) -> list[MandatoryLeaveRecord]:
        if not entries:
            raise LocalRepositoryError("Select at least one Mandatory Leave year.")
        timestamp = datetime.now().isoformat(sep=" ", timespec="seconds")
        rows: list[tuple[object, ...]] = []
        for year, vl, sl in entries:
            if year < 1900 or year > 9999:
                raise LocalRepositoryError(f"Invalid Mandatory Leave year: {year}.")
            if vl < 0 or sl < 0 or (vl <= 0 and sl <= 0):
                raise LocalRepositoryError(
                    f"Enter a VL or SL amount greater than zero for {year}."
                )
            rows.append(
                (
                    uuid.uuid4().hex,
                    employee.employee_id,
                    employee.name,
                    year,
                    round(vl, 3),
                    round(sl, 3),
                    timestamp,
                )
            )
        with self._lock:
            database = self._db()
            try:
                database.executemany(
                    """
                    INSERT INTO mandatory_leave_records (
                        record_id, employee_id, name, year, vl, sl, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                database.commit()
            except sqlite3.IntegrityError as error:
                database.rollback()
                raise LocalRepositoryError(
                    "A Mandatory Leave record already exists for one of the selected years."
                ) from error
            except sqlite3.Error as error:
                database.rollback()
                raise LocalRepositoryError(
                    f"Could not save Mandatory Leave: {error}"
                ) from error
        saved_years = {int(row[3]) for row in rows}
        return [
            record
            for record in self.mandatory_leave_records(employee.employee_id)
            if record.year in saved_years
        ]

    def delete_mandatory_leave(self, record_id: str, employee_id: str) -> bool:
        with self._lock:
            try:
                cursor = self._db().execute(
                    """
                    DELETE FROM mandatory_leave_records
                    WHERE record_id = ? AND employee_id = ?
                    """,
                    (record_id, employee_id),
                )
                self._db().commit()
            except sqlite3.Error as error:
                self._db().rollback()
                raise LocalRepositoryError(
                    f"Could not delete Mandatory Leave: {error}"
                ) from error
        return cursor.rowcount == 1

    def save_employee_profile(self, employee_id: str, assumption_date: date) -> Employee:
        earned = compute_monthly_accrual_through_month(
            assumption_date,
            date.today(),
        )
        with self._lock:
            database = self._db()
            try:
                cursor = database.execute(
                    """
                    UPDATE employees
                    SET assumption_date = ?, earned_vl = ?, earned_sl = ?
                    WHERE employee_id = ?
                    """,
                    (assumption_date.isoformat(), earned, earned, employee_id),
                )
                if cursor.rowcount != 1:
                    raise LocalRepositoryError(
                        "Employee was not found in the local database."
                    )
                self._recalculate_credit_entries(
                    database,
                    employee_id,
                    assumption_date,
                )
                database.commit()
            except LocalRepositoryError:
                database.rollback()
                raise
            except (sqlite3.Error, ValueError) as error:
                database.rollback()
                raise LocalRepositoryError(
                    f"Could not save the Date of Entry or recalculate credits: {error}"
                ) from error
        employee = self.employee_by_id(employee_id)
        if employee is None:
            raise LocalRepositoryError("Employee could not be reloaded after saving.")
        return employee

    def delete_leave_record(self, record_id: str, employee_id: str) -> bool:
        with self._lock:
            try:
                cursor = self._db().execute(
                    """
                    DELETE FROM leave_records
                    WHERE record_id = ? AND employee_id = ?
                    """,
                    (record_id, employee_id),
                )
                self._db().commit()
            except sqlite3.Error as error:
                self._db().rollback()
                raise LocalRepositoryError(
                    f"Could not delete saved leave: {error}"
                ) from error
        return cursor.rowcount == 1

    def update_leave_status(
        self,
        record_id: str,
        employee_id: str,
        status: str,
    ) -> bool:
        """Update only a saved leave record's form status."""
        clean_status = _normalize_form_status(status)
        with self._lock:
            try:
                cursor = self._db().execute(
                    """
                    UPDATE leave_records
                    SET status = ?, timestamp = ?
                    WHERE record_id = ? AND employee_id = ?
                    """,
                    (
                        clean_status,
                        datetime.now().isoformat(sep=" ", timespec="seconds"),
                        record_id,
                        employee_id,
                    ),
                )
                self._db().commit()
            except sqlite3.Error as error:
                self._db().rollback()
                raise LocalRepositoryError(
                    f"Could not update saved leave status: {error}"
                ) from error
        return cursor.rowcount == 1

    def update_leave_record(
        self,
        record_id: str,
        employee_id: str,
        leave_type: str,
        start: date,
        end: date,
    ) -> bool:
        """Edit one saved row and recalculate its charge using local leave rules."""
        if end < start:
            raise LocalRepositoryError("End Date cannot be earlier than Start Date.")

        regular_holidays = {
            holiday.day for holiday in local_holidays() if holiday.is_regular
        }
        with self._lock:
            database = self._db()
            existing = database.execute(
                """
                SELECT leave_type, start_date, end_date, vl, sl, lwop
                FROM leave_records
                WHERE record_id = ? AND employee_id = ?
                """,
                (record_id, employee_id),
            ).fetchone()
            if existing is None:
                return False

            old_type = str(existing["leave_type"])
            old_start = date.fromisoformat(str(existing["start_date"]))
            old_end = date.fromisoformat(str(existing["end_date"]))
            old_vl = float(existing["vl"])
            old_sl = float(existing["sl"])
            old_lwop = float(existing["lwop"])
            old_charge = round(old_vl + old_sl, 3)
            old_chargeable_days = sum(
                credit_for_day(day, old_type, 1.0, regular_holidays)
                for day in inclusive_dates(old_start, old_end)
            )
            requested_credit = (
                round(old_charge / old_chargeable_days, 3)
                if carries_credit(old_type)
                and old_chargeable_days > 0
                and old_charge > 0
                else 1.0
            )
            total = round(
                sum(
                    credit_for_day(day, leave_type, requested_credit, regular_holidays)
                    for day in inclusive_dates(start, end)
                ),
                3,
            )

            vl = total if is_vl_charge(leave_type) else 0.0
            sl = total if is_sl_charge(leave_type) else 0.0
            if is_mone_charge(leave_type):
                if is_mone_charge(old_type):
                    vl = min(total, old_vl)
                    sl = round(total - vl, 3)
                else:
                    vl = total
                    sl = 0.0

            try:
                cursor = database.execute(
                    """
                    UPDATE leave_records
                    SET leave_type = ?, start_date = ?, end_date = ?,
                        vl = ?, sl = ?, lwop = ?, timestamp = ?
                    WHERE record_id = ? AND employee_id = ?
                    """,
                    (
                        leave_type,
                        start.isoformat(),
                        end.isoformat(),
                        vl,
                        sl,
                        old_lwop,
                        datetime.now().isoformat(sep=" ", timespec="seconds"),
                        record_id,
                        employee_id,
                    ),
                )
                database.commit()
            except sqlite3.Error as error:
                database.rollback()
                raise LocalRepositoryError(
                    f"Could not update saved leave: {error}"
                ) from error
        return cursor.rowcount == 1

    def import_leave_records(self, records: list[LeaveRecord]) -> tuple[int, int]:
        """Import exact pasted values, creating employees and skipping duplicates."""
        if not records:
            raise LocalRepositoryError("Paste at least one leave-history row.")
        imported = 0
        skipped = 0
        timestamp = datetime.now().isoformat(sep=" ", timespec="seconds")
        with self._lock:
            database = self._db()
            try:
                employees = {
                    str(row["name"]).casefold(): str(row["employee_id"])
                    for row in database.execute(
                        "SELECT employee_id, name FROM employees"
                    ).fetchall()
                }
                signatures = {
                    (
                        str(row["employee_id"]),
                        str(row["leave_type"]).casefold(),
                        str(row["start_date"]),
                        str(row["end_date"]),
                        round(float(row["vl"]), 3),
                        round(float(row["sl"]), 3),
                        round(float(row["lwop"]), 3),
                        str(row["status"]).casefold(),
                    )
                    for row in database.execute(
                        """
                        SELECT employee_id, leave_type, start_date, end_date,
                               vl, sl, lwop, status
                        FROM leave_records
                        """
                    ).fetchall()
                }
                for record in records:
                    clean_name = " ".join(record.name.split())
                    name_key = clean_name.casefold()
                    employee_id = employees.get(name_key)
                    if employee_id is None:
                        employee_id = f"MAN-{uuid.uuid4().hex[:8].upper()}"
                        database.execute(
                            """
                            INSERT INTO employees (
                                employee_id, name, assumption_date,
                                earned_vl, earned_sl, created_at
                            ) VALUES (?, ?, NULL, 0, 0, ?)
                            """,
                            (employee_id, clean_name, timestamp),
                        )
                        employees[name_key] = employee_id
                    signature = (
                        employee_id,
                        record.leave_type.casefold(),
                        record.start.isoformat(),
                        record.end.isoformat(),
                        round(record.vl, 3),
                        round(record.sl, 3),
                        round(record.lwop, 3),
                        (record.status or "A").casefold(),
                    )
                    if signature in signatures:
                        skipped += 1
                        continue
                    database.execute(
                        """
                        INSERT INTO leave_records (
                            record_id, leave_type, start_date, end_date, status,
                            vl, sl, lwop, employee_id, name, remarks, mone_code,
                            timestamp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            record.leave_type,
                            record.start.isoformat(),
                            record.end.isoformat(),
                            record.status or "A",
                            record.vl,
                            record.sl,
                            record.lwop,
                            employee_id,
                            clean_name,
                            record.remarks,
                            record.mone_code,
                            timestamp,
                        ),
                    )
                    signatures.add(signature)
                    imported += 1
                database.commit()
            except sqlite3.Error as error:
                database.rollback()
                raise LocalRepositoryError(
                    f"Could not import pasted history: {error}"
                ) from error
        return imported, skipped

    def _ensure_credit_entries_through(
        self,
        database: sqlite3.Connection,
        employee: Employee,
        leave_months: list[date],
    ) -> None:
        """Create credit rows for every saved leave month and December closings."""
        if employee.assumption_date is None or not leave_months:
            return
        targets = sorted(
            {
                date(value.year, value.month, 1)
                for value in leave_months
            }
        )
        previous = database.execute(
            """
            SELECT month, year, rate FROM credit_entries
            WHERE employee_id = ?
            ORDER BY sequence_id DESC LIMIT 1
            """,
            (employee.employee_id,),
        ).fetchone()
        if previous is None:
            last = date(
                employee.assumption_date.year,
                employee.assumption_date.month,
                1,
            )
            rate = 1.25
        else:
            last = date(int(previous["year"]), int(previous["month"]), 1)
            rate = float(previous["rate"])

        def add_checkpoint(checkpoint: date) -> None:
            nonlocal last
            month_gap = (
                12 * (checkpoint.year - last.year)
                + checkpoint.month
                - last.month
            )
            if month_gap <= 0:
                return
            earned = round(month_gap * rate, 3)
            database.execute(
                """
                INSERT INTO credit_entries (
                    entry_id, employee_id, month, year,
                    vl_earned, sl_earned, rate, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    employee.employee_id,
                    checkpoint.month,
                    checkpoint.year,
                    earned,
                    earned,
                    round(rate, 3),
                    datetime.now().isoformat(sep=" ", timespec="seconds"),
                ),
            )
            last = checkpoint

        for target in targets:
            if target <= last:
                continue
            for year in range(last.year, target.year):
                december = date(year, 12, 1)
                if december > last:
                    add_checkpoint(december)
            add_checkpoint(target)

    def rebuild_credit_entries_from_history(
        self,
        employee: Employee,
    ) -> list[CreditEntry]:
        """Rebuild the BIS credit ledger from the employee's saved leave dates."""
        if employee.assumption_date is None:
            raise LocalRepositoryError("Save the employee's Date of Entry first.")
        leave_months = [
            day
            for record in self.leave_records(employee.employee_id)
            for day in record.calendar_dates
        ]
        with self._lock:
            database = self._db()
            try:
                database.execute(
                    "DELETE FROM credit_entries WHERE employee_id = ?",
                    (employee.employee_id,),
                )
                self._ensure_credit_entries_through(database, employee, leave_months)
                database.commit()
            except sqlite3.Error as error:
                database.rollback()
                raise LocalRepositoryError(
                    f"Could not rebuild credit entries: {error}"
                ) from error
        return self.credit_entries(employee.employee_id)

    def save_draft(self, employee: Employee, entries: list[DraftEntry]) -> SaveResult:
        if not entries:
            raise LocalRepositoryError("Add at least one leave entry to the draft.")

        regular_holidays = {
            holiday.day for holiday in local_holidays() if holiday.is_regular
        }
        records = self.leave_records(employee.employee_id)
        known_dates = {
            day
            for record in records
            if not is_mone_charge(record.leave_type)
            for day in record.calendar_dates
        }
        rows: list[tuple[object, ...]] = []
        magclip_rows: list[tuple[str, ...]] = []
        dates_added = 0
        existing_dates_written = 0
        zero_credit_dates = 0
        timestamp = datetime.now().isoformat(sep=" ", timespec="seconds")

        for entry in entries:
            mone_entry = is_mone_charge(entry.leave_type)
            if mone_entry and (
                entry.vl_allocation is None or entry.sl_allocation is None
            ):
                raise LocalRepositoryError("MONE requires both VL and SL amounts.")
            accepted: list[LeaveDay] = []
            for item in sorted(entry.days, key=lambda value: value.day):
                if not mone_entry and item.day in known_dates:
                    existing_dates_written += 1
                if not mone_entry:
                    known_dates.add(item.day)
                credits = (
                    0.0
                    if mone_entry
                    else credit_for_day(
                        item.day,
                        entry.leave_type,
                        item.credits,
                        regular_holidays,
                    )
                )
                if credits == 0 and not mone_entry:
                    zero_credit_dates += 1
                accepted.append(LeaveDay(item.day, credits))

            dates_added += len(accepted)
            for group in group_consecutive_dates(
                accepted,
                date_getter=lambda value: value.day,
            ):
                total = round(sum(item.credits for item in group), 3)
                vl = total if is_vl_charge(entry.leave_type) else 0.0
                sl = total if is_sl_charge(entry.leave_type) else 0.0
                if mone_entry:
                    vl = round(max(0.0, float(entry.vl_allocation or 0.0)), 3)
                    sl = round(max(0.0, float(entry.sl_allocation or 0.0)), 3)
                record_id = str(uuid.uuid4())
                rows.append(
                    (
                        record_id,
                        entry.leave_type,
                        group[0].day.isoformat(),
                        group[-1].day.isoformat(),
                        _normalize_form_status(entry.status),
                        vl,
                        sl,
                        0.0,
                        employee.employee_id,
                        employee.name,
                        entry.remarks,
                        entry.mone_code if mone_entry else "",
                        timestamp,
                    )
                )
                magclip_rows.append(
                    (
                        entry.mone_code if mone_entry and entry.mone_code else entry.leave_type,
                        group[0].day.strftime("%m/%d/%Y"),
                        group[-1].day.strftime("%m/%d/%Y"),
                        _normalize_form_status(entry.status),
                        _format_credit(vl),
                        _format_credit(sl),
                        _format_credit(0),
                    )
                )

        with self._lock:
            try:
                database = self._db()
                database.executemany(
                    """
                    INSERT INTO leave_records (
                        record_id, leave_type, start_date, end_date, status,
                        vl, sl, lwop, employee_id, name, remarks, mone_code,
                        timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                leave_months = [
                    leave_day.day
                    for entry in entries
                    for leave_day in entry.days
                ]
                self._ensure_credit_entries_through(
                    database,
                    employee,
                    leave_months,
                )
                database.commit()
            except sqlite3.Error as error:
                self._db().rollback()
                raise LocalRepositoryError(f"Could not save leave history: {error}") from error

        return SaveResult(
            rows_written=len(rows),
            dates_added=dates_added,
            existing_dates_written=existing_dates_written,
            zero_credit_dates=zero_credit_dates,
            magclip_rows=tuple(magclip_rows),
        )

    @staticmethod
    def _employee_from_row(row: sqlite3.Row) -> Employee:
        assumption = str(row["assumption_date"] or "")
        return Employee(
            employee_id=str(row["employee_id"]),
            name=str(row["name"]),
            assumption_date=date.fromisoformat(assumption) if assumption else None,
            earned_vl=float(row["earned_vl"]),
            earned_sl=float(row["earned_sl"]),
        )


def _normalize_form_status(status: str) -> str:
    value = str(status or "A").strip().upper()
    if value not in {"A", "C", "D"}:
        raise LocalRepositoryError("Form Status must be A, C, or D.")
    return value


def _format_credit(value: float) -> str:
    return f"{float(value):.3f}"
