from __future__ import annotations

import calendar
import csv
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt, QDate, QItemSelectionModel
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDateEdit, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QHeaderView, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QSplitter, QVBoxLayout, QWidget)

from .ver2_balance_overview import overview_rows
from .ver2_balance_list import include_personnel_and_mone
from .ver2_print_fields import ver2_print_fields
from .ver2_database import normalized_name
from .ver2_balances import resolve_balance_matches, wellness_priority_records
from .rules import normalize_leave_type
from .ver2_credit import allocate_unique_estimates
from .philippine_holidays import HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR


def wellness_days_by_employee(records, as_of):
    """Collect unique approved VER1 wellness dates after the opening balance."""
    days_by_employee = {}
    for record in records:
        if normalize_leave_type(record.leave_type) != 'Wellness Leave':
            continue
        if str(record.status or '').strip().upper() not in {'A', 'APPROVED'}:
            continue
        employee_id = str(record.employee_id or '').strip()
        if not employee_id:
            continue
        start = max(record.start, date(2026, 9, 1))
        end = min(record.end, as_of, date(2026, 12, 31))
        if start <= end:
            days = days_by_employee.setdefault(employee_id, set())
            days.update(start + timedelta(days=offset) for offset in range((end - start).days + 1))
    return days_by_employee


def web_export_rows(rows, as_of, updated_at):
    """Export the values shown for every balance row, including unavailable rows."""
    within_year = as_of.year == 2026 and as_of >= date(2026, 8, 31)
    result = []
    for source, person, status, estimate in rows:
        employee_id = str(getattr(person, 'employee_number', '') or '').strip() if person else ''
        name = person.name if person else source.get('name', '')
        values = [(estimate.get(key) if estimate else None) for key in ('vl', 'sl', 'fl')]
        values += [source.get('wl_current') if person and within_year else None]
        values += [estimate.get('spl') if estimate else None]
        # Match the displayed precision, and preserve a blank for unavailable values.
        formatted = [('' if value is None else (f'{value:.3f}' if index < 2 else f'{value:.0f}'))
                     for index, value in enumerate(values)]
        result.append([employee_id, name, as_of.isoformat(), *formatted, updated_at])
    return result


def balance_filter_flags(source, person, status, estimate):
    """Classify the existing balance row; categories may overlap."""
    status_text = str(status or '').casefold()
    fallback = source.get('fallback_kind')
    employee_id = str(getattr(person, 'employee_number', '') or '').strip() if person else ''
    needs_link = (not person or not employee_id or bool(fallback) or
                  bool(getattr(person, 'ver1_only', False)) or
                  'needs linking' in status_text or 'linked employee unavailable' in status_text or
                  status_text.startswith('possible name match'))
    possible = status_text.startswith('possible name match')
    missing_opening = not fallback and any(source.get(key) is None for key in ('vl', 'sl', 'fl', 'wl', 'spl'))
    conflicts = bool(estimate and estimate.get('review')) or 'conflicts or holiday' in status_text
    no_leave = 'no matched leave' in status_text or 'no matched ver2 leave' in status_text
    flags = set()
    if needs_link:
        flags.add('link')
    if possible:
        flags.add('possible')
    if missing_opening:
        flags.add('missing')
    if conflicts:
        flags.add('conflicts')
    if fallback == 'mone':
        flags.add('fallback')
    if no_leave:
        flags.add('no_leave')
    if estimate and estimate.get('auto_resolutions'):
        flags.add('auto')
    if flags or 'review' in status_text or 'unavailable' in status_text:
        flags.add('attention')
    return flags


