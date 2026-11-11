from __future__ import annotations

from pathlib import Path
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .ver2_database import normalized_name
from .ver2_balances import BALANCE_DATE, project_balance, suggested_balance_candidates, resolve_balance_matches
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
        link_button.setToolTip("Link a balance to a BIS employee or explicitly confirm an unmatched imported name.")
        link_button.clicked.connect(self._link_balance)
        balance_controls.addWidget(link_button)
        unlink_button = QPushButton('Remove Name Link')
        unlink_button.setToolTip('Remove a manual link for an imported leave name without a BIS ID.')
        unlink_button.clicked.connect(self._remove_name_link)
        balance_controls.addWidget(unlink_button)
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
        matches_by_key = resolve_balance_matches(self._balance_rows, self._people, links)
        for row in self._balance_rows:
            match = matches_by_key.get(row['key'])
            if match and match[0].employee_number == employee_id:
                return row, match[1]
        if assigned:
            return None, "Linked balance source or employee is unavailable or ambiguous; review the link."
        candidates = suggested_balance_candidates(name, self._balance_rows)
        if candidates:
            return None, "Name needs review · click Link Balance."
        return None, "No matching brought-forward balance."

    def _link_balance(self) -> None:
        item = self.people.currentItem()
        if item is None or not item.data(0, Qt.ItemDataRole.UserRole):
            QMessageBox.information(self, "Link Balance", "Select a unique BIS employee or an unmatched imported leave name first.")
            return
        source_only = item.text(1) == '—'
        if source_only and not item.text(2).startswith('Unmatched'):
            QMessageBox.warning(self, 'Link Balance', 'This name is ambiguous. Resolve the duplicate employee records before linking.')
            return
        if self._balance_links is None or not self._balance_rows:
            QMessageBox.information(self, "Link Balance", "Load a brought-forward workbook first.")
            return
        options = suggested_balance_candidates(item.text(0), self._balance_rows)
        existing_keys = {entry['key'] for entry in options}
        options += [entry for entry in self._balance_rows
                    if entry['key'] not in existing_keys and entry.get('proposed_name')
                    and normalized_name(entry['proposed_name']) == normalized_name(item.text(0))]
        options = options or self._balance_rows
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
        if source_only:
            existing = resolve_balance_matches(self._balance_rows, self._people, self._balance_links.all())
            if selected['key'] in existing:
                QMessageBox.warning(self, 'Link Balance', 'This balance already matches a BIS employee. Review that match before linking it to an imported name.')
                return
            question = (f"Manually link imported leave name {item.text(0)} to balance {selected['name']}?\n\n"
                        "This name has no BIS employee ID. Confirm that both records are the same person. "
                        "The link will be marked for review.")
            if QMessageBox.question(self, 'Confirm manual name link', question) != QMessageBox.StandardButton.Yes:
                return
            try:
                self._balance_links.assign_source(item.text(0), selected['key'])
            except Exception as error:
                QMessageBox.warning(self, 'Link Balance', str(error))
                return
            self._show_selected()
            return
        if QMessageBox.question(self, "Confirm balance link",
            f'Link {item.text(0)} ({item.text(1)}) to the balance for {selected["name"]}?') != QMessageBox.StandardButton.Yes:
            return
        try:
            self._balance_links.assign(item.text(1), selected["key"])
        except Exception as error:
            QMessageBox.warning(self, "Link Balance", str(error))
            return
        self._show_selected()

    def _remove_name_link(self):
        item = self.people.currentItem()
        if item is None or item.text(1) != '—' or self._balance_links is None or not item.data(0, Qt.ItemDataRole.UserRole):
            QMessageBox.information(self, 'Remove Name Link', 'Select an imported leave name without a BIS ID first.')
            return
        if normalized_name(item.text(0)) not in self._balance_links.source_links():
            QMessageBox.information(self, 'Remove Name Link', 'This imported name does not have a manual balance link.')
            return
        if QMessageBox.question(self, 'Remove Name Link', f"Remove the manual balance link for {item.text(0)}?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self._balance_links.remove_source(item.text(0))
        except Exception as error:
            QMessageBox.warning(self, 'Remove Name Link', str(error))
            return
        self._show_selected()

    def _show_balance(self, row: QTreeWidgetItem, records: list[dict]) -> None:
        key = str(row.data(0, Qt.ItemDataRole.UserRole) or '')
        if not key:
            self.balance_summary.setText("Balance unavailable: select a unique employee or imported name.")
            return
        if row.text(1) == '—':
            if not row.text(2).startswith('Unmatched') or self._balance_links is None:
                self.balance_summary.setText('Balance unavailable: this imported name is ambiguous or no balance file is loaded.')
                return
            source_key = self._balance_links.source_links().get(key)
            existing = resolve_balance_matches(self._balance_rows, self._people, self._balance_links.all())
            balance = next((entry for entry in self._balance_rows if entry['key'] == source_key), None)
            if source_key in existing:
                self.balance_summary.setText('Manual name link needs review: this balance now matches a BIS employee.')
                return
            match = 'Manually linked imported name · no BIS ID · review'
        else:
            balance, match = self._resolve_balance(row.text(1), row.text(0))
        if balance is None:
            self.balance_summary.setText('No manual link yet · click Link Balance.' if row.text(1) == '—' else match)
            return
        today = date.today()
        if today < BALANCE_DATE:
            self.balance_summary.setText("Balance calculation is unavailable before 08/31/2026.")
            return
        result = project_balance(balance, records, self._regular_holidays, HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR, today)
        def fmt(value):
            return f"{value:.3f}" if value is not None else "—"
        text = (f'{match} · {balance["name"]} ({Path(balance["path"]).name}, row {balance["row"]}) · Opening 08/31/2026: VL {fmt(balance["vl"])} | SL {fmt(balance["sl"])}'
                f'\nThrough {today:%m/%d/%Y}: earned VL {fmt(result["earned_vl"])} | SL {fmt(result["earned_sl"])}'
                f' · leave deducted VL {fmt(result["used_vl"])} | SL {fmt(result["used_sl"])}'
                f' · Remaining VL {fmt(result["vl"])} | SL {fmt(result["sl"])}')
        if match.startswith("Possible name match"):
            text += f'\nNAME AUDIT: credits {balance["name"]} | personnel {row.text(0)}. Provisional until confirmed.'
        if result["review"]:
            text += "\nUnavailable until conflicting leave types or missing holiday data are reviewed."
        if balance["vl"] is None or balance["sl"] is None:
            text += "\nA missing or invalid opening balance is not treated as zero."
        if not records:
            text += "\nNo matched leave records. Check unmatched names before relying on this balance."
        text += "\nEarns 1.250 VL and SL for each completed month after August 2026; imported leave only."
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
            hits = [] if record['leave_type'].strip().upper() == 'SPL' else audit_excluded_dates(start, end, self._regular_holidays)
            same_month = start.year == end.year and start.month == end.month
            codes = [f"{kind}{day.day}" if same_month else f"{kind}{day:%m/%d}" for day, kind in hits]
            details = [f"{kind} {day:%m/%d/%Y}" for day, kind in hits]
            if record.get('excluded_dates'):
                codes.append("MANUALLY EXCLUDED")
                details.append("Excluded from calculations by review: " + ", ".join(record['excluded_dates']))
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
                ) + ". VL/SL overlaps may be assigned automatically in Leave Balance; check Troubleshoot for the decision.")
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



