from __future__ import annotations

from datetime import date
from html import escape
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Qt, QSignalBlocker, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from .ver2_balances import BALANCE_DATE, project_balance, resolve_balance_matches
from .ver2_database import normalized_name
from .philippine_holidays import HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR


def overview_rows(balances, people, records, links, holidays, as_of, source_links=None, wellness_by_id=None):
    """Show all imported balances; calculate only for unambiguous linked staff."""
    matches = resolve_balance_matches(balances, people, links)
    owner_by_source = {source: owner for owner, source in links.items()}
    manual_by_source = {source: name for name, source in (source_links or {}).items()}
    bis_names = {normalized_name(person.name) for person in people}
    result = []
    for source in balances:
        person, status = matches.get(source['key'], (None, 'Needs linking'))
        name_key = manual_by_source.get(source['key'])
        if person is None and source['key'] not in owner_by_source and name_key and name_key not in bis_names and records.get(name_key):
            person = SimpleNamespace(name=records[name_key][0]['name'], employee_number='', source_only=True)
            status = 'Manually linked imported name · no BIS ID · review'
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
                wl = (wellness_by_id or {}).get(str(getattr(person, 'employee_number', '') or '').strip(), set())
                estimate = project_balance(source, history, holidays, HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR, as_of, wl)
                if estimate['review']:
                    status += ' · Review conflicts or holidays'
                if not history:
                    status += ' · No matched leave; review'
                if source['vl'] is None or source['sl'] is None:
                    status += ' · Missing opening credit'
        result.append((source, person, status, estimate))
    return result


def parse_bis_clipboard_row(text):
    """Parse a single Excel TSV row or a pipe-separated row, preserving empty cells."""
    raw = str(text or '').strip('\r\n')
    if not raw or '\n' in raw or '\r' in raw:
        return None
    if '|' in raw:
        raw = raw.strip()
        if raw.startswith('|'):
            raw = raw[1:]
        if raw.endswith('|'):
            raw = raw[:-1]
        fields = raw.split('|')
    else:
        fields = raw.split('\t')
    fields = [part.strip() for part in fields]
    if len(fields) != 5 or not fields[0]:
        return None
    return fields


