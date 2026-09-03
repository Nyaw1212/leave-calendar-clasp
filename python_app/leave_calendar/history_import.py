from __future__ import annotations

import csv
import io
from datetime import datetime

from .models import LeaveRecord
from .rules import normalize_leave_type


IMPORT_FIELDS = ("NAME", "TYPE", "START", "END", "VL", "SL", "LWOP", "STATUS")


class HistoryImportError(ValueError):
    pass


def parse_history_text(text: str, default_name: str = "") -> list[LeaveRecord]:
    source = str(text or "").strip()
    if not source:
        raise HistoryImportError("Paste at least one leave-history row.")
    delimiter = "\t" if "\t" in source else ","
    rows = [
        [cell.strip() for cell in row]
        for row in csv.reader(io.StringIO(source), delimiter=delimiter)
        if any(cell.strip() for cell in row)
    ]
    if not rows:
        raise HistoryImportError("Paste at least one leave-history row.")

    header = [_header_name(value) for value in rows[0]]
    has_header = "TYPE" in header and "START" in header and "END" in header
    if has_header:
        indexes = {name: index for index, name in enumerate(header) if name}
        data_rows = rows[1:]
    else:
        expected = IMPORT_FIELDS if len(rows[0]) >= 8 else IMPORT_FIELDS[1:]
        indexes = {name: index for index, name in enumerate(expected)}
        data_rows = rows

    missing = [name for name in ("TYPE", "START", "END") if name not in indexes]
    if missing:
        raise HistoryImportError("Missing required column(s): " + ", ".join(missing))

    records: list[LeaveRecord] = []
    for row_number, row in enumerate(data_rows, start=2 if has_header else 1):
        try:
            name = _cell(row, indexes.get("NAME")) or default_name.strip()
            if not name:
                raise HistoryImportError("NAME is blank and no employee is selected.")
            leave_type = normalize_leave_type(_cell(row, indexes["TYPE"]))
            if not leave_type:
                raise HistoryImportError("TYPE is blank.")
            start = _parse_date(_cell(row, indexes["START"]))
            end = _parse_date(_cell(row, indexes["END"]))
            if end < start:
                raise HistoryImportError("END is before START.")
            records.append(
                LeaveRecord(
                    leave_type=leave_type,
                    start=start,
                    end=end,
                    vl=_parse_credit(_cell(row, indexes.get("VL"))),
                    sl=_parse_credit(_cell(row, indexes.get("SL"))),
                    lwop=_parse_credit(_cell(row, indexes.get("LWOP"))),
                    status=_cell(row, indexes.get("STATUS")) or "A",
                    record_id="",
                    employee_id="",
                    name=" ".join(name.split()),
                    remarks="Imported from pasted history",
                )
            )
        except (HistoryImportError, ValueError) as error:
            raise HistoryImportError(f"Row {row_number}: {error}") from error
    if not records:
        raise HistoryImportError("The pasted text contains a header but no data rows.")
    return records


def _header_name(value: str) -> str:
    normalized = " ".join(value.strip().upper().replace("_", " ").split())
    return "TYPE" if normalized == "LEAVE TYPE" else normalized


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _parse_date(value: str):
    for pattern in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise HistoryImportError(f'Invalid date "{value}"; use M/D/YYYY.')


def _parse_credit(value: str) -> float:
    if not value:
        return 0.0
    number = float(value.replace(",", ""))
    if number < 0:
        raise HistoryImportError("Credits cannot be negative.")
    return round(number, 3)
