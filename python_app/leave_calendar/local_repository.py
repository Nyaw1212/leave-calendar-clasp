from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

from .leave_types import LeaveTypeOption
from .models import (
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

    def leave_records(self, force: bool = False) -> list[LeaveRecord]:
        del force
        with self._lock:
            rows = self._db().execute(
                """
                SELECT leave_type, start_date, end_date, vl, sl, lwop,
                       record_id, employee_id, name, remarks
                FROM leave_records
                ORDER BY start_date, end_date, record_id
                """
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
            )
            for row in rows
        ]

    def employee_profile(
        self,
        employee: Employee,
        as_of_date: date | None = None,
        force: bool = False,
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

        earned = compute_csc_accrual(employee.assumption_date, as_of)
        opening = compute_opening_credit(employee.assumption_date)
        used_vl = 0.0
        used_sl = 0.0
        for record in self.leave_records():
            if record.employee_id != employee.employee_id:
                continue
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

    def save_draft(self, employee: Employee, entries: list[DraftEntry]) -> SaveResult:
        if not entries:
            raise LocalRepositoryError("Add at least one leave entry to the draft.")

        regular_holidays = {
            holiday.day for holiday in local_holidays() if holiday.is_regular
        }
        records = [
            record for record in self.leave_records() if record.employee_id == employee.employee_id
        ]
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
            for group in group_consecutive_dates(
                accepted,
                date_getter=lambda value: value.day,
            ):
                total = round(sum(item.credits for item in group), 3)
                vl = total if is_vl_charge(entry.leave_type) else 0.0
                sl = total if is_sl_charge(entry.leave_type) else 0.0
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
