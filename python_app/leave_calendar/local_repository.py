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
    SaveResult,
)
from .philippine_holidays import local_holidays
from .rules import (
    compute_csc_accrual,
    compute_opening_credit,
    credit_for_day,
    group_consecutive_dates,
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
    LeaveTypeOption("Maternity Leave", "ML", "6", "Maternity Leave (ML)"),
    LeaveTypeOption("Paternity Leave", "PL", "P", "Paternity Leave (PL)"),
    LeaveTypeOption("Special Privilege Leave", "SPL", "1", "Special Privilege Leave (SPL)"),
    LeaveTypeOption("Solo Parent Leave", "Solo Parent", "S", "Solo Parent Leave"),
    LeaveTypeOption("Study Leave", "Study", "Z", "Study Leave"),
    LeaveTypeOption("10-Day VAWC Leave", "VAWC", "9", "10-Day VAWC Leave"),
    LeaveTypeOption("Wellness Leave", "WL", "2", "Wellness Leave (WL)"),
    LeaveTypeOption("MONE", "MONE", "M", "MONE — Allocate VL / SL"),
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
                """
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
                       record_id, employee_id, name, remarks
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
        manual_opening = self.credit_opening(employee.employee_id)
        credit_rows = self.credit_entries(employee.employee_id)
        if manual_opening is not None or credit_rows:
            opening_vl, opening_sl = manual_opening or (0.0, 0.0)
            earned_vl = round(sum(row.vl_earned for row in credit_rows), 3)
            earned_sl = round(sum(row.sl_earned for row in credit_rows), 3)
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
            return EmployeeProfile(
                employee.employee_id,
                employee.name,
                employee.assumption_date,
                as_of,
                opening_vl,
                opening_sl,
                earned_vl,
                earned_sl,
                round(used_vl, 3),
                round(used_sl, 3),
                round(opening_vl + earned_vl - used_vl, 3),
                round(opening_sl + earned_sl - used_sl, 3),
            )

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

        earned = compute_csc_accrual(employee.assumption_date, as_of)
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

    def save_employee_profile(self, employee_id: str, assumption_date: date) -> Employee:
        earned = compute_csc_accrual(assumption_date, date.today())
        with self._lock:
            cursor = self._db().execute(
                """
                UPDATE employees
                SET assumption_date = ?, earned_vl = ?, earned_sl = ?
                WHERE employee_id = ?
                """,
                (assumption_date.isoformat(), earned, earned, employee_id),
            )
            if cursor.rowcount != 1:
                raise LocalRepositoryError("Employee was not found in the local database.")
            self._db().commit()
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
                            vl, sl, lwop, employee_id, name, remarks, timestamp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def save_draft(self, employee: Employee, entries: list[DraftEntry]) -> SaveResult:
        if not entries:
            raise LocalRepositoryError("Add at least one leave entry to the draft.")

        regular_holidays = {
            holiday.day for holiday in local_holidays() if holiday.is_regular
        }
        records = self.leave_records(employee.employee_id)
        known_dates = {
            day for record in records for day in record.calendar_dates
        }
        rows: list[tuple[object, ...]] = []
        magclip_rows: list[tuple[str, ...]] = []
        dates_added = 0
        existing_dates_written = 0
        zero_credit_dates = 0
        timestamp = datetime.now().isoformat(sep=" ", timespec="seconds")

        for entry in entries:
            accepted: list[LeaveDay] = []
            for item in sorted(entry.days, key=lambda value: value.day):
                if item.day in known_dates:
                    existing_dates_written += 1
                known_dates.add(item.day)
                credits = credit_for_day(
                    item.day,
                    entry.leave_type,
                    item.credits,
                    regular_holidays,
                )
                if credits == 0:
                    zero_credit_dates += 1
                accepted.append(LeaveDay(item.day, credits))

            dates_added += len(accepted)
            mone_vl_remaining = 0.0
            mone_sl_remaining = 0.0
            if is_mone_charge(entry.leave_type):
                entry_total = round(sum(item.credits for item in accepted), 3)
                requested_vl = (
                    entry_total
                    if entry.vl_allocation is None
                    else max(0.0, float(entry.vl_allocation))
                )
                mone_vl_remaining = min(entry_total, round(requested_vl, 3))
                mone_sl_remaining = round(entry_total - mone_vl_remaining, 3)
            for group in group_consecutive_dates(
                accepted,
                date_getter=lambda value: value.day,
            ):
                total = round(sum(item.credits for item in group), 3)
                vl = total if is_vl_charge(entry.leave_type) else 0.0
                sl = total if is_sl_charge(entry.leave_type) else 0.0
                if is_mone_charge(entry.leave_type):
                    vl = min(total, mone_vl_remaining)
                    sl = min(round(total - vl, 3), mone_sl_remaining)
                    mone_vl_remaining = round(mone_vl_remaining - vl, 3)
                    mone_sl_remaining = round(mone_sl_remaining - sl, 3)
                record_id = str(uuid.uuid4())
                rows.append(
                    (
                        record_id,
                        entry.leave_type,
                        group[0].day.isoformat(),
                        group[-1].day.isoformat(),
                        "A",
                        vl,
                        sl,
                        0.0,
                        employee.employee_id,
                        employee.name,
                        entry.remarks,
                        timestamp,
                    )
                )
                magclip_rows.append(
                    (
                        entry.leave_type,
                        group[0].day.strftime("%m/%d/%Y"),
                        group[-1].day.strftime("%m/%d/%Y"),
                        "A",
                        _format_credit(vl),
                        _format_credit(sl),
                        _format_credit(0),
                    )
                )

        with self._lock:
            try:
                self._db().executemany(
                    """
                    INSERT INTO leave_records (
                        record_id, leave_type, start_date, end_date, status,
                        vl, sl, lwop, employee_id, name, remarks, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                self._db().commit()
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


def _format_credit(value: float) -> str:
    return f"{float(value):.3f}"
