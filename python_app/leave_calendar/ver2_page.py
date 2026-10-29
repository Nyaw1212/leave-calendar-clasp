from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .settings import app_data_dir


SOURCE_NAMES = ("BAL BROUGHT FORWARD", "VL", "SL", "FL")


def read_workbook(path: str) -> dict[str, list[list[object]]]:
    """Read workbook values without changing the source file."""
    suffix = Path(path).suffix.casefold()
    if suffix == ".xls":
        import xlrd

        workbook = xlrd.open_workbook(path)
        result = {}
        for sheet in workbook.sheets():
            rows = []
            for row_index in range(sheet.nrows):
                row = []
                for cell in sheet.row(row_index):
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        row.append(xlrd.xldate_as_datetime(cell.value, workbook.datemode))
                    elif cell.ctype == xlrd.XL_CELL_ERROR:
                        row.append(xlrd.error_text_from_code.get(cell.value, "#ERROR"))
                    else:
                        row.append(cell.value)
                rows.append(row)
            result[sheet.name] = rows
        return result
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            return {sheet.title: [list(row) for row in sheet.iter_rows(values_only=True)]
                    for sheet in workbook.worksheets}
        finally:
            workbook.close()
    raise ValueError("Choose an .xls or .xlsx workbook.")


def display_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d") if value.time().isoformat() == "00:00:00" else str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


