from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .ver2_balances import BALANCE_DATE, project_balance
from .ver2_database import normalized_name
from .philippine_holidays import HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR


def overview_rows(balances, people, records, links, holidays, as_of):
    """Show all imported balances; calculate only for unambiguous linked staff."""
    people_by_name = defaultdict(list)
    people_by_id = defaultdict(list)
    source_names = Counter(row['name_key'] for row in balances)
    for person in people:
        people_by_name[normalized_name(person.name)].append(person)
        people_by_id[person.employee_number].append(person)
    owner_by_source = {source: owner for owner, source in links.items()}
    result = []
    for source in balances:
        owner = owner_by_source.get(source['key'])
        person = None
        status = 'Needs linking'
        if owner:
            candidates = people_by_id.get(owner, [])
            if len(candidates) == 1 and len(people_by_name[normalized_name(candidates[0].name)]) == 1:
                person, status = candidates[0], 'Manually linked'
            else:
                status = 'Linked employee unavailable or ambiguous'
        else:
            candidates = people_by_name.get(source['name_key'], [])
            if (len(candidates) == 1 and source_names[source['name_key']] == 1
                    and len(people_by_id[candidates[0].employee_number]) == 1
                    and candidates[0].employee_number not in links):
                person, status = candidates[0], 'Exact name match'
        estimate = None
        if person:
            history = records.get(normalized_name(person.name), [])
            if as_of < BALANCE_DATE:
                status += ' · Calculation date before opening'
            else:
                estimate = project_balance(source, history, holidays, HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR, as_of)
                if estimate['review']:
                    status += ' · Review conflicts or holidays'
                if not history:
                    status += ' · No matched leave; review'
                if source['vl'] is None or source['sl'] is None:
                    status += ' · Missing opening credit'
        result.append((source, person, status, estimate))
    return result


class Ver2BalanceOverview(QWidget):
    def __init__(self, personnel, open_personnel):
        super().__init__()
        self.personnel = personnel
        self.open_personnel = open_personnel
        self._dirty = True
        layout = QVBoxLayout(self)
        note = QLabel('Check Leave Balances · Opening values are from 08/31/2026. Remaining values deduct imported leave through today; earned credits are not included. Unmatched names need review.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel('Open this page to load uploaded balances.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search spreadsheet name, employee name or ID')
        self.search.textChanged.connect(self._filter)
        controls.addWidget(self.search, 1)
        view = QPushButton('View employee / Link balance')
        view.clicked.connect(self._open_selected)
        controls.addWidget(view)
        refresh = QPushButton('Refresh')
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        layout.addLayout(controls)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(['Spreadsheet name', 'Employee ID', 'Employee name', 'Opening VL', 'Opening SL', 'VL deducted', 'SL deducted', 'Remaining VL', 'Remaining SL', 'Status', 'Source'])
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(9, 280)
        self.table.itemDoubleClicked.connect(lambda *_: self._open_selected())
        layout.addWidget(self.table, 1)

    def refresh_if_needed(self):
        if self._dirty:
            self.refresh()

    def refresh(self):
        self._dirty = False
        p = self.personnel
        links = p._balance_links.all() if p._balance_links is not None else {}
        rows = overview_rows(p._balance_rows, p._people, p._records, links, p._regular_holidays, date.today())
        self.table.setUpdatesEnabled(False)
        self.table.clear()
        def fmt(value):
            return f'{value:.3f}' if value is not None else '—'
        for source, person, status, estimate in rows:
            values = [source['name'], person.employee_number if person else '—', person.name if person else '—',
                      fmt(source['vl']), fmt(source['sl']),
                      fmt(estimate['used_vl']) if estimate else '—', fmt(estimate['used_sl']) if estimate else '—',
                      fmt(estimate['vl']) if estimate else '—', fmt(estimate['sl']) if estimate else '—', status,
                      f"{Path(source['path']).name} · {source['sheet']} · row {source['row']}"]
            item = QTreeWidgetItem(values)
            item.setData(0, Qt.ItemDataRole.UserRole, person.employee_number if person else '')
            self.table.addTopLevelItem(item)
        self.table.setUpdatesEnabled(True)
        self.status.setText(f'{len(rows)} brought-forward rows loaded. Select a matched employee to view leave history; use Personnel Files → Link Balance for names needing review.' if rows else 'No brought-forward rows loaded. Open BAL BROUGHT FORWARD and add your credits workbook.')
        self._filter()

    def _filter(self, *_):
        query = self.search.text().strip().casefold()
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            item.setHidden(query not in ' '.join(item.text(i) for i in range(3)).casefold())

    def _open_selected(self):
        item = self.table.currentItem()
        if not item:
            QMessageBox.information(self, 'Check Leave Balances', 'Select a balance row first.')
            return
        employee_id = item.data(0, Qt.ItemDataRole.UserRole)
        self.open_personnel(employee_id, item.text(0))
