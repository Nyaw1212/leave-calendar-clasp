from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .ver2_balances import BALANCE_DATE, project_balance, resolve_balance_matches
from .ver2_database import normalized_name
from .philippine_holidays import HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR


def overview_rows(balances, people, records, links, holidays, as_of):
    """Show all imported balances; calculate only for unambiguous linked staff."""
    matches = resolve_balance_matches(balances, people, links)
    owner_by_source = {source: owner for owner, source in links.items()}
    result = []
    for source in balances:
        person, status = matches.get(source['key'], (None, 'Needs linking'))
        if not person and source.get('has_normal_match_column'):
            status = ('Normalized name not found or ambiguous · needs linking'
                      if source.get('proposed_name') else 'Normalized name missing · needs linking')
        if not person and source['key'] in owner_by_source:
            status = 'Linked employee unavailable or ambiguous'
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
        self._print_helper = None
        self._print_rows = {}
        self._print_as_of = None
        layout = QVBoxLayout(self)
        note = QLabel('Check Leave Balances · Pink rows need name review. Opening balances are from 08/31/2026; VL and SL each earn 1.250 per completed month through today. Imported leave is deducted through today.')
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
        confirm = QPushButton('Confirm name match')
        confirm.clicked.connect(self._confirm_selected)
        controls.addWidget(confirm)
        refresh = QPushButton('Refresh')
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        layout.addLayout(controls)
        printing = QHBoxLayout()
        printing.addWidget(QLabel('Print selected rows · Ctrl / Shift + click for multiple'))
        printing.addStretch(1)
        editor = QPushButton('Print Template Editor')
        editor.clicked.connect(self._open_print_editor)
        printing.addWidget(editor)
        preview = QPushButton('Print Preview')
        preview.clicked.connect(self._open_print_preview)
        printing.addWidget(preview)
        queue = QPushButton('Print Queue')
        queue.clicked.connect(self._open_print_queue)
        printing.addWidget(queue)
        resume = QPushButton('Resume Unprinted')
        resume.clicked.connect(lambda: self._open_print_queue(resume=True))
        printing.addWidget(resume)
        layout.addLayout(printing)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(['Spreadsheet name', 'Employee ID', 'Employee name', 'Opening VL', 'Opening SL', 'VL earned', 'SL earned', 'VL deducted', 'SL deducted', 'Remaining VL', 'Remaining SL', 'Status', 'Source'])
        self.table.setRootIsDecorated(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(11, 280)
        self.table.itemDoubleClicked.connect(lambda *_: self._open_selected())
        layout.addWidget(self.table, 1)

    def refresh_if_needed(self):
        if self._dirty:
            self.refresh()

    def refresh(self):
        self._dirty = False
        p = self.personnel
        links = p._balance_links.all() if p._balance_links is not None else {}
        self._print_as_of = date.today()
        rows = overview_rows(p._balance_rows, p._people, p._records, links, p._regular_holidays, self._print_as_of)
        self._print_rows = {source['key']: (source, person, status, estimate) for source, person, status, estimate in rows}
        self.table.setUpdatesEnabled(False)
        self.table.clear()
        def fmt(value):
            return f'{value:.3f}' if value is not None else '—'
        for source, person, status, estimate in rows:
            values = [source['name'], person.employee_number if person else '—', person.name if person else '—',
                      fmt(source['vl']), fmt(source['sl']),
                      fmt(estimate['earned_vl']) if estimate else '—', fmt(estimate['earned_sl']) if estimate else '—',
                      fmt(estimate['used_vl']) if estimate else '—', fmt(estimate['used_sl']) if estimate else '—',
                      fmt(estimate['vl']) if estimate else '—', fmt(estimate['sl']) if estimate else '—', status,
                      f"{Path(source['path']).name} · {source['sheet']} · row {source['row']}"]
            item = QTreeWidgetItem(values)
            item.setData(0, Qt.ItemDataRole.UserRole, person.employee_number if person else '')
            item.setData(0, Qt.ItemDataRole.UserRole + 1, source['key'])
            item.setData(0, Qt.ItemDataRole.UserRole + 2, status.startswith('Possible name match'))
            if status.startswith('Possible name match'):
                for column in range(len(values)):
                    item.setBackground(column, QBrush(QColor('#f8c9dd')))
                    item.setForeground(column, QBrush(QColor('#25202a')))
            self.table.addTopLevelItem(item)
        self.table.setUpdatesEnabled(True)
        self.status.setText(f'{len(rows)} brought-forward rows loaded. Pink = possible match; select it and confirm after checking both names. For a wrong or ambiguous match, use View employee / Link balance.' if rows else 'No brought-forward rows loaded. Open BAL BROUGHT FORWARD and add your credits workbook.')
        self._filter()

    def _filter(self, *_):
        query = self.search.text().strip().casefold()
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            item.setHidden(query not in ' '.join(item.text(i) for i in range(3)).casefold())

    def set_print_helper(self, helper):
        self._print_helper = helper

    def _selected_print_key(self):
        item = self.table.currentItem()
        if not item or not item.isSelected() or item.isHidden():
            QMessageBox.information(self, 'VER2 Printing', 'Select a visible balance row first.')
            return None
        return item.data(0, Qt.ItemDataRole.UserRole + 1)

    def _make_print_editor(self, key, parent=None):
        return self._print_helper._make_editor(key, parent=parent or self,
                                               rows=self._print_rows, as_of=self._print_as_of)

    def _open_print_editor(self):
        key = self._selected_print_key()
        if key is not None and self._print_helper is not None:
            self._make_print_editor(key).exec()

    def _open_print_preview(self):
        key = self._selected_print_key()
        if key is None or self._print_helper is None:
            return
        from .print_preview import LeaveCardPrintPreview
        from .print_template_editor import TEMPLATE_FILE
        if not TEMPLATE_FILE.is_file():
            QMessageBox.information(self, 'VER2 Printing', 'Open Print Template Editor and save a template first.')
            return
        editor = self._make_print_editor(key)
        LeaveCardPrintPreview(editor).exec()

    def _open_print_queue(self, resume=False):
        if self._print_helper is None:
            return
        from .personnel_print_queue import PersonnelPrintQueue
        from .print_tracker_store import load_statuses
        scope = f'ver2-balance:{self._print_as_of:%Y-%m-%d}'
        statuses = load_statuses(scope)
        selected = {item.data(0, Qt.ItemDataRole.UserRole + 1) for item in self.table.selectedItems() if not item.isHidden()}
        use_unprinted = resume or not selected
        entries = []
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            key = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if not item.isHidden() and ((use_unprinted and statuses.get(str(key)) != 'Confirmed printed') or (not use_unprinted and key in selected)):
                entries.append((key, item.text(2) if item.text(2) != '—' else item.text(0)))
        if not entries:
            QMessageBox.information(self, 'VER2 Print Queue', 'No visible unprinted names to queue.' if use_unprinted else 'No visible rows selected.')
            return
        rows, as_of = dict(self._print_rows), self._print_as_of
        factory = lambda key, name, parent: self._print_helper._make_editor(key, name, parent, rows, as_of)
        review = sum(bool('review' in rows[key][2].casefold() or rows[key][1] is None) for key, _ in entries)
        notice = (f'Check Leave Balances values through {as_of:%B %d, %Y}. '
                  f'{review} selected row(s) need review. Unknown values print blank; '
                  'SPL and WL are carried forward from August 2026.')
        PersonnelPrintQueue(self, entries, None, editor_factory=factory, notice=notice, tracker_scope=scope).exec()

    def _open_selected(self):
        item = self.table.currentItem()
        if not item:
            QMessageBox.information(self, 'Check Leave Balances', 'Select a balance row first.')
            return
        employee_id = item.data(0, Qt.ItemDataRole.UserRole)
        self.open_personnel(employee_id, item.text(0))

    def _confirm_selected(self):
        item = self.table.currentItem()
        if not item or not item.data(0, Qt.ItemDataRole.UserRole + 2):
            QMessageBox.information(self, 'Confirm name match', 'Select a pink possible-match row first.')
            return
        question = (f"Is this the same employee?\n\nCredits: {item.text(0)}\n"
                    f"Personnel: {item.text(2)} ({item.text(1)})")
        if QMessageBox.question(self, 'Confirm name match', question) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.personnel._balance_links.assign(item.data(0, Qt.ItemDataRole.UserRole),
                                                 item.data(0, Qt.ItemDataRole.UserRole + 1))
        except Exception as error:
            QMessageBox.warning(self, 'Confirm name match', str(error))
            return
        self.refresh()
