from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
import sqlite3
from datetime import date, datetime
from pathlib import Path


def normalized_name(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def iso_date(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    value = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Invalid date: {value!r}")


class Ver2Database:
    def __init__(self, path: Path):
        self.path = path
        with sqlite3.connect(self.path) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS imported_leave (
                record_key TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL,
                rank TEXT NOT NULL, station TEXT NOT NULL, office TEXT NOT NULL,
                start_date TEXT NOT NULL, end_date TEXT NOT NULL, leave_type TEXT NOT NULL,
                status TEXT NOT NULL, source_path TEXT NOT NULL, source_sheet TEXT NOT NULL,
                source_row INTEGER NOT NULL, source_values TEXT NOT NULL
            )""")
            connection.execute("CREATE INDEX IF NOT EXISTS ver2_leave_name ON imported_leave(name_key)")
            connection.execute("""CREATE TABLE IF NOT EXISTS ver2_excluded_leave_dates (
                record_key TEXT NOT NULL, leave_date TEXT NOT NULL,
                PRIMARY KEY (record_key, leave_date)
            )""")

    @staticmethod
    def _mone_id(value):
        return re.sub(r"[\s-]+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()

    @staticmethod
    def _mone_amount(value):
        try:
            number = Decimal(str(value).strip())
            if not number.is_finite() or number < 0 or number > 100000 or number * 1000 != (number * 1000).to_integral_value():
                raise ValueError
            return int(number * 1000)
        except (InvalidOperation, ValueError):
            raise ValueError("MONE amounts must be nonnegative numbers with at most three decimal places.")

    def _ensure_mone_tables(self, connection):
        connection.execute("""CREATE TABLE IF NOT EXISTS ver2_mone_totals (
            employee_key TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
            vl_milli INTEGER NOT NULL, sl_milli INTEGER NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY (employee_key, start_date, end_date))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS ver2_mone_audit (
            employee_key TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
            old_vl INTEGER NOT NULL, old_sl INTEGER NOT NULL, new_vl INTEGER NOT NULL,
            new_sl INTEGER NOT NULL, updated_at TEXT NOT NULL)""")
        connection.execute("""CREATE TABLE IF NOT EXISTS ver2_mone_drafts (
            employee_key TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
            vl_text TEXT NOT NULL, sl_text TEXT NOT NULL, expected_vl INTEGER NOT NULL,
            expected_sl INTEGER NOT NULL, PRIMARY KEY (employee_key, start_date, end_date))""")

    def mone_totals(self, as_of=None):
        with sqlite3.connect(self.path) as connection:
            self._ensure_mone_tables(connection)
            query = "SELECT employee_key, start_date, end_date, vl_milli, sl_milli FROM ver2_mone_totals"
            values = ()
            if as_of is not None:
                query += " WHERE start_date <= ?"
                values = (iso_date(as_of),)
            return [tuple(row) for row in connection.execute(query, values)]

    def mone_drafts(self, start, end):
        with sqlite3.connect(self.path) as connection:
            self._ensure_mone_tables(connection)
            return {row[0]: tuple(row[1:]) for row in connection.execute(
                "SELECT employee_key, vl_text, sl_text, expected_vl, expected_sl FROM ver2_mone_drafts WHERE start_date=? AND end_date=?", (iso_date(start), iso_date(end)))}

    def save_mone_draft(self, employee_id, start, end, vl_text, sl_text, expected_vl, expected_sl):
        key = self._mone_id(employee_id)
        with sqlite3.connect(self.path) as connection:
            self._ensure_mone_tables(connection)
            connection.execute("INSERT OR REPLACE INTO ver2_mone_drafts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, iso_date(start), iso_date(end), str(vl_text), str(sl_text), int(expected_vl), int(expected_sl)))

    def save_mone_total(self, employee_id, start, end, vl, sl, expected_vl, expected_sl):
        key, start, end = self._mone_id(employee_id), iso_date(start), iso_date(end)
        if not key or end < start or start <= '2026-08-31':
            raise ValueError("Choose an employee and a valid date range after August 31, 2026.")
        new_vl, new_sl = self._mone_amount(vl), self._mone_amount(sl)
        with sqlite3.connect(self.path) as connection:
            self._ensure_mone_tables(connection)
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute("SELECT vl_milli, sl_milli FROM ver2_mone_totals WHERE employee_key=? AND start_date=? AND end_date=?", (key, start, end)).fetchone() or (0, 0)
            if old != (int(expected_vl), int(expected_sl)):
                raise ValueError("The saved MONE total changed. Refresh and review before saving.")
            stamp = datetime.now().isoformat(timespec="seconds")
            connection.execute("INSERT OR REPLACE INTO ver2_mone_totals VALUES (?, ?, ?, ?, ?, ?)", (key, start, end, new_vl, new_sl, stamp))
            connection.execute("INSERT INTO ver2_mone_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (key, start, end, *old, new_vl, new_sl, stamp))
            connection.execute("DELETE FROM ver2_mone_drafts WHERE employee_key=? AND start_date=? AND end_date=?", (key, start, end))

    def import_sheet(self, category: str, path: str, sheet: str, rows: list) -> tuple[int, list[str]]:
        if category not in ("VL", "SL", "FL", "SPL"):
            return 0, []
        header_index = next((i for i, row in enumerate(rows) if any(str(v or "").strip() for v in row)), None)
        if header_index is None:
            return 0, [f"{Path(path).name}: sheet is empty"]
        headings = {" ".join(str(v or "").strip().casefold().split()): i
                    for i, v in enumerate(rows[header_index]) if str(v or "").strip()}
        aliases = {"name": ("emp_name", "employee name", "name"),
                   "start": ("start_at", "start date", "start"),
                   "end": ("end_at", "end date", "end"),
                   "type": ("type", "leave type"),
                   "rank": ("emp_rank", "rank"), "station": ("oppf", "station"),
                   "office": ("office",), "status": ("status", "form status")}
        columns = {key: next((headings[a] for a in options if a in headings), None)
                   for key, options in aliases.items()}
        if any(columns[k] is None for k in ("name", "start", "end")):
            return 0, [f"{Path(path).name}: required name, start and end columns not found"]
        prepared = []
        errors = []
        for index, row in enumerate(rows[header_index + 1:], start=header_index + 2):
            if not any(str(v or "").strip() for v in row):
                continue
            def value(key: str) -> object:
                pos = columns[key]
                return row[pos] if pos is not None and pos < len(row) else ""
            try:
                name = " ".join(str(value("name") or "").split())
                if not name:
                    raise ValueError("employee name is empty")
                # A workbook without TYPE inherits the explicitly selected source tab.
                # If TYPE is present, validate it rather than hiding missing or conflicting values.
                leave_type = category if columns["type"] is None else str(value("type") or "").strip().upper()
                if leave_type != category:
                    raise ValueError(f"type {leave_type!r} does not match {category}")
                start, end = iso_date(value("start")), iso_date(value("end"))
                if end < start:
                    raise ValueError("end date is before start date")
                original = json.dumps(row, default=str, ensure_ascii=False)
                identity = json.dumps([str(Path(path).resolve()).casefold(), sheet, index, original], ensure_ascii=False)
                key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                prepared.append((key, name, normalized_name(name), str(value("rank") or "").strip(),
                    str(value("station") or "").strip(), str(value("office") or "").strip(),
                    start, end, leave_type, str(value("status") or "").strip(), path, sheet, index, original))
            except ValueError as error:
                errors.append(f"{Path(path).name} row {index}: {error}")
        with sqlite3.connect(self.path) as connection:
            before = connection.total_changes
            connection.executemany("INSERT OR IGNORE INTO imported_leave VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", prepared)
            inserted = connection.total_changes - before
        return inserted, errors

    def records(self) -> list[dict]:
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = [dict(row) for row in connection.execute(
                "SELECT * FROM imported_leave ORDER BY name_key, start_date DESC, end_date DESC")]
            excluded = {}
            for item in connection.execute("SELECT record_key, leave_date FROM ver2_excluded_leave_dates"):
                excluded.setdefault(item["record_key"], []).append(item["leave_date"])
            for row in rows:
                row['excluded_dates'] = excluded.get(row['record_key'], [])
            return rows

    def set_date_inclusions(self, changes: list[tuple[str, str, bool]]) -> None:
        """Save per-record date choices atomically; unchanged dates are untouched."""
        with sqlite3.connect(self.path) as connection:
            for key, date_text, included in changes:
                day = date.fromisoformat(date_text)
                row = connection.execute(
                    "SELECT start_date, end_date FROM imported_leave WHERE record_key = ?", (key,)
                ).fetchone()
                if row is None or not (date.fromisoformat(row[0]) <= day <= date.fromisoformat(row[1])):
                    raise ValueError("A selected leave date is no longer available. Refresh and try again.")
                if included:
                    connection.execute("DELETE FROM ver2_excluded_leave_dates WHERE record_key = ? AND leave_date = ?", (key, day.isoformat()))
                else:
                    connection.execute("INSERT OR IGNORE INTO ver2_excluded_leave_dates VALUES (?, ?)", (key, day.isoformat()))