class Ver2BalanceOverview(QWidget):
    bis_personnel_added = Signal(object)

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
        add_bis = QPushButton('Add BIS / Link')
        add_bis.setToolTip('Add one verified employee to the local BIS list and link the selected balance row.')
        add_bis.clicked.connect(self._quick_add_bis)
        controls.addWidget(add_bis)
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
        unlinked = QPushButton('Print Unlinked Names')
        unlinked.setToolTip('Print all unlinked and possible-match spreadsheet names, including rows hidden by search.')
        unlinked.clicked.connect(self._print_unlinked_names)
        printing.addWidget(unlinked)
        export_unlinked = QPushButton('Export Unlinked XLS')
        export_unlinked.setToolTip('Save all unlinked and possible-match names to an Excel .xls file.')
        export_unlinked.clicked.connect(self._export_unlinked_names)
        printing.addWidget(export_unlinked)
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
        self.table.setHeaderLabels(['Employee name', 'Employee ID', 'Spreadsheet name', 'Opening VL', 'Opening SL', 'VL earned', 'SL earned', 'VL deducted', 'SL deducted', 'Remaining VL', 'Remaining SL', 'Status', 'Source', 'Printed'])
        self.table.setRootIsDecorated(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(11, 280)
        self.table.setColumnWidth(13, 170)
        self.table.itemDoubleClicked.connect(lambda _item, column: self._open_selected() if column != 13 else None)
        self.table.itemChanged.connect(self._printed_changed)
        layout.addWidget(self.table, 1)

    def refresh_if_needed(self):
        if self._dirty:
            self.refresh()

    def refresh(self):
        self._dirty = False
        p = self.personnel
        links = p._balance_links.all() if p._balance_links is not None else {}
        self._print_as_of = date.today()
        from .print_tracker_store import is_printed_or_sent, load_statuses
        print_statuses = load_statuses(f'ver2-balance:{self._print_as_of:%Y-%m-%d}')
        name_links = p._balance_links.source_links() if p._balance_links is not None else {}
        repository = getattr(self.window(), 'repository', None)
        try:
            from .ver2_simple_balances import wellness_days_by_employee
            wellness = wellness_days_by_employee(repository.leave_records(), self._print_as_of) if repository is not None else {}
        except Exception:
            wellness = {}
        rows = overview_rows(p._balance_rows, p._people, p._records, links, p._regular_holidays, self._print_as_of, name_links, wellness)
        self._print_rows = {source['key']: (source, person, status, estimate) for source, person, status, estimate in rows}
        self.table.setUpdatesEnabled(False)
        blocker = QSignalBlocker(self.table)
        self.table.clear()
        def fmt(value):
            return f'{value:.3f}' if value is not None else '—'
        for source, person, status, estimate in rows:
            values = [person.name if person else source['name'], (person.employee_number or '—') if person else '—', source['name'],
                      fmt(source['vl']), fmt(source['sl']),
                      fmt(estimate['earned_vl']) if estimate else '—', fmt(estimate['earned_sl']) if estimate else '—',
                      fmt(estimate['used_vl']) if estimate else '—', fmt(estimate['used_sl']) if estimate else '—',
                      fmt(estimate['vl']) if estimate else '—', fmt(estimate['sl']) if estimate else '—', status,
                      f"{Path(source['path']).name} · {source['sheet']} · row {source['row']}",
                      print_statuses.get(str(source['key']), 'Not confirmed')]
            item = QTreeWidgetItem(values)
            if not person:
                item.setToolTip(0, 'No employee match: showing the spreadsheet name.')
            item.setData(0, Qt.ItemDataRole.UserRole, person.employee_number if person else '')
            item.setData(0, Qt.ItemDataRole.UserRole + 1, source['key'])
            item.setData(0, Qt.ItemDataRole.UserRole + 2, status.startswith('Possible name match'))
            item.setCheckState(13, Qt.CheckState.Checked if is_printed_or_sent(print_statuses.get(str(source['key']))) else Qt.CheckState.Unchecked)
            item.setToolTip(13, 'Sent to printer is automatic; it does not confirm the physical card printed. Uncheck cards needing a reprint.')
            if status.startswith('Possible name match'):
                for column in range(len(values)):
                    item.setBackground(column, QBrush(QColor('#f8c9dd')))
                    item.setForeground(column, QBrush(QColor('#25202a')))
            self.table.addTopLevelItem(item)
        del blocker
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

    def _quick_add_bis(self, selected_row=None):
        # Qt's clicked signal may supply a boolean instead of a selected row.
        if not isinstance(selected_row, tuple):
            item = self.table.currentItem()
            if item is None or not item.isSelected() or item.isHidden():
                QMessageBox.information(self, 'Add BIS / Link', 'Select the brought-forward balance row first.')
                return
            key = item.data(0, Qt.ItemDataRole.UserRole + 1)
            selected_row = self._print_rows[key]
        source, person, _status, _estimate = selected_row
        key = source['key']
        if source.get('fallback_kind') or not source.get('path'):
            QMessageBox.information(self, 'Add BIS / Link', 'Select the actual brought-forward balance row first. This entry has no brought-forward row to link.')
            return
        if person and person.employee_number and not getattr(person, 'ver1_only', False):
            QMessageBox.information(self, 'Add BIS / Link', 'This balance already matches a BIS employee. Review the existing match first.')
            return
        repository = getattr(self.window(), 'repository', None)
        if repository is None or not hasattr(repository, 'add_bis_personnel'):
            QMessageBox.warning(self, 'Add BIS / Link', 'The local BIS database is not available.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Add BIS employee and link balance')
        form = QFormLayout(dialog)
        note = QLabel(f"Balance row: {source['name']} · {Path(source['path']).name} row {source['row']}\nEnter the verified BIS details for this same person. This updates the app, not the Excel file.")
        note.setWordWrap(True)
        form.addRow(note)
        name = QLineEdit(source.get('proposed_name') or (person.name if person else source['name']))
        employee_id = QLineEdit()
        employee_id.setPlaceholderText('Actual BIS employee number')
        rank = QLineEdit()
        office = QLineEdit()
        gender = QLineEdit()
        paste = QPlainTextEdit()
        paste.setPlaceholderText('Paste Excel row: Employee, Rank, employee_number, badge_id, office')
        paste.setMaximumHeight(65)
        parse_button = QPushButton('Fill fields from pasted row')
        badge_id = QLineEdit()
        badge_id.setReadOnly(True)
        badge_id.setPlaceholderText('Reference only; not saved by this form')
        badge_id.setToolTip('Badge ID is shown for reference. Only the employee number is saved.')
        def parse_row(show_error=False):
            fields = parse_bis_clipboard_row(paste.toPlainText())
            if fields is None:
                if show_error:
                    QMessageBox.warning(dialog, 'Paste BIS row', 'Paste one Excel row with five columns: Employee, Rank, employee_number, badge_id, office.')
                return
            name.setText(' '.join(fields[0].split()))
            rank.setText(fields[1])
            employee_id.setText(fields[2])
            badge_id.setText(fields[3])
            office.setText(fields[4])
        parse_button.clicked.connect(lambda: parse_row(True))
        paste.textChanged.connect(parse_row)
        form.addRow('Paste BIS row', paste)
        form.addRow(parse_button)
        form.addRow('Badge ID (reference only)', badge_id)
        form.addRow('Full BIS name *', name)
        form.addRow('BIS employee number *', employee_id)
        form.addRow('Rank', rank)
        form.addRow('Office', office)
        form.addRow('Gender', gender)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        employee_id.setFocus()
        while dialog.exec() == QDialog.DialogCode.Accepted:
            bis_name, bis_id = name.text().strip(), employee_id.text().strip()
            if not bis_name or not bis_id:
                QMessageBox.warning(self, 'Add BIS / Link', 'Enter the full name and actual BIS employee number.')
                continue
            existing_name_link = next((n for n, source_key in self.personnel._balance_links.source_links().items() if source_key == key), None)
            if existing_name_link and existing_name_link != normalized_name(bis_name):
                QMessageBox.warning(self, 'Add BIS / Link', 'This balance has a manual link to a different imported name. Review or remove that link first.')
                continue
            try:
                repository.add_bis_personnel(bis_id, bis_name, rank.text(), gender.text(), office.text())
            except Exception as error:
                QMessageBox.warning(self, 'Add BIS / Link', str(error))
                continue
            link_error = None
            try:
                self.personnel._balance_links.assign_new_bis(bis_id, key, bis_name)
            except Exception as error:
                link_error = str(error)
            people = repository.bis_personnel()
            self.bis_personnel_added.emit(people)
            self.refresh()
            if link_error:
                QMessageBox.warning(self, 'BIS employee added', f'The BIS employee was saved, but the balance could not be linked: {link_error}\nUse Link Balance to review the records.')
            else:
                QMessageBox.information(self, 'BIS employee added', 'The BIS employee was added and linked to this balance. The original Excel list was not changed.')
            return

    def _refresh_print_tracking(self):
        from .print_tracker_store import is_printed_or_sent, load_statuses
        statuses = load_statuses(f'ver2-balance:{self._print_as_of:%Y-%m-%d}')
        blocker = QSignalBlocker(self.table)
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            key = item.data(0, Qt.ItemDataRole.UserRole + 1)
            item.setText(13, statuses.get(str(key), 'Not confirmed'))
            item.setCheckState(13, Qt.CheckState.Checked if is_printed_or_sent(statuses.get(str(key))) else Qt.CheckState.Unchecked)
        del blocker

    def _printed_changed(self, item, column):
        if column != 13 or self._print_as_of is None:
            return
        from .print_tracker_store import save_status
        key = item.data(0, Qt.ItemDataRole.UserRole + 1)
        status = 'Confirmed printed' if item.checkState(13) == Qt.CheckState.Checked else 'Not confirmed'
        try:
            save_status(f'ver2-balance:{self._print_as_of:%Y-%m-%d}', key, status)
        except Exception as error:
            QMessageBox.warning(self, 'Printed status', f'Could not save this status: {error}')
            self._refresh_print_tracking()
            return
        blocker = QSignalBlocker(self.table)
        item.setText(13, status)
        del blocker

    def _selected_print_key(self):
        item = self.table.currentItem()
        if not item or not item.isSelected() or item.isHidden():
            QMessageBox.information(self, 'VER2 Printing', 'Select a visible balance row first.')
            return None
        return item.data(0, Qt.ItemDataRole.UserRole + 1)

    def _make_print_editor(self, key, parent=None):
        return self._print_helper._make_editor(key, parent=parent or self,
                                               rows=self._print_rows, as_of=self._print_as_of)

    def _unlinked_candidates(self):
        # Include unresolved rows and tentative matches that still need review.
        candidates = []
        for source, person, status, _estimate in self._print_rows.values():
            if person is None or status.startswith('Possible name match'):
                proposed = person.name if person else (source.get('proposed_name') or '')
                candidates.append((source['name'], proposed, status,
                                   f"{Path(source['path']).name} · {source['sheet']} · row {source['row']}"))
        candidates.sort(key=lambda row: (row[0].casefold(), row[3].casefold()))
        return candidates

    def _export_unlinked_names(self):
        from .unlinked_export import write_unlinked_xls
        candidates = self._unlinked_candidates()
        if not candidates:
            QMessageBox.information(self, 'Export unlinked names', 'There are no unlinked or unconfirmed names to export.')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export unlinked names', 'unlinked_names.xls', 'Excel 97–2003 Workbook (*.xls)')
        if not path:
            return
        if not Path(path).suffix:
            path += '.xls'
        elif Path(path).suffix.lower() != '.xls':
            QMessageBox.warning(self, 'Export unlinked names', 'Please use the .xls file extension.')
            return
        try:
            write_unlinked_xls(path, candidates)
        except Exception as error:
            QMessageBox.warning(self, 'Export unlinked names', f'Could not export the file: {error}')
            return
        QMessageBox.information(self, 'Export unlinked names', f'Exported {len(candidates)} rows to:\n{path}')

    def _print_unlinked_names(self):
        from PySide6.QtGui import QTextDocument, QPageSize
        from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog

        candidates = self._unlinked_candidates()
        if not candidates:
            QMessageBox.information(self, 'Print unlinked names', 'There are no unlinked or unconfirmed names to print.')
            return

        rows = ''.join(
            '<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>'.format(
                index, escape(str(name)), escape(str(proposed or '—')),
                escape(str(status)), escape(str(source)))
            for index, (name, proposed, status, source) in enumerate(candidates, 1)
        )
        document = QTextDocument(self)
        document.setHtml(
            '<h2>Unlinked and unconfirmed employee names</h2>'
            f'<p>Check Leave Balances · {self._print_as_of:%B %d, %Y} · {len(candidates)} rows</p>'
            '<p>Includes unresolved names and possible matches that need review. '
            'The report includes all rows, regardless of the search filter.</p>'
            '<table width="100%" border="1" cellspacing="0" cellpadding="5">'
            '<thead><tr><th>#</th><th>Spreadsheet name</th><th>Proposed employee</th>'
            '<th>Link status</th><th>Source</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>'
        )
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.Letter))
        dialog = QPrintPreviewDialog(printer, self)
        dialog.setWindowTitle(f'Unlinked Names · Print Preview ({len(candidates)} rows)')
        dialog.resize(1100, 800)
        dialog.paintRequested.connect(document.print_)
        dialog.exec()

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
        from .print_tracker_store import is_printed_or_sent, load_statuses
        scope = f'ver2-balance:{self._print_as_of:%Y-%m-%d}'
        selected = {item.data(0, Qt.ItemDataRole.UserRole + 1) for item in self.table.selectedItems() if not item.isHidden()}
        use_unprinted = resume or not selected
        remaining = iter(range(self.table.topLevelItemCount() - 1, -1, -1))
        def load_batch():
            statuses = load_statuses(scope) if use_unprinted else {}
            batch = []
            for index in remaining:
                item = self.table.topLevelItem(index)
                key = item.data(0, Qt.ItemDataRole.UserRole + 1)
                if not item.isHidden() and ((use_unprinted and not is_printed_or_sent(statuses.get(str(key)))) or (not use_unprinted and key in selected)):
                    batch.append((key, item.text(0)))
                    if len(batch) == 10:
                        break
            return batch
        entries = load_batch()
        if not entries:
            QMessageBox.information(self, 'VER2 Print Queue', 'No visible unprinted names to queue.' if use_unprinted else 'No visible rows selected.')
            return
        rows, as_of = self._print_rows, self._print_as_of
        factory = lambda key, name, parent: self._print_helper._make_editor(key, name, parent, rows, as_of)
        review = sum(bool('review' in rows[key][2].casefold() or rows[key][1] is None) for key, _ in entries)
        notice = (f'Loaded up to 10 cards from the bottom. Check Leave Balances values through {as_of:%B %d, %Y}. '
                  f'{review} row(s) in the first batch need review. Unknown values print blank; '
                  'WL is carried forward from August 2026.')
        PersonnelPrintQueue(self, entries, None, editor_factory=factory, notice=notice, tracker_scope=scope, next_batch_loader=load_batch).exec()
        self._refresh_print_tracking()

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
        question = (f"Is this the same employee?\n\nCredits: {item.text(2)}\n"
                    f"Personnel: {item.text(0)} ({item.text(1)})")
        if QMessageBox.question(self, 'Confirm name match', question) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.personnel._balance_links.assign(item.data(0, Qt.ItemDataRole.UserRole),
                                                 item.data(0, Qt.ItemDataRole.UserRole + 1))
        except Exception as error:
            QMessageBox.warning(self, 'Confirm name match', str(error))
            return
        self.refresh()