def balance_conflict_details(history, holidays, as_of, automatic=()):
    """Reproduce the balance calculation's review flags and show the source rows."""
    if as_of < date(2026, 8, 31):
        return 'The selected date is before the brought-forward balance.'
    eligible = []
    originals = {}
    for row in history:
        status = str(row.get('status') or '').strip().upper()
        if status not in {'', 'A', 'APPROVED'}:
            continue
        start = max(date.fromisoformat(row['start_date']), date(2026, 9, 1))
        end = min(date.fromisoformat(row['end_date']), as_of)
        if start <= end:
            originals[row['record_key']] = row
            clipped = dict(row, start_date=start.isoformat(), end_date=end.isoformat())
            if not status:
                clipped['status'] = 'A'
            eligible.append(clipped)
    allocations = allocate_unique_estimates(eligible, holidays, HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR)
    days = sorted({day for item in allocations.values() for day in item['conflicts']})
    lines = ['The calculation checks approved VER2 leave after August 31, 2026, through the selected date.',
             'A blank status is treated as approved. Only chargeable overlapping dates are flagged.']

    def row_description(row):
        row = originals[row['record_key']]
        source_path = str(row.get('source_path') or '')
        source_name = Path(source_path.replace('\\', '/')).name if source_path else 'Unknown file'
        return (f"  • {row.get('leave_type', '?')} · {row['start_date']} to {row['end_date']} "
                f"· {source_name} · {row.get('source_sheet') or 'Unknown sheet'} "
                f"· row {row.get('source_row') or 'unknown'}")

    auto_by_day = {item[0]: item for item in automatic}
    if days:
        lines.extend(['', 'OVERLAPPING LEAVE DATES'])
        for day in days:
            decision = auto_by_day.get(day)
            if decision:
                suffix = f' (SL before: {decision[2]})' if decision[2] is not None else ''
                lines.append(f'{day:%B %d, %Y}: automatically charged to {decision[1]}{suffix}.')
            else:
                lines.append(f'{day:%B %d, %Y}: needs review.')
            for row in eligible:
                if day in allocations[row['record_key']]['conflicts']:
                    lines.append(row_description(row))
    unavailable = [row for row in eligible if allocations[row['record_key']]['unavailable']]
    if unavailable:
        lines.extend(['', 'HOLIDAY DATA UNAVAILABLE OR OVERLAPPING AN UNAUDITABLE RANGE',
                      f'The current holiday data covers {HOLIDAY_MIN_YEAR}–{HOLIDAY_MAX_YEAR}.'])
        lines.extend(row_description(row) for row in unavailable)
    excluded = [(row, day) for row in eligible for day in row.get('excluded_dates', ())
                if row['start_date'] <= day <= row['end_date']]
    if excluded:
        lines.extend(['', 'MANUALLY EXCLUDED DATES'])
        for row, day in excluded:
            lines.append(day + ':')
            lines.append(row_description(row))
    if not days and not unavailable:
        lines.extend(['', 'No unresolved conflict or unavailable holiday range was found.'])
    lines.extend(['', 'Review the original source records before changing or removing any leave.'])
    return '\n'.join(lines)


