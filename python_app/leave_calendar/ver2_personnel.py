from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .ver2_database import normalized_name


class Ver2PersonnelPage(QWidget):
    """Display imported VER2 leave records against exact, unambiguous BIS names."""

    def __init__(self) -> None:
        super().__init__()
        self._records: dict[str, list[dict]] = {}
        self._people = []
        layout = QVBoxLayout(self)
        note = QLabel("VER2 imported leave history · Exact, unique BIS names are linked; other names need review. Status is not assumed approved.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search personnel name or employee ID")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.people = QTreeWidget()
        self.people.setHeaderLabels(["Name", "Employee ID", "Link", "Records"])
        self.people.setRootIsDecorated(False)
        self.people.itemSelectionChanged.connect(self._show_selected)
        split.addWidget(self.people)
        right = QWidget()
        details = QVBoxLayout(right)
        self.selected = QLabel("Select a name to view imported leave history.")
        self.selected.setWordWrap(True)
        details.addWidget(self.selected)
        self.history = QTreeWidget()
        self.history.setHeaderLabels(["Type", "Start", "End", "Status", "Source file", "Sheet", "Row"])
        self.history.setRootIsDecorated(False)
        self.history.setAlternatingRowColors(True)
        details.addWidget(self.history)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, 1)

    def set_data(self, people: list, records: list[dict]) -> None:
        self._people = people
        self._records = {}
        for record in records:
            self._records.setdefault(record["name_key"], []).append(record)
        bis = {}
        for person in people:
            bis.setdefault(normalized_name(person.name), []).append(person)
        self.people.clear()
        for person in sorted(people, key=lambda p: (p.name.casefold(), p.employee_number)):
            key = normalized_name(person.name)
            unique = len(bis[key]) == 1
            matched = self._records.get(key, []) if unique else []
            item = QTreeWidgetItem([person.name, person.employee_number,
                                    "Matched" if unique and matched else ("Ambiguous" if not unique else "No records"),
                                    str(len(matched))])
            item.setData(0, Qt.ItemDataRole.UserRole, key if unique else "")
            self.people.addTopLevelItem(item)
        for key, entries in sorted(self._records.items()):
            if len(bis.get(key, [])) == 1:
                continue
            reason = "Ambiguous — review" if key in bis else "Unmatched — review"
            item = QTreeWidgetItem([entries[0]["name"], "—", reason, str(len(entries))])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            self.people.addTopLevelItem(item)
        self.history.clear()
        self.selected.setText("Select a name to view imported leave history.")
        self._filter()

    def _filter(self, _text: str = "") -> None:
        query = self.search.text().strip().casefold()
        for i in range(self.people.topLevelItemCount()):
            row = self.people.topLevelItem(i)
            row.setHidden(query not in (row.text(0) + " " + row.text(1)).casefold())

    def _show_selected(self) -> None:
        row = self.people.currentItem()
        self.history.clear()
        if row is None:
            return
        key = str(row.data(0, Qt.ItemDataRole.UserRole) or "")
        records = self._records.get(key, []) if key else []
        self.selected.setText(f"{row.text(0)} · {row.text(1)} · {len(records)} imported records")
        for record in records:
            QTreeWidgetItem(self.history, [record["leave_type"], record["start_date"], record["end_date"],
                record["status"] or "Not provided", Path(record["source_path"]).name,
                record["source_sheet"], str(record["source_row"])])
