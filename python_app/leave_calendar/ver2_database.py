from __future__ import annotations

import hashlib
import json
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

    def import_sheet(self, category: str, path: str, sheet: str, rows: list) -> tuple[int, list[str]]:
        if category not in ("VL", "SL", "FL"):
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
        if any(columns[k] is None for k in ("name", "start", "end", "type")):
            return 0, [f"{Path(path).name}: required name, start, end and type columns not found"]
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
                leave_type = str(value("type") or "").strip().upper()
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
            return [dict(row) for row in connection.execute(
                "SELECT * FROM imported_leave ORDER BY name_key, start_date DESC, end_date DESC")]
