from __future__ import annotations

from pathlib import Path
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .ver2_database import normalized_name
from .ver2_balances import BALANCE_DATE, project_balance, suggested_balance_candidates
from .ver2_credit import estimate_leave_charge, audit_excluded_dates, duplicate_leave_overlaps, allocate_unique_estimates
from .philippine_holidays import HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR, local_holidays


class Ver2PersonnelPage(QWidget):
    """Display imported VER2 leave records against exact, unambiguous BIS names."""

    def __init__(self) -> None:
        super().__init__()
        self._records: dict[str, list[dict]] = {}
        self._people = []
        self._balance_rows: list[dict] = []
        self._balance_links = None
        self._overlaps: dict[str, dict] = {}
        self._regular_holidays = frozenset(item.day for item in local_holidays() if item.is_regular)
        layout = QVBoxLayout(self)
        note = QLabel("Opening balances are as of 08/31/2026. Blank imported statuses are treated as approved. VL/SL balances exclude weekends, regular holidays and duplicate same-type dates; conflicting types need review.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search personnel name or employee ID")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.people = QTreeWidget()
        self.people.setHeaderLabels(["Name", "Employee ID", "Link", "Records", "Overlaps"])
        self.people.setRootIsDecorated(False)
        self.people.itemSelectionChanged.connect(self._show_selected)
        split.addWidget(self.people)
        right = QWidget()
        details = QVBoxLayout(right)
        self.selected = QLabel("Select a name to view imported leave history.")
        self.selected.setWordWrap(True)
        details.addWidget(self.selected)
        balance_controls = QHBoxLayout()
        self.balance_summary = QLabel("Select an employee to view brought-forward and remaining balances.")
        self.balance_summary.setWordWrap(True)
        balance_controls.addWidget(self.balance_summary, 1)
        link_button = QPushButton("Link Balance")
        link_button.setToolTip("Review and link a brought-forward balance row to this BIS employee.")
        link_button.clicked.connect(self._link_balance)
        balance_controls.addWidget(link_button)
        details.addLayout(balance_controls)
        self.audit_preview = QLabel("AUDIT · Select a leave row to view excluded dates and overlaps.")
        self.audit_preview.setWordWrap(True)
        self.audit_preview.setStyleSheet("background:#12303b;color:#9ee9f1;border:1px solid #2a7e8e;padding:8px;font-weight:700;")
        details.addWidget(self.audit_preview)
        self.history = QTreeWidget()
        self.history.setHeaderLabels(["Type", "Start", "End", "Calendar days", "Chargeable days", "VL estimate", "SL estimate", "Status", "Audit", "Source file", "Sheet", "Row"])
        self.history.setRootIsDecorated(False)
        self.history.setAlternatingRowColors(True)
        self.history.setColumnWidth(8, 240)
        self.history.itemSelectionChanged.connect(self._show_audit)
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
        self._overlaps = {key: duplicate_leave_overlaps(entries)
                          for key, entries in self._records.items()}
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
                                    str(len(matched)), "Review" if unique and self._overlaps.get(key) else "—"])
            item.setData(0, Qt.ItemDataRole.UserRole, key if unique else "")
            self.people.addTopLevelItem(item)
        for key, entries in sorted(self._records.items()):
            if len(bis.get(key, [])) == 1:
                continue
            reason = "Ambiguous — review" if key in bis else "Unmatched — review"
            item = QTreeWidgetItem([entries[0]["name"], "—", reason, str(len(entries)),
                                    "Review" if self._overlaps.get(key) else "—"])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            self.people.addTopLevelItem(item)
        self.history.clear()
        self.audit_preview.setText("AUDIT · Select a leave row to view excluded dates and overlaps.")
        self.selected.setText("Select a name to view imported leave history.")
        self.balance_summary.setText("Select an employee to view brought-forward and remaining balances.")
        self._filter()

    def set_balance_data(self, rows: list[dict], links: object) -> None:
        self._balance_rows = rows
        self._balance_links = links
        if self.people.currentItem() is not None:
            self._show_selected()

    def _resolve_balance(self, employee_id: str, name: str) -> tuple[dict | None, str]:
        if self._balance_links is None:
            return None, "Load a brought-forward file first."
        links = self._balance_links.all()
        assigned = links.get(employee_id)
        if assigned:
            row = next((entry for entry in self._balance_rows if entry["key"] == assigned), None)
            return (row, "Manually linked") if row else (None, "Linked balance source is unavailable or has changed; review the link.")
        matches = [entry for entry in self._balance_rows if entry["name_key"] == normalized_name(name)]
        used = {key for owner, key in links.items() if owner != employee_id}
        if len(matches) == 1 and matches[0]["key"] not in used:
            return matches[0], "Exact name match"
        candidates = suggested_balance_candidates(name, self._balance_rows)
        if matches or candidates:
            return None, "Name needs review · click Link Balance."
        return None, "No matching brought-forward balance."

    def _link_balance(self) -> None:
        item = self.people.currentItem()
        if item is None or item.text(1) == "—" or not item.data(0, Qt.ItemDataRole.UserRole):
            QMessageBox.information(self, "Link Balance", "Select a unique BIS employee first.")
            return
        if self._balance_links is None or not self._balance_rows:
            QMessageBox.information(self, "Link Balance", "Load a brought-forward workbook first.")
            return
        options = suggested_balance_candidates(item.text(0), self._balance_rows) or self._balance_rows
        options = sorted(options, key=lambda value: (value["name_key"], value["path"], value["row"]))
        labels = [f'{value["name"]} · {Path(value["path"]).name} · {value["sheet"]} row {value["row"]}' for value in options]
        choice, ok = QInputDialog.getItem(self, "Link brought-forward balance",
            f'Select the balance row for {item.text(0)} ({item.text(1)}). Confirm the employee identity:',
            labels, 0, True)
        if not ok:
            return
        if choice not in labels:
            QMessageBox.warning(self, "Link Balance", "Select one of the listed balance rows.")
            return
        selected = options[labels.index(choice)]
        if QMessageBox.question(self, "Confirm balance link",
            f'Link {item.text(0)} ({item.text(1)}) to the balance for {selected["name"]}?') != QMessageBox.StandardButton.Yes:
            return
        try:
            self._balance_links.assign(item.text(1), selected["key"])
        except Exception as error:
            QMessageBox.warning(self, "Link Balance", str(error))
            return
        self._show_selected()

    def _show_balance(self, row: QTreeWidgetItem, records: list[dict]) -> None:
        if row.text(1) == "—" or not row.data(0, Qt.ItemDataRole.UserRole):
            self.balance_summary.setText("Balance unavailable: match this name to a unique BIS employee first.")
            return
        balance, match = self._resolve_balance(row.text(1), row.text(0))
        if balance is None:
            self.balance_summary.setText(match)
            return
        today = date.today()
        if today < BALANCE_DATE:
            self.balance_summary.setText("Balance calculation is unavailable before 08/31/2026.")
            return
        result = project_balance(balance, records, self._regular_holidays, HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR, today)
        def fmt(value):
            return f"{value:.3f}" if value is not None else "—"
        text = (f'{match} · {balance["name"]} ({Path(balance["path"]).name}, row {balance["row"]}) · Opening 08/31/2026: VL {fmt(balance["vl"])} | SL {fmt(balance["sl"])}'
                f'\nThrough {today:%m/%d/%Y}: leave deducted VL {fmt(result["used_vl"])} | SL {fmt(result["used_sl"])}'
                f' · Remaining VL {fmt(result["vl"])} | SL {fmt(result["sl"])}')
        if result["review"]:
            text += "\nUnavailable until conflicting leave types or missing holiday data are reviewed."
        if balance["vl"] is None or balance["sl"] is None:
            text += "\nA missing or invalid opening balance is not treated as zero."
        if not records:
            text += "\nNo matched leave records. Check unmatched names before relying on this balance."
        text += "\nIncludes imported leave only; no additional earned credits are included."
        self.balance_summary.setText(text)

    def _filter(self, _text: str = "") -> None:
        query = self.search.text().strip().casefold()
        for i in range(self.people.topLevelItemCount()):
            row = self.people.topLevelItem(i)
            row.setHidden(query not in (row.text(0) + " " + row.text(1)).casefold())

    def _show_audit(self) -> None:
        item = self.history.currentItem()
        if item is None:
            self.audit_preview.setText("AUDIT · Select a leave row to view excluded dates and overlaps.")
            return
        self.audit_preview.setText("AUDIT · " + str(item.data(8, Qt.ItemDataRole.UserRole) or "No excluded dates or overlaps."))

    def _show_selected(self) -> None:
        row = self.people.currentItem()
        self.history.clear()
        if row is None:
            return
        key = str(row.data(0, Qt.ItemDataRole.UserRole) or "")
        records = self._records.get(key, []) if key else []
        self._show_balance(row, records)
        self.selected.setText(f"{row.text(0)} · {row.text(1)} · {len(records)} imported records")
        overlaps = self._overlaps.get(key, {})
        allocations = allocate_unique_estimates(records, self._regular_holidays, HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR)
        for record in records:
            start, end = date.fromisoformat(record["start_date"]), date.fromisoformat(record["end_date"])
            calendar_days, chargeable, vl, sl = estimate_leave_charge(
                start, end,
                record["leave_type"],
                self._regular_holidays,
                HOLIDAY_MIN_YEAR,
                HOLIDAY_MAX_YEAR,
            )
            allocation = allocations[record["record_key"]]
            if allocation["unavailable"] or allocation["excluded"] or allocation["conflicts"]:
                chargeable, vl, sl = None, None, None
            else:
                chargeable, vl, sl = allocation["chargeable"], allocation["vl"], allocation["sl"]
            hits = audit_excluded_dates(start, end, self._regular_holidays)
            same_month = start.year == end.year and start.month == end.month
            codes = [f"{kind}{day.day}" if same_month else f"{kind}{day:%m/%d}" for day, kind in hits]
            details = [f"{kind} {day:%m/%d/%Y}" for day, kind in hits]
            ranges = overlaps.get(record["record_key"], [])
            if ranges:
                codes.insert(0, "OVERLAP")
                details.insert(0, "Possible overlapping leave dates: " + ", ".join(
                    f"{first:%m/%d/%Y}–{last:%m/%d/%Y}" for first, last in sorted(set(ranges))
                ))
            if allocation["duplicates"]:
                codes.append("COUNTED ELSEWHERE")
                details.append("Already counted on another same-type row: " + ", ".join(
                    day.strftime("%m/%d/%Y") for day in allocation["duplicates"]
                ))
            if allocation["conflicts"]:
                codes.append("TYPE CONFLICT · REVIEW")
                details.append("Different leave types overlap on: " + ", ".join(
                    day.strftime("%m/%d/%Y") for day in allocation["conflicts"]
                ) + ". Review before charging.")
            if allocation["excluded"]:
                codes.append("NOT CHARGED")
                details.append("Cancelled or disapproved entry is not counted.")
            if allocation["unavailable"]:
                codes.append("HOLIDAYS UNKNOWN")
                details.append(f"Regular holidays unavailable outside {HOLIDAY_MIN_YEAR}–{HOLIDAY_MAX_YEAR}, or an overlapping entry has unavailable holiday data.")
            audit_text = " · ".join(codes) or "—"
            item = QTreeWidgetItem(self.history, [
                record["leave_type"], record["start_date"], record["end_date"],
                str(calendar_days), str(chargeable) if chargeable is not None else "—",
                f"{vl:.3f}" if vl is not None else "—",
                f"{sl:.3f}" if sl is not None else "—",
                record["status"] or "A (assumed)", audit_text, Path(record["source_path"]).name,
                record["source_sheet"], str(record["source_row"]),
            ])
            audit_detail = " · ".join(details) or "No excluded dates or overlaps."
            item.setData(8, Qt.ItemDataRole.UserRole, audit_detail)
            item.setToolTip(8, audit_detail)
            status = str(record["status"] or "").strip().upper()
            if status in {"C", "D", "CANCELLED", "CANCELED", "DISAPPROVED"} or record["leave_type"].strip().upper() == "MONE":
                for column in range(self.history.columnCount()):
                    item.setBackground(column, QBrush(QColor("#705b16")))
            elif ranges:
                for column in range(self.history.columnCount()):
                    item.setBackground(column, QBrush(QColor("#8a2828")))
            detail = ("Estimated unique chargeable days, allocated once among same-type rows. "
                      "Not an approved deduction. Different-type overlaps require review.")
            if allocation["unavailable"]:
                detail += f" Holiday data is available only for {HOLIDAY_MIN_YEAR}–{HOLIDAY_MAX_YEAR}."
            for column in (3, 4, 5, 6):
                item.setToolTip(column, detail)
