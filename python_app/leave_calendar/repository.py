from __future__ import annotations

import threading
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from .leave_types import LeaveTypeOption, default_leave_type_options, parse_leave_type_rows
from .models import (
    DraftEntry,
    Employee,
    EmployeeProfile,
    Holiday,
    LeaveDay,
    LeaveRecord,
    SaveResult,
)
from .philippine_holidays import (
    REGULAR_HOLIDAY,
    SPECIAL_NON_WORKING_HOLIDAY,
    SPECIAL_WORKING_HOLIDAY,
    timeanddate_calendar_url,
)
from .rules import (
    compute_csc_accrual,
    compute_opening_credit,
    credit_for_day,
    group_consecutive_dates,
    is_sl_charge,
    is_vl_charge,
    prorated_usage,
)
from .settings import AppSettings


RECORDS_SHEET = "Leave Records"
EMPLOYEES_SHEET = "Employees"
HOLIDAYS_SHEET = "Holidays"
LEAVE_TYPES_SHEET = "LEAVE_TYPE"

RECORD_HEADERS = (
    "TYPE",
    "START",
    "END",
    "STATUS",
    "VL",
    "SL",
    "LWOP",
    "Record ID",
    "Employee ID",
    "Name",
    "Remarks",
    "Timestamp",
)
EMPLOYEE_HEADERS = (
    "Employee ID",
    "Name",
    "Date of Assumption",
    "Computed VL Earned",
    "Computed SL Earned",
)
HOLIDAY_HEADERS = (
    "Date",
    "Holiday Name",
    "Holiday Type",
    "Year",
    "Source",
    "Imported At",
)


class RepositoryError(RuntimeError):
    pass


