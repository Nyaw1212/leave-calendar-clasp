from __future__ import annotations

import calendar
from datetime import date
from types import SimpleNamespace

from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
                               QSplitter, QVBoxLayout, QWidget)

from .ver2_balance_overview import overview_rows
from .ver2_balance_list import include_personnel_and_mone
from .ver2_print_fields import ver2_print_fields
from .ver2_database import normalized_name


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
        editor_button = QPushButton('Print Template Editor')
        editor_button.clicked.connect(self._open_editor)
        controls.addWidget(editor_button)
        preview_button = QPushButton('Print Preview')
        preview_button.clicked.connect(self._open_print_preview)
        controls.addWidget(preview_button)
        queue_button = QPushButton('Print Queue')
        queue_button.setToolTip('Select multiple names with Ctrl or Shift, then preview the print queue.')
        queue_button.clicked.connect(self._open_print_queue)
        resume_button = QPushButton('Resume Unprinted')
        resume_button.setToolTip('Queue visible cards that have not been confirmed printed, starting at the bottom.')
        resume_button.clicked.connect(lambda: self._open_print_queue(resume=True))
        controls.addWidget(resume_button)
        controls.addWidget(queue_button)
        layout.addLayout(controls)
        self.coverage = QLabel('')
        self.coverage.setStyleSheet('font-size: 12pt; font-weight: 700; color: #d5bd83;')
        self.coverage.setWordWrap(True)
        layout.addWidget(self.coverage)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search name')
        left_layout.addWidget(self.search)
        selection_hint = QLabel('Ctrl or Shift + click to select names for the print queue.')
        selection_hint.setWordWrap(True)
        left_layout.addWidget(selection_hint)
        self.names = QListWidget()
        self.names.setObjectName('nameList')
        self.names.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.names.setToolTip('Use Ctrl or Shift to select multiple names for the print queue.')
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
        repository = getattr(self.window(), 'repository', None)
        message = ''
        people = list(p._people)
        try:
            if repository is not None:
                known_ids = {person.employee_number for person in people}
                for employee in repository.employees():
                    if employee.employee_id not in known_ids:
                        people.append(SimpleNamespace(name=employee.name, employee_number=employee.employee_id, ver1_only=True))
                        known_ids.add(employee.employee_id)
                for employee_id, snapshot in repository.all_mone_balance_overrides().items():
                    if employee_id not in known_ids and snapshot.get('name'):
                        people.append(SimpleNamespace(name=snapshot['name'], employee_number=employee_id, ver1_only=True))
                        known_ids.add(employee_id)
        except Exception:
            message = ' · MONE balances could not be loaded'
        bis_names = {normalized_name(person.name) for person in p._people}
        match_people = list(p._people) + [person for person in people[len(p._people):]
                                          if normalized_name(person.name) not in bis_names]
        rows = overview_rows(p._balance_rows, match_people, p._records, links, p._regular_holidays, self._as_of)
        try:
            matched_ids = {person.employee_number for _, person, _, _ in rows if person}
            missing_ids = {person.employee_number for person in people if person.employee_number not in matched_ids}
            overrides = repository.mone_balance_fallbacks(missing_ids) if repository is not None else {}
        except Exception:
            overrides = {}
            message = ' · MONE balances could not be loaded'
        rows, covered = include_personnel_and_mone(rows, people, overrides, p._records, p._regular_holidays, self._as_of)
        self.coverage.setText(f'VL and SL values: {covered} / {len(people)} personnel records · MONE 0 / 0 is not counted · [VER1] = additional ID; duplicate names may need review{message}')
        current = self.names.currentItem()
        selected_key = current.data(Qt.ItemDataRole.UserRole) if current else None
        self._rows = {source['key']: (source, person, status, estimate)
                      for source, person, status, estimate in rows}
        self.names.blockSignals(True)
        self.names.clear()
        selected = None
        for source, person, status, estimate in rows:
            name = person.name if person else source['name']
            if person and getattr(person, 'ver1_only', False):
                name += '  [VER1]'
            item = QListWidgetItem(name)
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
        self.names.setCurrentItem(current, QItemSelectionModel.SelectionFlag.NoUpdate)
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
        if source.get('fallback_kind') == 'mone':
            if not source.get('august_usable'):
                self.period.setText('AUGUST BALANCE UNAVAILABLE · REVIEW SOURCE')
        elif source.get('fallback_kind') == 'missing':
            self.period.setText('NO BALANCE AVAILABLE')
        within_year = self._as_of.year == 2026 and self._as_of >= date(2026, 8, 31)
        balances = {
            'VL': estimate.get('vl') if estimate else None,
            'SL': estimate.get('sl') if estimate else None,
            'FL': estimate.get('fl') if estimate else None,
            'SPL': source.get('spl') if person and within_year else None,
            'WL': source.get('wl') if person and within_year else None,
        }
        for label, value in balances.items():
            text = (f'{value:.0f}' if label in {'FL', 'SPL', 'WL'} else f'{value:.3f}') if value is not None else '—'
            self.values[label].setText(text)
            self.values[label].setToolTip(f'Exact balance: {value:.3f}' if value is not None and label in {'FL', 'SPL', 'WL'} else '')
        note = ('Opening balances: August 31, 2026. VL and SL earn 1.250 each per completed month; VL, SL and FL reflect imported leave. '
                'SPL and WL are carried forward from August because later leave is not imported. '
                'Check unmatched leave and import issues. — means unavailable or needs review.')
        if source.get('fallback_kind') == 'mone':
            if source.get('august_usable'):
                origin = {'history': 'VER1 leave history calculated through August 31, 2026',
                          'catchup': 'VER1 MONE catch-up reconstructed through August 2026',
                          'manual': 'VER1 MONE saved balance treated as the August 2026 opening'}.get(source.get('mone_kind'), 'VER1 balance')
                note = (f'Source: {origin}. VL and SL each earn 1.250 per completed month after August; '
                        'matched VER2 leave is deducted. SPL, FL and WL openings are unavailable. '
                        'Review the source and unmatched leave.')
            else:
                note = ('The last credited month in the VER1 MONE entry is after August 2026, '
                        'so the August opening cannot be determined. Review the source before calculating.')
            if source.get('mone_zero'):
                note += ' MONE 0 / 0 is not counted as encoded.'
        if status.startswith('Possible name match'):
            note = f'{status}. NAME MATCH: credits {source["name"]} / personnel {person.name}. Confirm in Check Leave Balances.\n' + note
        elif status != 'Exact name match' and status != 'Manually linked':
            note = f'{status}.\n' + note
        self.note.setText(note)

    def _print_row(self):
        item = self.names.currentItem()
        if item is None or not item.isSelected():
            QMessageBox.information(self, 'VER2 Printing', 'Select a name first.')
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _make_editor(self, key, _name='', parent=None, rows=None, as_of=None):
        from types import SimpleNamespace
        from .print_template_editor import TemplateEditorDialog
        source, person, _status, estimate = (rows if rows is not None else self._rows)[key]
        when = as_of if as_of is not None else self._as_of
        assumption = None
        repository = getattr(self.window(), 'repository', None)
        if person and repository is not None:
            employee = repository.employee_by_id(person.employee_number)
            assumption = getattr(employee, 'assumption_date', None) if employee else None
        fields = ver2_print_fields(source, person, estimate, when, assumption)
        employee = SimpleNamespace(name=fields['name'], assumption_date=assumption)
        editor = TemplateEditorDialog(parent or self, employee=employee, repository=None, field_values=fields)
        editor.setWindowTitle(f'VER2 · Print Template Editor · {when:%B %Y} · {_status}')
        return editor

    def _open_editor(self):
        key = self._print_row()
        if key is not None:
            self._make_editor(key).exec()

    def _open_print_preview(self):
        key = self._print_row()
        if key is None:
            return
        from .print_preview import LeaveCardPrintPreview
        from .print_template_editor import TEMPLATE_FILE
        if not TEMPLATE_FILE.is_file():
            QMessageBox.information(self, 'VER2 Printing', 'Open Print Template Editor and save a template first.')
            return
        editor = self._make_editor(key)
        LeaveCardPrintPreview(editor).exec()

    def _open_print_queue(self, resume=False):
        from .personnel_print_queue import PersonnelPrintQueue
        from .print_tracker_store import is_printed_or_sent, load_statuses
        scope = f'ver2-balance:{self._as_of:%Y-%m-%d}'
        statuses = load_statuses(scope)
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.names.selectedItems() if not item.isHidden()}
        use_unprinted = resume or not selected
        entries = []
        for index in range(self.names.count() - 1, -1, -1):
            item = self.names.item(index)
            key = item.data(Qt.ItemDataRole.UserRole)
            if not item.isHidden() and ((use_unprinted and not is_printed_or_sent(statuses.get(str(key)))) or (not use_unprinted and key in selected)):
                entries.append((key, item.text()))
                if len(entries) == 10:
                    break
        if not entries:
            QMessageBox.information(self, 'VER2 Print Queue', 'No visible unprinted names to queue.' if use_unprinted else 'No visible names selected.')
            return
        # Snapshot rows and period so every page in a batch uses the same data.
        rows, as_of = {key: self._rows[key] for key, _ in entries}, self._as_of
        factory = lambda key, name, parent: self._make_editor(key, name, parent, rows, as_of)
        review = sum(bool('review' in rows[key][2].casefold() or rows[key][1] is None or rows[key][0].get('fallback_kind')) for key, _ in entries)
        notice = (f'Loaded up to 10 cards from the bottom. VER2 balances as of {as_of:%B %d, %Y}. {review} selected name(s) need review. '
                  'Unknown values print blank. VER1 fallbacks use an August opening; check their source and matched leave. SPL and WL for B/F rows are carried forward from August 2026.')
        PersonnelPrintQueue(self, entries, None, editor_factory=factory, notice=notice, tracker_scope=scope).exec()
