from __future__ import annotations

import calendar
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .ver2_balance_overview import overview_rows


class Ver2SimpleBalances(QWidget):
    """A compact month-end view of the brought-forward workbook."""

    def __init__(self, personnel):
        super().__init__()
        self.personnel = personnel
        layout = QVBoxLayout(self)
        title = QLabel('Leave Balance')
        title.setStyleSheet('font-size: 20pt; font-weight: 700;')
        layout.addWidget(title)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('As of the end of'))
        self.month = QComboBox()
        for month in range(1, 13):
            self.month.addItem(calendar.month_name[month], month)
        self.month.setCurrentIndex(date.today().month - 1)
        controls.addWidget(self.month)
        self.year = QSpinBox()
        self.year.setRange(2026, 2100)
        self.year.setValue(max(2026, date.today().year))
        controls.addWidget(self.year)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search name or employee ID')
        controls.addWidget(self.search, 1)
        layout.addLayout(controls)
        self.note = QLabel('')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.table = QTreeWidget()
        self.table.setHeaderLabels(['Name', 'Employee ID', 'VL', 'SL', 'SPL', 'FL', 'WL'])
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        font = QFont(self.table.font())
        font.setPointSize(36)
        self.table.setFont(font)
        self.table.header().setFont(font)
        self.table.setStyleSheet('QTreeWidget { font-size: 36pt; } QHeaderView::section { font-size: 36pt; }')
        self.table.setColumnWidth(0, 700)
        self.table.setColumnWidth(1, 300)
        for column in range(2, 7):
            self.table.setColumnWidth(column, 200)
        layout.addWidget(self.table, 1)
        self.search.textChanged.connect(self._filter)
        self.month.currentIndexChanged.connect(self.refresh)
        self.year.valueChanged.connect(self.refresh)

    def refresh(self, *_):
        year, month = self.year.value(), self.month.currentData()
        as_of = date(year, month, calendar.monthrange(year, month)[1])
        p = self.personnel
        links = p._balance_links.all() if p._balance_links is not None else {}
        rows = overview_rows(p._balance_rows, p._people, p._records, links, p._regular_holidays, as_of)
        self.note.setText(
            f'As of {as_of:%B %d, %Y}. Opening balances are from August 31, 2026. '
            'VL, SL and FL reflect imported leave; earned credits are not added. '
            'SPL and WL are carried forward from August because their later leave is not imported. '
            'Review provisional name matches in Check Leave Balances. '
            '— = unavailable or requires review. Verify unmatched leave and import issues.')
        self.table.setUpdatesEnabled(False)
        self.table.clear()
        def fmt(value):
            return f'{value:.3f}' if value is not None else '—'
        for source, person, status, estimate in rows:
            within_year = as_of.year == 2026 and as_of >= date(2026, 8, 31)
            values = [person.name if person else source['name'], person.employee_number if person else '—',
                      fmt(estimate['vl']) if estimate else '—', fmt(estimate['sl']) if estimate else '—',
                      fmt(source.get('spl')) if person and within_year else '—',
                      fmt(estimate.get('fl')) if estimate else '—',
                      fmt(source.get('wl')) if person and within_year else '—']
            item = QTreeWidgetItem(values)
            detail = status + f"\nCredits name: {source['name']}"
            if person:
                detail += f'\nPersonnel name: {person.name}'
            for column in range(len(values)):
                item.setToolTip(column, detail)
            self.table.addTopLevelItem(item)
        self.table.setUpdatesEnabled(True)
        self._filter()

    def _filter(self, *_):
        query = self.search.text().strip().casefold()
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            item.setHidden(query not in (item.text(0) + ' ' + item.text(1)).casefold())