class SheetsRepository:
    """Thin, cached Google Sheets repository used by the desktop UI."""

    def __init__(self, settings: AppSettings, cache_seconds: float = 45.0) -> None:
        self.settings = settings
        self.cache_seconds = cache_seconds
        self._client: Any = None
        self._spreadsheet: Any = None
        self._worksheets: dict[str, Any] = {}
        self._cache: dict[str, tuple[float, list[list[str]]]] = {}
        self._lock = threading.RLock()

    @property
    def spreadsheet_title(self) -> str:
        return str(getattr(self._spreadsheet, "title", ""))

    def connect(self) -> None:
        self.settings.validate()
        try:
            import gspread
        except ImportError as error:
            raise RepositoryError(
                "Google Sheets support is not installed. Run the setup command in "
                "python_app/README.md, or use the packaged Windows build."
            ) from error

        try:
            self._client = gspread.service_account(filename=self.settings.credentials_path)
            self._spreadsheet = self._client.open_by_key(self.settings.spreadsheet_id)
            self._ensure_layout()
        except Exception as error:  # gspread maps API failures to several exception types.
            raise RepositoryError(_friendly_google_error(error)) from error

    def _ensure_layout(self) -> None:
        self._ensure_worksheet(RECORDS_SHEET, RECORD_HEADERS, rows=1000, cols=12)
        self._ensure_worksheet(EMPLOYEES_SHEET, EMPLOYEE_HEADERS, rows=500, cols=5)

        records_header = tuple(self._worksheet(RECORDS_SHEET).row_values(1))
        if records_header and tuple(records_header[:7]) != RECORD_HEADERS[:7]:
            raise RepositoryError(
                "Leave Records has an unsupported column layout. Run the existing "
                "Apps Script MAGCLIP migration once before using the Python app."
            )
        self._worksheet(RECORDS_SHEET).update(
            range_name="A1:L1",
            values=[list(RECORD_HEADERS)],
            value_input_option="RAW",
        )

        self._apply_formats()
        self.invalidate()

    def _ensure_worksheet(
        self,
        title: str,
        headers: tuple[str, ...],
        *,
        rows: int,
        cols: int,
    ) -> Any:
        try:
            worksheet = self._spreadsheet.worksheet(title)
        except Exception as error:
            if error.__class__.__name__ != "WorksheetNotFound":
                raise
            worksheet = self._spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)

        current = worksheet.row_values(1)
        if not current:
            worksheet.update(
                range_name=f"A1:{_column_letter(len(headers))}1",
                values=[list(headers)],
                value_input_option="RAW",
            )
        elif title != RECORDS_SHEET:
            padded = list(current[: len(headers)]) + [""] * max(0, len(headers) - len(current))
            for index, header in enumerate(headers):
                if not padded[index]:
                    padded[index] = header
            worksheet.update(
                range_name=f"A1:{_column_letter(len(headers))}1",
                values=[padded[: len(headers)]],
                value_input_option="RAW",
            )
        self._worksheets[title] = worksheet
        return worksheet

    def _apply_formats(self) -> None:
        formats = {
            RECORDS_SHEET: {
                "A1:L1": {"textFormat": {"bold": True}},
                "B:C": {"numberFormat": {"type": "DATE", "pattern": "MM/dd/yyyy"}},
                "E:G": {"numberFormat": {"type": "NUMBER", "pattern": "0.000"}},
                "L:L": {
                    "numberFormat": {"type": "DATE_TIME", "pattern": "MM/dd/yyyy HH:mm:ss"}
                },
            },
            EMPLOYEES_SHEET: {
                "A1:E1": {"textFormat": {"bold": True}},
                "C:C": {"numberFormat": {"type": "DATE", "pattern": "MM/dd/yyyy"}},
                "D:E": {"numberFormat": {"type": "NUMBER", "pattern": "0.000"}},
            },
        }
        for title, ranges in formats.items():
            worksheet = self._worksheet(title)
            for range_name, value in ranges.items():
                try:
                    worksheet.format(range_name, value)
                except Exception:
                    # Formatting is helpful, but it must never block data entry.
                    pass

    def _worksheet(self, title: str) -> Any:
        worksheet = self._worksheets.get(title)
        if worksheet is None:
            worksheet = self._spreadsheet.worksheet(title)
            self._worksheets[title] = worksheet
        return worksheet

    def invalidate(self, *titles: str) -> None:
        with self._lock:
            if titles:
                for title in titles:
                    self._cache.pop(title, None)
            else:
                self._cache.clear()

    def _values(self, title: str, force: bool = False) -> list[list[str]]:
        with self._lock:
            now = time.monotonic()
            cached = self._cache.get(title)
            if cached and not force and now - cached[0] < self.cache_seconds:
                return cached[1]
            values = self._worksheet(title).get_all_values()
            self._cache[title] = (now, values)
            return values

    def employees(self, force: bool = False) -> list[Employee]:
        values = self._values(EMPLOYEES_SHEET, force=force)
        result: list[Employee] = []
        for row in values[1:]:
            cells = _pad(row, len(EMPLOYEE_HEADERS))
            employee_id = cells[0].strip()
            name = cells[1].strip()
            if not employee_id and not name:
                continue
            if not employee_id:
                continue
            result.append(
                Employee(
                    employee_id=employee_id,
                    name=name or employee_id,
                    assumption_date=parse_sheet_date(cells[2]),
                    earned_vl=_number(cells[3]),
                    earned_sl=_number(cells[4]),
                )
            )
        return sorted(result, key=lambda item: (item.name.casefold(), item.employee_id))

    def employee_by_id(self, employee_id: str, force: bool = False) -> Employee | None:
        wanted = str(employee_id).strip()
        return next(
            (item for item in self.employees(force=force) if item.employee_id == wanted),
            None,
        )

    def get_or_create_employee(self, name: str) -> tuple[Employee, bool]:
        clean_name = " ".join(str(name or "").split())
        if not clean_name:
            raise RepositoryError("Enter an employee name.")

        with self._lock:
            employees = self.employees(force=True)
            matches = [item for item in employees if item.name.casefold() == clean_name.casefold()]
            if matches:
                return matches[0], False

            employee = Employee(
                employee_id=f"MAN-{uuid.uuid4().hex[:8].upper()}",
                name=clean_name,
            )
            self._worksheet(EMPLOYEES_SHEET).append_row(
                [employee.employee_id, safe_sheet_text(employee.name), "", 0, 0],
                value_input_option="USER_ENTERED",
            )
            self.invalidate(EMPLOYEES_SHEET)
            return employee, True

    def holiday_records(self, force: bool = False) -> tuple[Holiday, ...]:
        values = self._values(HOLIDAYS_SHEET, force=force)
        result: list[Holiday] = []
        for row in values[1:]:
            cells = _pad(row, len(HOLIDAY_HEADERS))
            holiday_date = parse_sheet_date(cells[0])
            name = cells[1].strip()
            holiday_type = cells[2].strip()
            if holiday_date and name and holiday_type:
                result.append(Holiday(holiday_date, name, holiday_type))
        return tuple(sorted(result, key=lambda item: (item.day, item.holiday_type, item.name)))

    def regular_holidays(self, force: bool = False) -> set[date]:
        return {
            holiday.day
            for holiday in self.holiday_records(force=force)
            if holiday.is_regular
        }

    def replace_holidays(self, year: int, holidays: Iterable[Holiday]) -> int:
        """Replace one year's nationwide typed holidays and preserve other rows."""
        rows = sorted(holidays, key=lambda item: (item.day, item.holiday_type, item.name))
        managed_types = {
            REGULAR_HOLIDAY.casefold(),
            SPECIAL_NON_WORKING_HOLIDAY.casefold(),
            SPECIAL_WORKING_HOLIDAY.casefold(),
        }
        if any(item.day.year != year for item in rows):
            raise RepositoryError("A holiday date does not match the selected year.")
        if any(item.holiday_type.casefold() not in managed_types for item in rows):
            raise RepositoryError("An unsupported Philippine holiday type was provided.")
        if not rows:
            raise RepositoryError(f"No reviewed Philippine holidays are available for {year}.")

        with self._lock:
            worksheet = self._worksheet(HOLIDAYS_SHEET)
            values = self._values(HOLIDAYS_SHEET, force=True)
            rows_to_delete: list[int] = []
            existing_rows: list[Holiday] = []
            for row_number, row in enumerate(values[1:], start=2):
                cells = _pad(row, len(HOLIDAY_HEADERS))
                holiday_date = parse_sheet_date(cells[0])
                holiday_type = cells[2].strip()
                if (
                    holiday_date
                    and holiday_date.year == year
                    and holiday_type.casefold() in managed_types
                ):
                    rows_to_delete.append(row_number)
                    existing_rows.append(
                        Holiday(holiday_date, cells[1].strip(), holiday_type)
                    )

            if sorted(existing_rows, key=lambda item: (item.day, item.holiday_type, item.name)) == rows:
                return len(rows)

            requested_set = set(rows)
            existing_set = set(existing_rows)
            if (
                len(existing_set) == len(existing_rows)
                and existing_set.issubset(requested_set)
            ):
                rows_to_append = sorted(
                    requested_set - existing_set,
                    key=lambda item: (item.day, item.holiday_type, item.name),
                )
                if rows_to_append:
                    self._append_holiday_rows(worksheet, year, rows_to_append)
                    self.invalidate(HOLIDAYS_SHEET)
                return len(rows)

            for row_number in reversed(rows_to_delete):
                worksheet.delete_rows(row_number)

            self._append_holiday_rows(worksheet, year, rows)
            self.invalidate(HOLIDAYS_SHEET)
            return len(rows)

    @staticmethod
    def _append_holiday_rows(
        worksheet: Any,
        year: int,
        holidays: Iterable[Holiday],
    ) -> None:
        imported_at = datetime.now().isoformat(sep=" ", timespec="seconds")
        source = timeanddate_calendar_url(year)
        worksheet.append_rows(
            [
                [
                    item.day.isoformat(),
                    safe_sheet_text(item.name),
                    item.holiday_type,
                    year,
                    source,
                    imported_at,
                ]
                for item in holidays
            ],
            value_input_option="RAW",
        )

    def replace_regular_holidays(
        self,
        year: int,
        holidays: Iterable[tuple[date, str]],
    ) -> int:
        """Replace one year's regular holidays while preserving every other row."""
        rows = sorted(holidays, key=lambda item: item[0])
        if any(day.year != year for day, _name in rows):
            raise RepositoryError("A holiday date does not match the selected year.")
        if not rows:
            raise RepositoryError(f"No reviewed regular holidays are available for {year}.")

        with self._lock:
            worksheet = self._worksheet(HOLIDAYS_SHEET)
            values = self._values(HOLIDAYS_SHEET, force=True)
            rows_to_delete: list[int] = []
            existing_rows: list[tuple[date, str]] = []
            for row_number, row in enumerate(values[1:], start=2):
                cells = _pad(row, len(HOLIDAY_HEADERS))
                holiday_date = parse_sheet_date(cells[0])
                if (
                    holiday_date
                    and holiday_date.year == year
                    and "regular" in cells[2].strip().casefold()
                ):
                    rows_to_delete.append(row_number)
                    existing_rows.append((holiday_date, cells[1].strip()))

            # A second click for an already imported year must not issue a dozen
            # delete requests and another append request. Besides being wasteful,
            # that old path could hit Google Sheets API throttling and leave the UI
            # appearing to load forever.
            requested_rows = [(day, name.strip()) for day, name in rows]
            if sorted(existing_rows) == sorted(requested_rows):
                return len(rows)

            for row_number in reversed(rows_to_delete):
                worksheet.delete_rows(row_number)

            imported_at = datetime.now().isoformat(sep=" ", timespec="seconds")
            source = timeanddate_calendar_url(year)
            worksheet.append_rows(
                [
                    [
                        day.isoformat(),
                        safe_sheet_text(name),
                        "Regular Holiday",
                        year,
                        source,
                        imported_at,
                    ]
                    for day, name in rows
                ],
                # Keep ISO dates as literal values. USER_ENTERED can convert dates
                # through the spreadsheet timezone and shift them back one day.
                value_input_option="RAW",
            )
            self.invalidate(HOLIDAYS_SHEET)
            return len(rows)

    def leave_types(self, force: bool = False) -> list[LeaveTypeOption]:
        """Read leave choices and keyboard shortcuts from the existing LEAVE_TYPE tab."""
        try:
            values = self._values(LEAVE_TYPES_SHEET, force=force)
        except Exception as error:
            if error.__class__.__name__ == "WorksheetNotFound":
                return default_leave_type_options()
            raise
        return parse_leave_type_rows(values)

    def leave_records(self, force: bool = False) -> list[LeaveRecord]:
        values = self._values(RECORDS_SHEET, force=force)
        records: list[LeaveRecord] = []
        for row in values[1:]:
            cells = _pad(row, len(RECORD_HEADERS))
            start = parse_sheet_date(cells[1])
            end = parse_sheet_date(cells[2])
            if not start or not end or not cells[8].strip():
                continue
            records.append(
                LeaveRecord(
                    leave_type=cells[0].strip(),
                    start=start,
                    end=end,
                    vl=_number(cells[4]),
                    sl=_number(cells[5]),
                    lwop=_number(cells[6]),
                    record_id=cells[7].strip(),
                    employee_id=cells[8].strip(),
                    name=cells[9].strip(),
                    remarks=cells[10].strip(),
                )
            )
        return records

    def existing_dates(self, employee_id: str, force: bool = False) -> set[date]:
        result: set[date] = set()
        for record in self.leave_records(force=force):
            if record.employee_id != employee_id:
                continue
            cursor = record.start
            while cursor <= record.end:
                result.add(cursor)
                cursor += timedelta(days=1)
        return result

    def employee_profile(
        self,
        employee: Employee,
        as_of_date: date | None = None,
        force: bool = False,
    ) -> EmployeeProfile:
        as_of = as_of_date or date.today()
        if not employee.assumption_date:
            return EmployeeProfile(
                employee_id=employee.employee_id,
                name=employee.name,
                assumption_date=None,
                as_of_date=as_of,
                opening_vl=0,
                opening_sl=0,
                earned_vl=0,
                earned_sl=0,
                used_vl=0,
                used_sl=0,
                balance_vl=0,
                balance_sl=0,
            )

        earned = compute_csc_accrual(employee.assumption_date, as_of)
        opening = compute_opening_credit(employee.assumption_date)
        used_vl = 0.0
        used_sl = 0.0
        for record in self.leave_records(force=force):
            if record.employee_id != employee.employee_id:
                continue
            used_vl += prorated_usage(record.start, record.end, as_of, record.vl)
            used_sl += prorated_usage(record.start, record.end, as_of, record.sl)

        return EmployeeProfile(
            employee_id=employee.employee_id,
            name=employee.name,
            assumption_date=employee.assumption_date,
            as_of_date=as_of,
            opening_vl=round(opening, 3),
            opening_sl=round(opening, 3),
            earned_vl=round(earned, 3),
            earned_sl=round(earned, 3),
            used_vl=round(used_vl, 3),
            used_sl=round(used_sl, 3),
            balance_vl=round(earned - used_vl, 3),
            balance_sl=round(earned - used_sl, 3),
        )

    def save_employee_profile(self, employee_id: str, assumption_date: date) -> Employee:
        with self._lock:
            employees = self.employees(force=True)
            index = next(
                (offset for offset, item in enumerate(employees) if item.employee_id == employee_id),
                None,
            )
            if index is None:
                raise RepositoryError("Employee was not found in the Employees sheet.")

            # The sorted Employee list does not preserve the physical row, so locate it directly.
            values = self._values(EMPLOYEES_SHEET, force=True)
            row_number = next(
                (
                    offset
                    for offset, row in enumerate(values[1:], start=2)
                    if _pad(row, len(EMPLOYEE_HEADERS))[0].strip() == employee_id
                ),
                None,
            )
            if row_number is None:
                raise RepositoryError("Employee was not found in the Employees sheet.")

            earned = compute_csc_accrual(assumption_date, date.today())
            self._worksheet(EMPLOYEES_SHEET).update(
                range_name=f"C{row_number}:E{row_number}",
                values=[[assumption_date.isoformat(), earned, earned]],
                value_input_option="USER_ENTERED",
            )
            self.invalidate(EMPLOYEES_SHEET)
            employee = self.employee_by_id(employee_id, force=True)
            if employee is None:
                raise RepositoryError("Employee profile could not be reloaded after saving.")
            return employee

    def save_draft(self, employee: Employee, entries: list[DraftEntry]) -> SaveResult:
        if not entries:
            raise RepositoryError("Add at least one leave entry to the draft.")

        with self._lock:
            regular_holidays = self.regular_holidays(force=True)
            known_dates = self.existing_dates(employee.employee_id, force=True)
            rows: list[list[Any]] = []
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
                for group in group_consecutive_dates(accepted, date_getter=lambda value: value.day):
                    total = round(sum(item.credits for item in group), 3)
                    vl = total if is_vl_charge(entry.leave_type) else 0
                    sl = total if is_sl_charge(entry.leave_type) else 0
                    rows.append(
                        [
                            entry.leave_type,
                            group[0].day.isoformat(),
                            group[-1].day.isoformat(),
                            "A",
                            vl,
                            sl,
                            0,
                            str(uuid.uuid4()),
                            employee.employee_id,
                            safe_sheet_text(employee.name),
                            safe_sheet_text(entry.remarks),
                            timestamp,
                        ]
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

            if rows:
                self._worksheet(RECORDS_SHEET).append_rows(
                    rows,
                    value_input_option="USER_ENTERED",
                )
                self.invalidate(RECORDS_SHEET)

            return SaveResult(
                rows_written=len(rows),
                dates_added=dates_added,
                existing_dates_written=existing_dates_written,
                zero_credit_dates=zero_credit_dates,
                magclip_rows=tuple(magclip_rows),
            )


def parse_sheet_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and value > 0:
        return date(1899, 12, 30) + timedelta(days=int(value))

    text = str(value or "").strip()
    if not text:
        return None
    date_text = text.split("T", 1)[0].split(" ", 1)[0]
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_text, pattern).date()
        except ValueError:
            continue
    return None


def safe_sheet_text(value: str) -> str:
    text = str(value or "")
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


def _number(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _format_credit(value: float) -> str:
    return f"{float(value):.3f}"


def _pad(row: Iterable[Any], width: int) -> list[str]:
    result = [str(value or "") for value in row]
    return (result + [""] * width)[:width]


def _column_letter(number: int) -> str:
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _friendly_google_error(error: Exception) -> str:
    message = str(error)
    lowered = message.casefold()
    if "permission" in lowered or "403" in lowered:
        return (
            "Google denied access. Share the spreadsheet with the service-account "
            "email shown inside the selected JSON file."
        )
    if "not found" in lowered or "404" in lowered:
        return "Spreadsheet not found. Check the Sheet URL/ID and sharing access."
    if "invalid_grant" in lowered or "credential" in lowered:
        return "The Google credentials file is invalid or has been disabled."
    return f"Could not connect to Google Sheets: {message}"
