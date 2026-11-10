from __future__ import annotations

import calendar
import csv
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt, QDate, QItemSelectionModel
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDateEdit, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox,
                               QSplitter, QVBoxLayout, QWidget)

from .ver2_balance_overview import overview_rows
from .ver2_balance_list import include_personnel_and_mone
from .ver2_print_fields import ver2_print_fields
from .ver2_database import normalized_name
from .ver2_balances import resolve_balance_matches


def web_export_rows(rows, as_of, updated_at):
    """Export the values shown for every balance row, including unavailable rows."""
    within_year = as_of.year == 2026 and as_of >= date(2026, 8, 31)
    result = []
    for source, person, status, estimate in rows:
        employee_id = str(getattr(person, 'employee_number', '') or '').strip() if person else ''
        name = person.name if person else source.get('name', '')
        values = [(estimate.get(key) if estimate else None) for key in ('vl', 'sl', 'fl')]
        values += [source.get('wl') if person and within_year else None]
        values += [estimate.get('spl') if estimate else None]
        # Match the displayed precision, and preserve a blank for unavailable values.
        formatted = [('' if value is None else (f'{value:.3f}' if index < 2 else f'{value:.0f}'))
                     for index, value in enumerate(values)]
        result.append([employee_id, name, as_of.isoformat(), *formatted, updated_at])
    return result