class Ver2SourceTab(QWidget):
    source_changed = Signal()

    def __init__(self, title: str) -> None:
        super().__init__()
        self.entries: list[dict] = []
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        button = QPushButton(f"Add {title} Excel file(s)")
        button.clicked.connect(self.choose_files)
        controls.addWidget(button)
        controls.addWidget(QLabel("File:"))
        self.file_selector = QComboBox()
        self.file_selector.setMinimumWidth(200)
        self.file_selector.currentIndexChanged.connect(self._file_changed)
        controls.addWidget(self.file_selector, 1)
        controls.addWidget(QLabel("Sheet:"))
        self.sheet_selector = QComboBox()
        self.sheet_selector.currentTextChanged.connect(self._sheet_changed)
        controls.addWidget(self.sheet_selector)
        refresh = QPushButton("Reload selected")
        refresh.clicked.connect(self.reload)
        controls.addWidget(refresh)
        remove = QPushButton("Remove selected")
        remove.setToolTip("Remove the file from this list; the original file is not deleted.")
        remove.clicked.connect(self.remove_selected)
        controls.addWidget(remove)
        layout.addLayout(controls)
        self.status = QLabel("Add Excel files to preview them together.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("QTableWidget { font-size: 14pt; } QHeaderView::section { font-size: 14pt; padding: 5px; }")
        layout.addWidget(self.table, 1)

    @staticmethod
    def _path_key(path: str) -> str:
        return str(Path(path).expanduser().resolve()).casefold()

    def choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add Excel files", "", "Excel files (*.xls *.xlsx)")
        if not paths:
            return
        messages = []
        existing = {self._path_key(entry["path"]) for entry in self.entries}
        for path in paths:
            key = self._path_key(path)
            if key in existing:
                messages.append(f"{Path(path).name}: already in the list.")
                continue
            try:
                sheets = read_workbook(path)
                if not sheets:
                    raise ValueError("The workbook has no sheets.")
            except Exception as error:
                messages.append(f"{Path(path).name}: {error}")
                continue
            self.entries.append({"path": path, "sheet": next(iter(sheets)), "sheets": sheets, "error": ""})
            existing.add(key)
        self._refresh_controls(len(self.entries) - 1)
        self._render_combined()
        self.source_changed.emit()
        if messages:
            QMessageBox.information(self, "Excel files", "\n".join(messages))

    def restore_entries(self, entries: list[dict]) -> None:
        self.entries = []
        seen = set()
        for source in entries:
            if not isinstance(source, dict) or not source.get("path"):
                continue
            path = str(source["path"])
            key = self._path_key(path)
            if key in seen:
                continue
            seen.add(key)
            selected = str(source.get("sheet", ""))
            try:
                sheets = read_workbook(path)
                if not sheets:
                    raise ValueError("The workbook has no sheets.")
                if selected and selected not in sheets:
                    raise ValueError(f"Saved sheet '{selected}' was not found.")
                selected = selected or next(iter(sheets))
                error = ""
            except Exception as exc:
                sheets = {}
                error = str(exc)
            self.entries.append({"path": path, "sheet": selected, "sheets": sheets, "error": error})
        self._refresh_controls(0)
        self._render_combined()

    def _refresh_controls(self, selected: int) -> None:
        self.file_selector.blockSignals(True)
        self.file_selector.clear()
        for entry in self.entries:
            label = Path(entry["path"]).name + (" ⚠" if entry["error"] else "")
            self.file_selector.addItem(label, entry["path"])
        if self.entries:
            self.file_selector.setCurrentIndex(max(0, min(selected, len(self.entries) - 1)))
        self.file_selector.blockSignals(False)
        self._file_changed(self.file_selector.currentIndex())

    def _file_changed(self, index: int) -> None:
        self.sheet_selector.blockSignals(True)
        self.sheet_selector.clear()
        if 0 <= index < len(self.entries):
            entry = self.entries[index]
            self.sheet_selector.addItems(list(entry["sheets"]))
            if entry["sheet"] in entry["sheets"]:
                self.sheet_selector.setCurrentText(entry["sheet"])
            self.file_selector.setToolTip(entry["path"])
        self.sheet_selector.blockSignals(False)

    def _sheet_changed(self, name: str) -> None:
        index = self.file_selector.currentIndex()
        if 0 <= index < len(self.entries) and name:
            self.entries[index]["sheet"] = name
            self._render_combined()
            self.source_changed.emit()

    def reload(self) -> None:
        index = self.file_selector.currentIndex()
        if not 0 <= index < len(self.entries):
            return
        entry = self.entries[index]
        try:
            sheets = read_workbook(entry["path"])
            if not sheets:
                raise ValueError("The workbook has no sheets.")
            if entry["sheet"] and entry["sheet"] not in sheets:
                raise ValueError(f"Saved sheet '{entry['sheet']}' was not found.")
        except Exception as error:
            QMessageBox.warning(self, "Excel file", f"Could not reload {Path(entry['path']).name}: {error}")
            return
        entry["sheets"] = sheets
        entry["sheet"] = entry["sheet"] or next(iter(sheets))
        entry["error"] = ""
        self._refresh_controls(index)
        self._render_combined()
        self.source_changed.emit()

    def remove_selected(self) -> None:
        index = self.file_selector.currentIndex()
        if 0 <= index < len(self.entries):
            self.entries.pop(index)
            self._refresh_controls(index)
            self._render_combined()
            self.source_changed.emit()

    def saved_entries(self) -> list[dict]:
        return [{"path": entry["path"], "sheet": entry["sheet"]} for entry in self.entries]

    def _render_combined(self) -> None:
        headers: list[str] = []
        header_keys: list[tuple[str, int]] = []
        combined: list[tuple[str, int, dict[tuple[str, int], str]]] = []
        errors = []
        for entry in self.entries:
            if entry["error"]:
                errors.append(f"{Path(entry['path']).name}: {entry['error']}")
                continue
            rows = entry["sheets"].get(entry["sheet"], [])
            header_index = next((i for i, row in enumerate(rows) if any(display_value(v).strip() for v in row)), None)
            if header_index is None:
                continue
            width = max((len(row) for row in rows), default=0)
            source_headers = rows[header_index]
            counts: dict[str, int] = {}
            keys: list[tuple[str, int]] = []
            for column in range(width):
                label = display_value(source_headers[column]).strip() if column < len(source_headers) else ""
                label = label or f"Column {column + 1}"
                normalized = " ".join(label.casefold().split())
                occurrence = counts.get(normalized, 0) + 1
                counts[normalized] = occurrence
                key = (normalized, occurrence)
                keys.append(key)
                if key not in header_keys:
                    header_keys.append(key)
                    headers.append(label if occurrence == 1 else f"{label} ({occurrence})")
            for row_index, row in enumerate(rows[header_index + 1:], start=header_index + 2):
                if not any(display_value(value).strip() for value in row):
                    continue
                cells = {keys[i]: display_value(value) for i, value in enumerate(row) if i < len(keys)}
                combined.append((Path(entry["path"]).name, row_index, cells))
        self.table.setUpdatesEnabled(False)
        try:
            self.table.clear()
            self.table.setColumnCount(len(headers) + 2)
            self.table.setHorizontalHeaderLabels(["Source file", "Source row"] + headers)
            self.table.setRowCount(len(combined))
            for row_number, (filename, source_row, cells) in enumerate(combined):
                self.table.setItem(row_number, 0, QTableWidgetItem(filename))
                self.table.setItem(row_number, 1, QTableWidgetItem(str(source_row)))
                for column, key in enumerate(header_keys, start=2):
                    text = cells.get(key, "")
                    if text:
                        self.table.setItem(row_number, column, QTableWidgetItem(text))
        finally:
            self.table.setUpdatesEnabled(True)
        status = f"Combined preview: {len(combined)} rows from {len(self.entries)} file(s). Source files are unchanged."
        if errors:
            status += " Could not load: " + "; ".join(errors)
        self.status.setText(status)


class Ver2Page(QWidget):
    back_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel("VER2 · Excel Leave Data")
        title.setStyleSheet("font-size: 22pt; font-weight: 800;")
        heading.addWidget(title)
        heading.addStretch(1)
        back = QPushButton("← VER1")
        back.clicked.connect(self.back_requested.emit)
        heading.addWidget(back)
        layout.addLayout(heading)
        note = QLabel("Add monthly workbooks to each source. This preview does not import records or calculate balances yet.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QTabWidget()
        self.sources = {}
        for name in SOURCE_NAMES:
            tab = Ver2SourceTab(name)
            tab.source_changed.connect(self.save_sources)
            self.sources[name] = tab
            self.tabs.addTab(tab, name)
        layout.addWidget(self.tabs, 1)
        self._sources_restored = False

    def restore_sources_once(self) -> None:
        if not self._sources_restored:
            self._sources_restored = True
            self._restore_sources()

    def _restore_sources(self) -> None:
        config = app_data_dir() / "ver2_sources.json"
        try:
            data = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            return
        for name, tab in self.sources.items():
            source = data.get(name, [])
            # Support the original single-file settings without losing them.
            if isinstance(source, dict):
                source = [source] if source.get("path") else []
            if isinstance(source, list):
                tab.restore_entries(source)

    def save_sources(self) -> None:
        config = app_data_dir() / "ver2_sources.json"
        data = {name: tab.saved_entries()
                for name, tab in self.sources.items() if tab.entries}
        try:
            config.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, "VER2 sources", f"Could not save source selection: {error}")
