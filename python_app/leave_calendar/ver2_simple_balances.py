from __future__ import annotations

import calendar
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QSpinBox,
                               QSplitter, QVBoxLayout, QWidget)

from .ver2_balance_overview import overview_rows


class Ver2SimpleBalances(QWidget):
    """Select a person to see a spacious month-end balance summary."""

    def __init__(self, personnel):
        super().__init__()
        self.personnel = personnel
        self._rows = {}
        self._as_of = None
        self.setStyleSheet('''
            QFrame#balancePanel { background: #151b28; border: 1px solid #655a43; border-radius: 12px; }
            QFrame#balanceCard { background: #20293a; border: 1px solid #675b45; border-radius: 12px; }
            QLabel#cardTitle { color: #d5bd83; font-size: 15pt; font-weight: 700; border: none; }
            QLabel#cardValue { color: #faf4e7; font-size: 36pt; font-weight: 700; border: none; }
            QLabel#cardCode { color: #d5bd83; font-size: 14pt; font-weight: 700; border: none; }
            QLabel#employeeName { color: #faf4e7; font-size: 23pt; font-weight: 700; border: none; }
            QLabel#balanceCaption { color: #d5bd83; font-size: 11pt; font-weight: 600; border: none; }
            QLabel#balanceNote { color: #c2c8d3; font-size: 10pt; border: none; }
            QListWidget#nameList { background: #151b28; color: #f0ede6; border: 1px solid #655a43; border-radius: 10px; font-size: 16pt; outline: none; }
            QListWidget#nameList::item { padding: 10px 12px; border-bottom: 1px solid #313747; }
            QListWidget#nameList::item:selected { background: #3d3a35; color: #fff7e8; }
        ''')
        layout = QVBoxLayout(self)
        title = QLabel('Leave Balance')
        title.setStyleSheet('font-size: 22pt; font-weight: 800; color: #f1e3c1;')
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
        controls.addStretch(1)
        layout.addLayout(controls)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search name')
        left_layout.addWidget(self.search)
        self.names = QListWidget()
        self.names.setObjectName('nameList')
        left_layout.addWidget(self.names, 1)
        split.addWidget(left)

        panel = QFrame()
        panel.setObjectName('balancePanel')
        detail = QVBoxLayout(panel)
        detail.setContentsMargins(28, 22, 28, 22)
        caption = QLabel('REMAINING LEAVE BALANCE  /  MONTH-END')
        caption.setObjectName('balanceCaption')
        detail.addWidget(caption)
        self.name = QLabel('Select a name')
        self.name.setObjectName('employeeName')
        self.name.setWordWrap(True)
        detail.addWidget(self.name)
        self.period = QLabel('')
        self.period.setObjectName('balanceCaption')
        detail.addWidget(self.period)
        grid = QGridLayout()
        grid.setSpacing(14)
        self.values = {}
        value_colors = {'VL': '#81D9A6', 'SL': '#FF9095', 'FL': '#EBC482',
                        'WL': '#8BCBEF', 'SPL': '#CBAFEF'}
        for label, full, row, col, span in [
            ('VL', 'VACATION LEAVE', 0, 0, 1), ('SL', 'SICK LEAVE', 0, 1, 1),
            ('FL', 'FORCED LEAVE', 1, 0, 1), ('WL', 'WELLNESS LEAVE', 1, 1, 1),
            ('SPL', 'SPECIAL PRIVILEGE LEAVE', 2, 0, 2),
        ]:
            card = QFrame()
            card.setObjectName('balanceCard')
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 12, 18, 12)
            heading = QLabel(full)
            heading.setObjectName('cardTitle')
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(heading)
            value = QLabel('—')
            value.setObjectName('cardValue')
            value.setStyleSheet(f'color: {value_colors[label]}; font-size: 36pt; font-weight: 700; border: none;')
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(value)
            code = QLabel(label)
            code.setObjectName('cardCode')
            code.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(code)
            self.values[label] = value
            grid.addWidget(card, row, col, 1, span)
        detail.addLayout(grid, 1)
        self.note = QLabel('')
        self.note.setObjectName('balanceNote')
        self.note.setWordWrap(True)
        detail.addWidget(self.note)
        split.addWidget(panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setSizes([500, 900])
        layout.addWidget(split, 1)
        self.search.textChanged.connect(self._filter)
        self.names.currentItemChanged.connect(self._show_selected)
        self.month.currentIndexChanged.connect(self.refresh)
        self.year.valueChanged.connect(self.refresh)

    def refresh(self, *_):
        year, month = self.year.value(), self.month.currentData()
        self._as_of = date(year, month, calendar.monthrange(year, month)[1])
        p = self.personnel
        links = p._balance_links.all() if p._balance_links is not None else {}
        rows = overview_rows(p._balance_rows, p._people, p._records, links, p._regular_holidays, self._as_of)
        current = self.names.currentItem()
        selected_key = current.data(Qt.ItemDataRole.UserRole) if current else None
        self._rows = {source['key']: (source, person, status, estimate)
                      for source, person, status, estimate in rows}
        self.names.blockSignals(True)
        self.names.clear()
        selected = None
        for source, person, status, estimate in rows:
            item = QListWidgetItem(person.name if person else source['name'])
            item.setData(Qt.ItemDataRole.UserRole, source['key'])
            self.names.addItem(item)
            if source['key'] == selected_key:
                selected = item
        self.names.blockSignals(False)
        self._filter(preferred=selected)

    def _filter(self, *_args, preferred=None):
        query = self.search.text().strip().casefold()
        first = None
        for index in range(self.names.count()):
            item = self.names.item(index)
            item.setHidden(query not in item.text().casefold())
            if not item.isHidden() and first is None:
                first = item
        current = preferred or self.names.currentItem()
        if current is None or current.isHidden():
            current = first
        self.names.setCurrentItem(current)
        self._show_selected(current)

    def _show_selected(self, item, *_):
        for value in self.values.values():
            value.setText('—')
        self.period.setText(f'AS OF {self._as_of:%B %d, %Y}' if self._as_of else '')
        self.note.setText('Select a name to view balances.')
        if item is None:
            self.name.setText('No matching name')
            return
        source, person, status, estimate = self._rows[item.data(Qt.ItemDataRole.UserRole)]
        self.name.setText(person.name if person else source['name'])
        within_year = self._as_of.year == 2026 and self._as_of >= date(2026, 8, 31)
        balances = {
            'VL': estimate.get('vl') if estimate else None,
            'SL': estimate.get('sl') if estimate else None,
            'FL': estimate.get('fl') if estimate else None,
            'SPL': source.get('spl') if person and within_year else None,
            'WL': source.get('wl') if person and within_year else None,
        }
        for label, value in balances.items():
            self.values[label].setText(f'{value:.3f}' if value is not None else '—')
        note = ('Opening balances: August 31, 2026. VL, SL and FL reflect imported leave; earned credits are not included. '
                'SPL and WL are carried forward from August because later leave is not imported. '
                'Check unmatched leave and import issues. — means unavailable or needs review.')
        if status.startswith('Possible name match'):
            note = f'{status}. NAME MATCH: credits {source["name"]} / personnel {person.name}. Confirm in Check Leave Balances.\n' + note
        elif status != 'Exact name match' and status != 'Manually linked':
            note = f'{status}.\n' + note
        self.note.setText(note)