def balance_diagnostics(source, person, status, estimate, people, records, rows, as_of, balance_rows=None):
    """Describe the selected row using only data already loaded by VER2."""
    name = person.name if person else source.get('name', '')
    lines = [f'Person: {name}', f'As of: {as_of:%B %d, %Y}', '']
    issues = []
    employee_id = getattr(person, 'employee_number', '') if person else ''
    if not person:
        lines.append('BIS / personnel: Not linked to a unique employee.')
        issues.append('Review the employee and link the balance using VER2 Personnel Files → Link Balance.')
    elif getattr(person, 'ver1_only', False):
        lines.append(f'Personnel ID: {employee_id or "unavailable"} (VER1 record; BIS link not confirmed).')
        issues.append('Check the BIS personnel record and employee number before relying on this balance.')
    elif not employee_id:
        lines.append('BIS employee ID: unavailable for this linked name.')
        issues.append('Review the personnel record and its BIS employee number.')
    else:
        lines.append(f'BIS employee: {person.name} · ID: {employee_id}')
        duplicates = [p for p in people if normalized_name(getattr(p, 'name', '')) == normalized_name(person.name)]
        id_duplicates = [p for p in people if getattr(p, 'employee_number', '') == employee_id]
        if len(duplicates) > 1 or len(id_duplicates) > 1:
            issues.append('The loaded personnel list has a duplicate name or employee ID; verify the records before linking.')

    kind = source.get('fallback_kind')
    if kind == 'missing':
        lines.append('Brought-forward balance: No linked balance or usable VER1 fallback for this row.')
        issues.append('Check BAL BROUGHT FORWARD and link the correct balance to the employee.')
    elif kind == 'mone':
        lines.append('Balance source: VER1 MONE / leave-history fallback, not a brought-forward workbook row.')
        lines.append('FL, WL and SPL opening values are unavailable from this fallback.')
        issues.append('Check the fallback source and link the correct brought-forward row if available.')
        if not source.get('august_usable', True):
            issues.append('The August opening could not be established from this fallback.')
    else:
        path = source.get('path', '')
        lines.append('Brought-forward name: ' + str(source.get('name', '—')))
        if path:
            lines.append(f"Source: {Path(path).name} · {source.get('sheet', '')} · row {source.get('row', '—')}")
            if not Path(path).is_file():
                issues.append('The source workbook is not currently at its saved location; locate it and reload.')
        missing = [label for label, field in [('VL', 'vl'), ('SL', 'sl'), ('FL', 'fl'), ('WL', 'wl'), ('SPL', 'spl')]
                   if source.get(field) is None]
        lines.append('Opening values: ' + ('Missing ' + ', '.join(missing) if missing else 'VL, SL, FL, WL and SPL available.'))
        if missing:
            issues.append('Check the missing opening values in BAL BROUGHT FORWARD. A blank is not treated as zero.')
        if not person and source.get('has_normal_match_column') and not source.get('proposed_name'):
            issues.append('The workbook normalized-match name is blank; review and link the correct BIS employee.')
    lines.append('Match status: ' + str(status))
    if status.startswith('Possible name match'):
        issues.append('The name match is provisional; compare the source and employee names and confirm the match.')

    # Search the original B/F rows, including rows not linked to any employee.
    name_key = normalized_name(name)
    matches = [b for b in (balance_rows or []) if name_key and
               name_key in {normalized_name(b.get('name', '')), normalized_name(b.get('proposed_name', ''))}]
    lines.extend(['', 'BROUGHT-FORWARD NAME CHECK'])
    if not matches:
        lines.append('No exact name match found in the currently loaded brought-forward rows.')
        issues.append('Check the spelling and reload the brought-forward workbook if needed.')
    else:
        lines.append(f'{len(matches)} exact name match(es) in loaded brought-forward data. These are opening credits, not current balances.')
        for match in matches:
            location = f"{Path(match.get('path') or '').name or 'Unknown file'} · {match.get('sheet') or 'Unknown sheet'} · row {match.get('row', '—')}"
            values = ' · '.join(f"{label}: {match.get(field) if match.get(field) is not None else '— (missing)'}"
                                for label, field in [('VL', 'vl'), ('SL', 'sl'), ('FL', 'fl'), ('WL', 'wl'), ('SPL', 'spl')])
            lines.append(f"{match.get('name', '—')} — {location}\n{values}")
        if len(matches) > 1:
            issues.append('Multiple brought-forward rows have the same name. Verify the source and employee before linking.')
        if not person:
            issues.append('The name check does not establish a BIS identity. Verify the employee before linking.')

    same_name = [r for r in rows.values() if normalized_name((r[1].name if r[1] else r[0].get('name', ''))) == normalized_name(name)]
    if len(same_name) > 1:
        issues.append(f'{len(same_name)} visible balance records have this exact name. They may be unlinked or different people; verify IDs and sources.')
    history_name = getattr(person, 'name', '') if person else ''
    history = records.get(normalized_name(history_name), []) if history_name else []
    if history_name:
        lines.append(f'Imported VER2 leave rows matched by name: {len(history)}.')
        if not history:
            issues.append('No imported VER2 leave rows matched this exact name. Check uploaded files and name spelling; this does not prove no leave was filed.')
    else:
        lines.append('Imported VER2 leave: Cannot check against a linked employee until the balance is linked.')
    if estimate and estimate.get('review'):
        issues.append('The calculation reports conflicting leave or unavailable holiday data; review the VER2 audit.')
    if as_of < date(2026, 8, 31):
        issues.append('The selected month is before the August 31, 2026 brought-forward opening; choose a later month.')
    if as_of.year != 2026:
        issues.append('FL, WL and SPL balances are not available for this selected year under the current calculation rules.')
    lines.extend(['', 'WHAT TO CHECK'])
    lines.extend(f'• {issue}' for issue in issues) if issues else lines.append('No missing items detected in the loaded data. Review the source and audit before using the balance.')
    return '\n'.join(lines)


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
        troubleshoot_button = QPushButton('Troubleshoot')
        troubleshoot_button.setToolTip('Check what is missing or needs review for the selected person.')
        troubleshoot_button.clicked.connect(self._troubleshoot_selected)
        controls.addWidget(troubleshoot_button)
        export_web_button = QPushButton('Export for Leave Checker')
        export_web_button.setToolTip('Export every balance row for the selected month to a CSV file.')
        export_web_button.clicked.connect(self._export_web_balances)
        controls.addWidget(export_web_button)
        add_bis_button = QPushButton('Add BIS / Link')
        add_bis_button.setToolTip('Add a verified BIS employee and link the selected brought-forward balance.')
        add_bis_button.clicked.connect(self._add_bis_selected)
        controls.addWidget(add_bis_button)
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

    def _calculate_rows(self, as_of):
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
        name_links = p._balance_links.source_links() if p._balance_links is not None else {}
        rows = overview_rows(p._balance_rows, match_people, p._records, links, p._regular_holidays, as_of, name_links)
        try:
            matched_ids = {person.employee_number for _, person, _, _ in rows if person}
            missing_ids = {person.employee_number for person in people if person.employee_number not in matched_ids}
            overrides = repository.mone_balance_fallbacks(missing_ids) if repository is not None else {}
        except Exception:
            overrides = {}
            message = ' · MONE balances could not be loaded'
        rows, covered = include_personnel_and_mone(rows, people, overrides, p._records, p._regular_holidays, as_of)
        return rows, covered, len(people), message

    def refresh(self, *_):
        year, month = self.year.value(), self.month.currentData()
        self._as_of = date(year, month, calendar.monthrange(year, month)[1])
        rows, covered, people_count, message = self._calculate_rows(self._as_of)
        self.coverage.setText(f'VL and SL values: {covered} / {people_count} personnel records · MONE 0 / 0 is not counted · [VER1] = additional ID; duplicate names may need review{message}')
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
            'SPL': estimate.get('spl') if estimate else None,
            'WL': source.get('wl') if person and within_year else None,
        }
        for label, value in balances.items():
            text = (f'{value:.0f}' if label in {'FL', 'SPL', 'WL'} else f'{value:.3f}') if value is not None else '—'
            self.values[label].setText(text)
            self.values[label].setToolTip(f'Exact balance: {value:.3f}' if value is not None and label in {'FL', 'SPL', 'WL'} else '')
        note = ('Opening balances: August 31, 2026. VL and SL earn 1.250 each per completed month; VL, SL, FL and SPL reflect imported leave. '
                'WL is carried forward from August because later leave is not imported. '
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

    def _export_web_balances(self):
        if not self._rows or self._as_of is None:
            QMessageBox.information(self, 'Export for Leave Checker', 'Load the personnel and balance data first.')
            return
        date_dialog = QDialog(self)
        date_dialog.setWindowTitle('Choose balance date')
        date_layout = QVBoxLayout(date_dialog)
        explanation = QLabel('Calculate balances through this date. Today is selected by default; choose month-end for a projection. The export time is recorded separately.')
        explanation.setWordWrap(True)
        date_layout.addWidget(explanation)
        date_picker = QDateEdit()
        date_picker.setCalendarPopup(True)
        date_picker.setDisplayFormat('MMM d, yyyy')
        date_picker.setMinimumDate(QDate(2026, 8, 31))
        date_picker.setMaximumDate(QDate(2100, 12, 31))
        date_picker.setDate(QDate.currentDate())
        date_layout.addWidget(date_picker)
        date_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        date_buttons.accepted.connect(date_dialog.accept)
        date_buttons.rejected.connect(date_dialog.reject)
        date_layout.addWidget(date_buttons)
        if date_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = date_picker.date()
        export_date = date(selected.year(), selected.month(), selected.day())
        rows, _covered, _people_count, message = self._calculate_rows(export_date)
        if message:
            QMessageBox.warning(self, 'Export for Leave Checker', 'Could not load all VER1/MONE balances. Check the data and try again; no file was exported.')
            return
        exported = web_export_rows(rows, export_date, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        ids = Counter(row[0].casefold() for row in exported if row[0])
        missing = sum(not row[0] for row in exported)
        duplicates = sum(1 for row in exported if row[0] and ids[row[0].casefold()] > 1)
        provisional = sum(str(row[2]).startswith('Possible name match') for row in rows)
        warning = (f'Export {len(exported)} balance rows as of {export_date:%B %d, %Y}?\\n\\n'
                   f'{missing} rows have no employee number; {duplicates} rows have a duplicate number; '
                   f'{provisional} rows have a possible name match requiring review. '
                   'The web app cannot look up missing or duplicate IDs. Review possible matches before publishing. '
                   'Unavailable values will be blank.')
        if QMessageBox.question(self, 'Export for Leave Checker', warning) != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export for Leave Checker',
            f'leave_balances_{export_date:%Y-%m-%d}.csv', 'CSV files (*.csv)')
        if not path:
            return
        if not path.lower().endswith('.csv'):
            path += '.csv'
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as output:
                writer = csv.writer(output)
                writer.writerow(['employee_id', 'name', 'as_of', 'vl', 'sl', 'fl', 'wl', 'spl', 'updated_at'])
                writer.writerows(exported)
        except (OSError, csv.Error) as error:
            QMessageBox.warning(self, 'Export for Leave Checker', f'Could not save the file: {error}')
            return
        QMessageBox.information(self, 'Export for Leave Checker',
            f'Saved {len(exported)} rows to {path}. Review the file before importing it into the LeaveBalances sheet.')

    def _troubleshoot_selected(self):
        item = self.names.currentItem()
        if item is None or item.isHidden():
            QMessageBox.information(self, 'Troubleshoot leave balance', 'Select a person first.')
            return
        row = self._rows.get(item.data(Qt.ItemDataRole.UserRole))
        if row is None or self._as_of is None:
            QMessageBox.information(self, 'Troubleshoot leave balance', 'The selected balance is not available. Refresh and try again.')
            return
        source, person, status, estimate = row
        text = balance_diagnostics(source, person, status, estimate, self.personnel._people,
                                   self.personnel._records, self._rows, self._as_of, self.personnel._balance_rows)
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Troubleshoot leave balance')
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(text)
        dialog.addButton(QMessageBox.StandardButton.Ok)
        # The add action needs a real B/F row and must not duplicate an existing BIS record.
        can_add_bis = (not source.get('fallback_kind') and bool(source.get('path')) and
                       (not person or not getattr(person, 'employee_number', '') or
                        getattr(person, 'ver1_only', False)))
        add_button = dialog.addButton('Add BIS / Link', QMessageBox.ButtonRole.ActionRole) if can_add_bis else None
        link_button = dialog.addButton('Link existing BIS employee', QMessageBox.ButtonRole.ActionRole) if can_add_bis else None
        can_view_card = source.get('fallback_kind') == 'mone' and person and getattr(person, 'employee_number', '')
        card_button = dialog.addButton('View leave card', QMessageBox.ButtonRole.ActionRole) if can_view_card else None
        dialog.exec()
        if add_button is not None and dialog.clickedButton() == add_button:
            self._add_bis_selected()
        elif link_button is not None and dialog.clickedButton() == link_button:
            self._link_existing_bis(row)
        elif card_button is not None and dialog.clickedButton() == card_button:
            self._view_fallback_card(person)

    def _view_fallback_card(self, person):
        from .card_preview import LeaveCardPreviewPage
        dialog = QDialog(self)
        dialog.setWindowTitle(f'Leave card · {person.name} · {person.employee_number}')
        dialog.resize(1100, 750)
        layout = QVBoxLayout(dialog)
        viewer = LeaveCardPreviewPage(dialog, embedded=True)
        # This shortcut is for viewing; attaching cards remains in the normal card workflow.
        viewer.attach_button.hide()
        viewer.set_employee_context(person.employee_number, person.name)
        if not viewer._source_path:
            viewer._clear_preview(f'No leave card is attached for {person.name} ({person.employee_number}). Use Open Temporary File to view a card.')
        layout.addWidget(viewer)
        dialog.exec()

    def _link_existing_bis(self, row):
        source, _person, _status, _estimate = row
        links = self.personnel._balance_links
        if links is None or not source.get('key'):
            QMessageBox.warning(self, 'Link existing BIS employee', 'The balance linking database is unavailable.')
            return
        # Read the same local list used by Add BIS, so a recently added employee is not missed.
        repository = getattr(self.window(), 'repository', None)
        if repository is None:
            QMessageBox.warning(self, 'Link existing BIS employee', 'The local BIS database is unavailable.')
            return
        try:
            people = repository.bis_personnel()
        except Exception as error:
            QMessageBox.warning(self, 'Link existing BIS employee', f'Could not load the BIS list: {error}')
            return
        overview = getattr(self, 'balance_overview', None)
        loaded = {(p.employee_number, p.name) for p in self.personnel._people}
        if overview is not None and loaded != {(p.employee_number, p.name) for p in people}:
            overview.bis_personnel_added.emit(people)
        name_counts, id_counts = {}, {}
        for person in people:
            name_key = normalized_name(getattr(person, 'name', ''))
            employee_id = str(getattr(person, 'employee_number', '') or '').strip().casefold()
            if name_key:
                name_counts[name_key] = name_counts.get(name_key, 0) + 1
            if employee_id:
                id_counts[employee_id] = id_counts.get(employee_id, 0) + 1
        candidates = sorted([p for p in people if getattr(p, 'employee_number', '')],
                            key=lambda p: (p.name.casefold(), str(p.employee_number)))
        if not candidates:
            QMessageBox.information(self, 'Link existing BIS employee', 'No BIS employees are available. Load the BIS list first.')
            return
        picker = QDialog(self)
        picker.setWindowTitle('Link existing BIS employee')
        picker.resize(650, 500)
        layout = QVBoxLayout(picker)
        note = QLabel(f"Balance: {source.get('name', '')}. Search by name or employee number, then select the correct employee.")
        note.setWordWrap(True)
        layout.addWidget(note)
        search = QLineEdit()
        search.setPlaceholderText('Search name or employee number')
        layout.addWidget(search)
        choices = QListWidget()
        layout.addWidget(choices)
        counts = QLabel()
        layout.addWidget(counts)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(picker.accept)
        buttons.rejected.connect(picker.reject)
        choices.itemDoubleClicked.connect(lambda _item: picker.accept())
        layout.addWidget(buttons)

        def filter_people(value):
            query = ' '.join(value.casefold().split())
            choices.clear()
            for candidate in candidates:
                if query not in f"{candidate.name} {candidate.employee_number}".casefold():
                    continue
                duplicate = (name_counts.get(normalized_name(candidate.name), 0) > 1 or
                             id_counts.get(str(candidate.employee_number).strip().casefold(), 0) > 1)
                label = f"{candidate.name} · {candidate.employee_number}" + (' · duplicate: review' if duplicate else '')
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, candidate)
                choices.addItem(item)
            counts.setText(f'{choices.count()} matching BIS employee(s). Select a row to continue.')

        search.textChanged.connect(filter_people)
        surname = source.get('name', '').split(',', 1)[0].strip()
        if surname:
            search.setText(surname)
        else:
            filter_people('')
        search.setFocus()
        while picker.exec() == QDialog.DialogCode.Accepted:
            item = choices.currentItem()
            if item is None:
                QMessageBox.information(picker, 'Link existing BIS employee', 'Select an employee from the list first.')
                continue
            person = item.data(Qt.ItemDataRole.UserRole)
            if (name_counts.get(normalized_name(person.name), 0) > 1 or
                id_counts.get(str(person.employee_number).strip().casefold(), 0) > 1):
                QMessageBox.warning(picker, 'Link existing BIS employee', 'This name or employee number is duplicated in the BIS list. Review the duplicate records before linking.')
                continue
            break
        else:
            return
        current_matches = resolve_balance_matches(self.personnel._balance_rows, people, links.all())
        occupied = current_matches.get(source['key'])
        if occupied and occupied[0].employee_number != person.employee_number:
            QMessageBox.warning(self, 'Link existing BIS employee', 'This balance already matches another BIS employee. Review that match first.')
            return
        other_matches = [key for key, value in current_matches.items()
                         if key != source['key'] and value[0].employee_number == person.employee_number]
        if other_matches:
            QMessageBox.warning(self, 'Link existing BIS employee', 'This employee already matches a different brought-forward row. Review that match first.')
            return
        if QMessageBox.question(self, 'Confirm balance link',
            f"Link {person.name} ({person.employee_number}) to the brought-forward balance for {source.get('name', '')}?\\n\\nVerify both records refer to the same person.") != QMessageBox.StandardButton.Yes:
            return
        try:
            # This refuses to overwrite another employee or a conflicting name link.
            links.assign_new_bis(person.employee_number, source['key'], person.name)
        except Exception as error:
            QMessageBox.warning(self, 'Link existing BIS employee', str(error))
            return
        overview = getattr(self, 'balance_overview', None)
        if overview is not None:
            overview._dirty = True
        self.refresh()
        QMessageBox.information(self, 'Balance linked', f"{person.name} is linked to {source.get('name', '')}. Review the displayed balance and imported leave records.")

    def _add_bis_selected(self):
        item = self.names.currentItem()
        row = self._rows.get(item.data(Qt.ItemDataRole.UserRole)) if item and not item.isHidden() else None
        if row is None:
            QMessageBox.information(self, 'Add BIS / Link', 'Select a brought-forward balance row first.')
            return
        overview = getattr(self, 'balance_overview', None)
        if overview is None:
            QMessageBox.warning(self, 'Add BIS / Link', 'The balance linking tool is unavailable.')
            return
        overview._quick_add_bis(row)
        self.refresh()

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
        if person and person.employee_number and repository is not None:
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
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.names.selectedItems() if not item.isHidden()}
        use_unprinted = resume or not selected
        remaining = iter(range(self.names.count() - 1, -1, -1))
        def load_batch():
            statuses = load_statuses(scope) if use_unprinted else {}
            batch = []
            for index in remaining:
                item = self.names.item(index)
                key = item.data(Qt.ItemDataRole.UserRole)
                if not item.isHidden() and ((use_unprinted and not is_printed_or_sent(statuses.get(str(key)))) or (not use_unprinted and key in selected)):
                    batch.append((key, item.text()))
                    if len(batch) == 10:
                        break
            return batch
        entries = load_batch()
        if not entries:
            QMessageBox.information(self, 'VER2 Print Queue', 'No visible unprinted names to queue.' if use_unprinted else 'No visible names selected.')
            return
        # Keep the existing data snapshot; only construct editors for the current batch.
        rows, as_of = self._rows, self._as_of
        factory = lambda key, name, parent: self._make_editor(key, name, parent, rows, as_of)
        review = sum(bool('review' in rows[key][2].casefold() or rows[key][1] is None or rows[key][0].get('fallback_kind')) for key, _ in entries)
        notice = (f'Loaded up to 10 cards from the bottom. VER2 balances as of {as_of:%B %d, %Y}. {review} name(s) in the first batch need review. '
                  'Unknown values print blank. VER1 fallbacks use an August opening; check their source and matched leave. WL for B/F rows is carried forward from August 2026.')
        PersonnelPrintQueue(self, entries, None, editor_factory=factory, notice=notice, tracker_scope=scope, next_batch_loader=load_batch).exec()