def conflict_date_choices(history, holidays, as_of):
    """Return original conflicting row/date pairs plus saved exclusions for review."""
    eligible = []
    originals = {}
    for row in history:
        status = str(row.get('status') or '').strip().upper()
        if status not in {'', 'A', 'APPROVED'}:
            continue
        start = max(date.fromisoformat(row['start_date']), date(2026, 9, 1))
        end = min(date.fromisoformat(row['end_date']), as_of)
        if start <= end:
            originals[row['record_key']] = row
            clipped = dict(row, start_date=start.isoformat(), end_date=end.isoformat(),
                           status=status or 'A', excluded_dates=[])
            eligible.append(clipped)
    allocations = allocate_unique_estimates(eligible, holidays, HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR)
    choices = []
    for row in eligible:
        original = originals[row['record_key']]
        excluded = set(original.get('excluded_dates', ()))
        flagged = {day.isoformat() for day in allocations[row['record_key']]['conflicts']}
        flagged.update(day for day in excluded if row['start_date'] <= day <= row['end_date'])
        for day in sorted(flagged):
            choices.append((day, original, day not in excluded))
    return sorted(choices, key=lambda item: (item[0], str(item[1].get('leave_type', '')), item[1]['record_key']))


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
    if person and source.get('wl') is not None and as_of.year == 2026 and as_of >= date(2026, 8, 31):
        if source.get('wl_current') is None:
            lines.append('Wellness leave: saved VER1 history could not be checked.')
            issues.append('Check the employee number and local leave history, then refresh.')
        else:
            lines.append(f"Wellness leave: opening {source['wl']} − {source.get('wl_days_used', 0)} approved calendar day(s) in saved VER1 history = {source['wl_current']}.")
            if not source.get('_wellness_dates'):
                issues.append('No later approved wellness days matched this employee number in saved VER1 history. Verify the ID and history if leave is missing.')
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
    if estimate and estimate.get('auto_resolutions'):
        lines.extend(['', 'AUTOMATIC OVERLAP CHOICES'])
        for day, kind, before in estimate['auto_resolutions']:
            suffix = f' · SL before: {before}' if before is not None else ''
            lines.append(f'{day:%B %d, %Y}: charged to {kind}{suffix}.')
        issues.append('Overlaps were assigned using the priority rules. Check cancellation records and use Show conflict details to review.')
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
        filter_controls = QHBoxLayout()
        filter_controls.addWidget(QLabel('Show'))
        self.status_filter = QComboBox()
        for label, value in [
            ('All records', 'all'),
            ('Needs attention', 'attention'),
            ('Needs linking / balance source', 'link'),
            ('Possible name match', 'possible'),
            ('Missing opening values', 'missing'),
            ('Conflicts / holiday review', 'conflicts'),
            ('Automatically resolved overlaps', 'auto'),
            ('VER1 fallback', 'fallback'),
            ('No matched VER2 leave', 'no_leave'),
        ]:
            self.status_filter.addItem(label, value)
        self.status_filter.setToolTip(
            'Categories can overlap. Needs linking includes missing BIS IDs and records without a brought-forward balance. '
            'No matched leave is a prompt to check, not proof that leave is missing.')
        filter_controls.addWidget(self.status_filter, 1)
        self.filter_count = QLabel('')
        filter_controls.addWidget(self.filter_count)
        left_layout.addLayout(filter_controls)
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
        self.status_filter.currentIndexChanged.connect(self._filter)
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
        try:
            if repository is None:
                raise RuntimeError('Local leave history is unavailable')
            wellness_days = wellness_days_by_employee(repository.leave_records(), as_of)
        except Exception:
            wellness_days = None
            message += ' · Wellness leave history could not be loaded'
        rows = overview_rows(p._balance_rows, match_people, p._records, links, p._regular_holidays, as_of, name_links, wellness_days)
        try:
            matched_ids = {person.employee_number for _, person, _, _ in rows if person}
            missing_ids = {person.employee_number for person in people if person.employee_number not in matched_ids}
            overrides = repository.mone_balance_fallbacks(missing_ids) if repository is not None else {}
        except Exception:
            overrides = {}
            message = ' · MONE balances could not be loaded'
        rows, covered = include_personnel_and_mone(rows, people, overrides, p._records, p._regular_holidays, as_of, wellness_days)
        updated_rows = []
        mone_database = getattr(self, 'exclusion_database', None)
        mone_by_id = {}
        mone_failed = False
        id_counts = Counter(mone_database._mone_id(getattr(person, 'employee_number', '')) for _, person, _, _ in rows if person) if mone_database else {}
        if mone_database is not None:
            try:
                for key, _start, _end, vl, sl in mone_database.mone_totals(as_of):
                    current = mone_by_id.setdefault(key, [0, 0])
                    current[0] += vl
                    current[1] += sl
            except Exception:
                mone_failed = True
                message += ' · Desktop MONE totals could not be loaded; VL and SL unavailable'
        for source, person, status, estimate in rows:
            source = dict(source)
            employee_id = str(getattr(person, 'employee_number', '') or '').strip() if person else ''
            if estimate and employee_id and mone_database is not None:
                debit = mone_by_id.get(mone_database._mone_id(employee_id), (0, 0))
                if mone_failed or (any(debit) and id_counts.get(mone_database._mone_id(employee_id), 0) != 1):
                    estimate = dict(estimate)
                    estimate['vl'] = estimate['sl'] = None
                    status = str(status) + ' · Desktop MONE needs review'
                elif any(debit):
                    estimate = dict(estimate)
                    for field, amount in zip(('vl', 'sl'), debit):
                        if estimate.get(field) is not None:
                            estimate[field] = round(estimate[field] - amount / 1000, 3)
                    source['desktop_mone_vl'] = debit[0] / 1000
                    source['desktop_mone_sl'] = debit[1] / 1000
            source['wl_current'] = None
            source['_wellness_dates'] = wellness_days.get(employee_id, set()) if wellness_days is not None else set()
            if (wellness_days is not None and employee_id and source.get('wl') is not None
                    and as_of.year == 2026 and as_of >= date(2026, 8, 31)
                    and estimate and not estimate.get('review')):
                used = estimate.get('used_wl', 0)
                source['wl_days_used'] = used
                source['wl_current'] = source['wl'] - used
            updated_rows.append((source, person, status, estimate))
        rows = updated_rows
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
            item.setToolTip(str(status))
            self.names.addItem(item)
            if source['key'] == selected_key:
                selected = item
        self.names.blockSignals(False)
        self._filter(preferred=selected)

    def _filter(self, *_args, preferred=None):
        query = ' '.join(self.search.text().split()).casefold()
        category = self.status_filter.currentData() or 'all'
        first = None
        visible = 0
        for index in range(self.names.count()):
            item = self.names.item(index)
            name = ' '.join(item.text().split()).casefold()
            row = self._rows.get(item.data(Qt.ItemDataRole.UserRole))
            flags = balance_filter_flags(*row) if row else set()
            item.setHidden(query not in name or (category != 'all' and category not in flags))
            if not item.isHidden():
                visible += 1
            if not item.isHidden() and first is None:
                first = item
        self.filter_count.setText(f'{visible} shown')
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
            'WL': source.get('wl_current') if person and within_year else None,
        }
        for label, value in balances.items():
            text = (f'{value:.0f}' if label in {'FL', 'SPL', 'WL'} else f'{value:.3f}') if value is not None else '—'
            self.values[label].setText(text)
            self.values[label].setToolTip(f'Exact balance: {value:.3f}' if value is not None and label in {'FL', 'SPL', 'WL'} else '')
        note = ('Opening balances: August 31, 2026. VL and SL earn 1.250 each per completed month; VL, SL, FL and SPL reflect imported leave. '
                'WL deducts approved calendar days in saved VER1 leave history matched by employee number. '
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
        if estimate and estimate.get('auto_resolutions'):
            note = (f"{len(estimate['auto_resolutions'])} overlap day(s) automatically assigned using the leave priority rules. "
                    'Use Troubleshoot to review or override.\n' + note)
        if source.get('desktop_mone_vl') or source.get('desktop_mone_sl'):
            note += f"\nDesktop MONE deducted: VL {source.get('desktop_mone_vl', 0):g}; SL {source.get('desktop_mone_sl', 0):g}."
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
        warning = (f'Export {len(exported)} balance rows as of {export_date:%B %d, %Y}?\n\n'
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
        history = list(self.personnel._records.get(normalized_name(person.name), [])) if person else []
        history += wellness_priority_records(source.get('_wellness_dates', set()))
        has_saved_exclusions = any(row.get('excluded_dates') for row in history)
        conflict_button = dialog.addButton('Show conflict details', QMessageBox.ButtonRole.ActionRole) if (estimate and (estimate.get('review') or estimate.get('auto_resolutions'))) or has_saved_exclusions else None
        dialog.exec()
        if add_button is not None and dialog.clickedButton() == add_button:
            self._add_bis_selected()
        elif link_button is not None and dialog.clickedButton() == link_button:
            self._link_existing_bis(row)
        elif card_button is not None and dialog.clickedButton() == card_button:
            self._view_fallback_card(person)
        elif conflict_button is not None and dialog.clickedButton() == conflict_button:
            details = balance_conflict_details(history, self.personnel._regular_holidays, self._as_of,
                                               estimate.get('auto_resolutions', ()) if estimate else ())
            choices = conflict_date_choices(history, self.personnel._regular_holidays, self._as_of)
            review = QDialog(self)
            review.setWindowTitle('Conflicting leave details')
            review.resize(1000, 720)
            review_layout = QVBoxLayout(review)
            heading = QLabel(f"{person.name if person else source.get('name', '')} · as of {self._as_of:%B %d, %Y}")
            heading.setWordWrap(True)
            review_layout.addWidget(heading)
            detail_text = QPlainTextEdit()
            detail_text.setReadOnly(True)
            detail_text.setPlainText(details)
            review_layout.addWidget(detail_text, 1)
            if choices:
                hint = QLabel('Tick a row to include that date; untick it to exclude that date from that leave record. '
                              'Wellness rows are read-only here and can be changed in VER1. '
                              'Verify the cancellation before choosing. You can change the selection later.')
                hint.setWordWrap(True)
                review_layout.addWidget(hint)
                choice_table = QTableWidget(len(choices), 4)
                choice_table.setHorizontalHeaderLabels(['Date', 'Leave', 'Source file / sheet / row', 'Count'])
                choice_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                choice_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
                for index, (day, record, included) in enumerate(choices):
                    path = str(record.get('source_path') or '').replace('\\', '/')
                    location = f"{Path(path).name or 'Unknown file'} · {record.get('source_sheet') or 'Unknown sheet'} · row {record.get('source_row') or 'unknown'}"
                    for column, value in enumerate((day, record.get('leave_type', ''), location)):
                        choice_table.setItem(index, column, QTableWidgetItem(str(value)))
                    check = QTableWidgetItem('')
                    check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    check.setCheckState(Qt.CheckState.Checked if included else Qt.CheckState.Unchecked)
                    if record.get('wellness_source'):
                        check.setFlags(check.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                        check.setToolTip('Wellness history is managed in VER1.')
                    choice_table.setItem(index, 3, check)
                review_layout.addWidget(choice_table, 1)
                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
                buttons.accepted.connect(review.accept)
            else:
                buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(review.reject)
            review_layout.addWidget(buttons)
            if review.exec() == QDialog.DialogCode.Accepted and choices:
                database = getattr(self, 'exclusion_database', None)
                if database is None:
                    QMessageBox.warning(self, 'Conflict review', 'The VER2 database is unavailable. No choices were saved.')
                    return
                changes = [(record['record_key'], day,
                            choice_table.item(index, 3).checkState() == Qt.CheckState.Checked)
                           for index, (day, record, _included) in enumerate(choices) if not record.get('wellness_source')]
                try:
                    database.set_date_inclusions(changes)
                    self.exclusions_updated()
                except Exception as error:
                    QMessageBox.warning(self, 'Conflict review', f'Could not update conflict choices: {error}')
                    return
                QMessageBox.information(self, 'Conflict review', 'Date choices saved. Balances have been recalculated.')

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




class Ver2BalanceTable(QWidget):
    """Review balances and edit locally recorded MONE totals by period."""

    def __init__(self, balance_page):
        super().__init__()
        self.balance_page = balance_page
        self._loading = False
        self._names, self._row_info = [], []
        layout = QVBoxLayout(self)
        title = QLabel('Leave Balance · Table Type')
        title.setStyleSheet('font-size: 20pt; font-weight: 800; color: #f1e3c1;')
        layout.addWidget(title)
        controls = QHBoxLayout()
        controls.addWidget(QLabel('As of the end of'))
        self.month = QComboBox()
        for number in range(1, 13):
            self.month.addItem(calendar.month_name[number], number)
        self.month.setCurrentIndex(balance_page.month.currentIndex())
        self.year = QSpinBox(); self.year.setRange(2026, 2100); self.year.setValue(balance_page.year.value())
        controls.addWidget(self.month); controls.addWidget(self.year)
        controls.addWidget(QLabel('MONE start'))
        self.mone_start = QDateEdit(QDate(2026, 11, 11)); self.mone_start.setCalendarPopup(True); self.mone_start.setDisplayFormat('MM/dd/yyyy')
        controls.addWidget(self.mone_start)
        controls.addWidget(QLabel('MONE end'))
        self.mone_end = QDateEdit(QDate(2026, 11, 20)); self.mone_end.setCalendarPopup(True); self.mone_end.setDisplayFormat('MM/dd/yyyy')
        controls.addWidget(self.mone_end)
        save_button = QPushButton('Save MONE for selected row'); save_button.clicked.connect(self._save_selected)
        controls.addWidget(save_button)
        controls.addStretch(1)
        refresh_button = QPushButton('Refresh'); refresh_button.clicked.connect(self.refresh); controls.addWidget(refresh_button)
        layout.addLayout(controls)
        self.search = QPlainTextEdit()
        self.search.setPlaceholderText('Paste or type names, one name per line. Partial names are accepted.')
        self.search.setMaximumHeight(120); self.search.setTabChangesFocus(True); layout.addWidget(self.search)
        self.status = QLabel(''); self.status.setWordWrap(True); layout.addWidget(self.status)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['NAME', 'VL', 'SL', 'FL', 'WL', 'SPL', 'MONE VL ✎', 'MONE SL ✎'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.SelectedClicked | QAbstractItemView.EditTrigger.EditKeyPressed | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader(); header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 8): header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False); layout.addWidget(self.table, 1)
        self.table.itemChanged.connect(self._draft_changed)
        self.table.cellClicked.connect(self._edit_mone_cell)
        self.search.textChanged.connect(self._filter)
        self.month.currentIndexChanged.connect(self.refresh); self.year.valueChanged.connect(self.refresh)
        self.mone_start.dateChanged.connect(self.refresh); self.mone_end.dateChanged.connect(self.refresh)

    def _period(self):
        return self.mone_start.date().toPython(), self.mone_end.date().toPython()

    def refresh(self, *_args):
        if self._loading: return
        self._loading = True
        try:
            year, month = self.year.value(), self.month.currentData()
            as_of = date(year, month, calendar.monthrange(year, month)[1])
            start, end = self._period()
            database = self.balance_page.exclusion_database
            rows, _covered, _count, message = self.balance_page._calculate_rows(as_of)
            values = web_export_rows(rows, as_of, '')
            totals = {key:(vl, sl) for key, first, last, vl, sl in database.mone_totals() if first == start.isoformat() and last == end.isoformat()}
            drafts = database.mone_drafts(start, end)
            id_counts = Counter(database._mone_id(data[0]) for data in values if database._mone_id(data[0]))
            self.table.setUpdatesEnabled(False); self.table.setRowCount(len(values))
            self._names, self._row_info = [], []
            for index, (data, detail) in enumerate(zip(values, rows)):
                source, person, status, estimate = detail
                name = str(data[1]) + ('  [VER1]' if person and getattr(person, 'ver1_only', False) else '')
                self._names.append(' '.join(name.split()).casefold())
                key = database._mone_id(data[0]); old = totals.get(key, (0, 0)); draft = drafts.get(key)
                can_edit = bool(key and id_counts[key] == 1 and estimate and estimate.get('vl') is not None and estimate.get('sl') is not None and start > date(2026, 8, 31) and start <= end and start <= as_of)
                self._row_info.append((data[0], old, draft, can_edit, estimate))
                mone_values = ([draft[0], draft[1]] if draft else [f'{old[0] / 1000:g}', f'{old[1] / 1000:g}']) if can_edit else ['—', '—']
                for column, value in enumerate([name, *data[3:8], *mone_values]):
                    item = QTableWidgetItem(str(value) if value != '' else '—'); item.setToolTip(str(status))
                    if column: item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if column < 6 or not can_edit: item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if column >= 6:
                        if can_edit:
                            item.setBackground(QColor('#31465a'))
                            item.setToolTip('Click to edit. Select this row and click Save MONE.' + (' Unsaved draft.' if draft else ''))
                        else:
                            item.setToolTip('Unavailable: needs a unique employee number, available VL and SL balances, and a valid MONE period.')
                    self.table.setItem(index, column, item)
            self._message = message
            self._filter()
        except Exception as error:
            self.status.setText(f'Could not load balances: {error}')
            QMessageBox.warning(self, 'Leave Balance · Table Type', str(error))
        finally:
            self.table.setUpdatesEnabled(True); self._loading = False

    def _edit_mone_cell(self, row, column):
        if not self._loading and column in (6, 7) and 0 <= row < len(self._row_info) and self._row_info[row][3]:
            item = self.table.item(row, column)
            if item is not None:
                self.table.editItem(item)

    def _draft_changed(self, item):
        if self._loading or item.column() not in (6, 7) or item.row() >= len(self._row_info): return
        row = item.row(); employee_id, old, draft, can_edit, _estimate = self._row_info[row]
        if not can_edit: return
        expected = (draft[2], draft[3]) if draft else old
        try:
            start, end = self._period()
            vl, sl = self.table.item(row, 6).text(), self.table.item(row, 7).text()
            self.balance_page.exclusion_database.save_mone_draft(employee_id, start, end, vl, sl, *expected)
            self._row_info[row] = (employee_id, old, (vl, sl, *expected), can_edit, _estimate)
            self.status.setText('MONE draft saved locally. Select the row and click Save MONE to apply it.')
        except Exception as error:
            QMessageBox.warning(self, 'MONE draft', str(error))

    def _save_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._row_info):
            QMessageBox.information(self, 'MONE', 'Select an employee row first.'); return
        employee_id, old, draft, can_edit, estimate = self._row_info[row]
        if not can_edit:
            QMessageBox.warning(self, 'MONE', 'A unique employee number, available VL and SL, and a valid period starting no later than the selected month are required.'); return
        try:
            database = self.balance_page.exclusion_database
            vl, sl = self.table.item(row, 6).text(), self.table.item(row, 7).text()
            new_vl, new_sl = database._mone_amount(vl), database._mone_amount(sl)
            expected = (draft[2], draft[3]) if draft else old
            if expected != old: raise ValueError('The saved MONE total changed. Refresh and review the draft.')
            if estimate['vl'] + (old[0] - new_vl) / 1000 < -0.000001 or estimate['sl'] + (old[1] - new_sl) / 1000 < -0.000001:
                raise ValueError('The MONE total exceeds the available leave balance.')
            if (new_vl, new_sl) == old:
                QMessageBox.information(self, 'MONE', 'MONE totals are unchanged.'); return
            name = self.table.item(row, 0).text()
            text = (f'Save MONE for {name}?\nVL: {old[0]/1000:g} → {new_vl/1000:g}\n'
                    f'SL: {old[1]/1000:g} → {new_sl/1000:g}\nOnly the difference will change the balance.')
            if QMessageBox.question(self, 'Save MONE', text) != QMessageBox.StandardButton.Yes: return
            start, end = self._period()
            database.save_mone_total(employee_id, start, end, vl, sl, *expected)
            self.balance_page.refresh()
            self.refresh()
        except Exception as error:
            QMessageBox.warning(self, 'MONE', str(error))

    def _filter(self):
        queries = [' '.join(line.split()).casefold() for line in self.search.toPlainText().splitlines() if line.strip()]
        visible = 0
        for index, name in enumerate(self._names):
            matched = not queries or any(query in name for query in queries)
            self.table.setRowHidden(index, not matched); visible += int(matched)
        self.status.setText(f'{visible} of {len(self._names)} records shown · Click a MONE cell to edit, then save the selected row · VL/SL are calculated; source balances stay unchanged.' + getattr(self, '_message', ''))
