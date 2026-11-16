from collections import Counter, defaultdict
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QHeaderView)

from .ver2_balances import resolve_balance_matches
from .ver2_database import normalized_name


def _id(person):
    return str(getattr(person, 'employee_number', '') or '').strip().casefold()


def _name_parts(name):
    name = normalized_name(name)
    if ',' not in name:
        return '', ''
    surname, given = name.split(',', 1)
    return surname.strip(), given.strip()


def _compatible(source_name, person_name):
    surname, given = _name_parts(source_name)
    other_surname, other_given = _name_parts(person_name)
    if not surname or surname != other_surname or not given or not other_given:
        return False
    # Require a complete given-name prefix, rather than guessing from an initial.
    first = given.split()[0].rstrip('.')
    if len(first) < 2 or first != other_given.split()[0].rstrip('.'):
        return False
    return given == other_given or given.startswith(other_given + ' ') or other_given.startswith(given + ' ')


def build_bulk_suggestions(rows, people, nhq_rows, links, name_links):
    """Suggest only unique, unclaimed matches; callers must confirm each link."""
    people = [p for p in people if _id(p) and normalized_name(p.name)]
    nhq = [SimpleNamespace(name=n, employee_number=e, rank=r, office=o, nhq=True)
           for n, e, r, o in nhq_rows if n and e]
    primary_ids = Counter(_id(p) for p in people)
    primary_names = Counter(normalized_name(p.name) for p in people)
    nhq_ids = Counter(_id(p) for p in nhq)
    nhq_names = Counter(normalized_name(p.name) for p in nhq)
    primary_by_surname, nhq_by_surname = defaultdict(list), defaultdict(list)
    for person in people:
        primary_by_surname[_name_parts(person.name)[0]].append(person)
    for person in nhq:
        nhq_by_surname[_name_parts(person.name)[0]].append(person)
    matches = resolve_balance_matches(rows, people, links)
    claimed = defaultdict(set)
    for key, (person, _status) in matches.items():
        claimed[_id(person)].add(key)
    for employee_id, key in links.items():
        claimed[str(employee_id).strip().casefold()].add(key)
    linked_sources = set(links.values())
    name_owner = {source: name for name, source in name_links.items()}
    output = []
    for row in rows:
        key = row['key']
        current = matches.get(key)
        if current and not str(current[1]).startswith('Possible name match'):
            continue
        raw_name = row.get('name', '')
        surname, _ = _name_parts(raw_name)
        primary = [p for p in primary_by_surname.get(surname, []) if _compatible(raw_name, p.name)]
        # Never fall back to NHQ if the primary list contains ambiguous candidates.
        pool = primary if primary else [p for p in nhq_by_surname.get(surname, []) if _compatible(raw_name, p.name)]
        reason, candidate = '', None
        if key in linked_sources:
            reason = 'Balance already has a saved employee link · review manually'
        elif not pool:
            reason = 'No matching name · review manually'
        elif len(pool) != 1:
            reason = f'{len(pool)} possible matches · review manually'
        else:
            p = pool[0]
            ident, name = _id(p), normalized_name(p.name)
            is_nhq = bool(getattr(p, 'nhq', False))
            duplicated = ((nhq_ids[ident] != 1 or nhq_names[name] != 1 or primary_ids[ident] or primary_names[name])
                          if is_nhq else (primary_ids[ident] != 1 or primary_names[name] != 1))
            if duplicated:
                reason = 'Duplicate name or employee number · review manually'
            elif row.get('proposed_name') and normalized_name(row['proposed_name']) != name:
                reason = 'Workbook match differs · review manually'
            elif claimed[ident] - {key}:
                reason = 'Employee already matches another balance · review manually'
            elif name_owner.get(key) and name_owner[key] != name:
                reason = 'Balance has a different name link · review manually'
            else:
                candidate = p
                reason = 'Exact name' if normalized_name(raw_name) == name else 'Short name · verify full name'
        output.append({'source': row, 'person': candidate, 'reason': reason})
    # The same person suggested for multiple rows is not unique.
    demand = Counter(_id(x['person']) for x in output if x['person'])
    for item in output:
        if item['person'] and demand[_id(item['person'])] > 1:
            item['person'] = None
            item['reason'] = 'Suggested for multiple balance rows · review manually'
    return output


class MatchTable(QTableWidget):
    """Extended row selection with keyboard and shift-click checkbox support."""

    def _selected_checks(self):
        return [self.item(index.row(), 0) for index in self.selectionModel().selectedRows()
                if not self.isRowHidden(index.row()) and self.item(index.row(), 0)
                and self.item(index.row(), 0).flags() & Qt.ItemFlag.ItemIsUserCheckable]

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            for item in self._selected_checks():
                item.setCheckState(Qt.CheckState.Checked)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.modifiers():
            checks = self._selected_checks()
            if checks:
                state = (Qt.CheckState.Unchecked if all(item.checkState() == Qt.CheckState.Checked for item in checks)
                         else Qt.CheckState.Checked)
                for item in checks:
                    item.setCheckState(state)
                event.accept()
                return
        super().keyPressEvent(event)


class BulkLinkDialog(QDialog):
    def __init__(self, parent, rows, repository, links, refresh):
        super().__init__(parent)
        self.rows, self.repository, self.links, self.refresh = rows, repository, links, refresh
        self.setWindowTitle('Cross-match unlinked balances')
        self.resize(1150, 650)
        layout = QVBoxLayout(self)
        note = QLabel('Review every suggested match. BIS is searched first; NHQ is used only when BIS has no name match. Shift-click checks a range; Ctrl-click selects individual rows; press Space to check or uncheck selected rows. No links are saved until you click Link selected.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search name, employee number, source or review status')
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        filters = QHBoxLayout()
        filters.addWidget(QLabel('Show:'))
        self.match_filter = QComboBox()
        self.match_filter.addItem('All unlinked rows', 'all')
        self.match_filter.addItem('With suggested full name', 'suggested')
        self.match_filter.addItem('Needs manual review', 'review')
        self.match_filter.currentIndexChanged.connect(self._filter)
        filters.addWidget(self.match_filter)
        filters.addStretch(1)
        layout.addLayout(filters)
        self.table = MatchTable(0, 6)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setHorizontalHeaderLabels(['Select', 'Brought-forward name', 'Suggested full name', 'Employee number', 'Source', 'Match / review'])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        controls = QHBoxLayout()
        select = QPushButton('Select visible suggestions')
        select.clicked.connect(lambda: self._select_all(True))
        clear = QPushButton('Clear all selections')
        clear.clicked.connect(lambda: self._select_all(False))
        save = QPushButton('Link selected')
        save.clicked.connect(self._save)
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        for button in (select, clear, save, close):
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self._reload()

    def _reload(self):
        try:
            people = self.repository.bis_personnel()
            self.items = build_bulk_suggestions(self.rows, people, self.links.nhq_lookup(), self.links.all(), self.links.source_links())
        except Exception as error:
            self.items = []
            QMessageBox.warning(self, 'Cross-match', f'Could not load the cross-match: {error}')
        self.table.setRowCount(len(self.items))
        for i, entry in enumerate(self.items):
            person = entry['person']
            check = QTableWidgetItem('')
            if person:
                check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
                check.setCheckState(Qt.CheckState.Unchecked)
            else:
                check.setFlags(Qt.ItemFlag.NoItemFlags)
            self.table.setItem(i, 0, check)
            values = [entry['source'].get('name', ''), person.name if person else '—',
                      str(person.employee_number) if person else '—',
                      ('NHQ' if getattr(person, 'nhq', False) else 'BIS') if person else '—', entry['reason']]
            for j, value in enumerate(values, 1):
                self.table.setItem(i, j, QTableWidgetItem(value))
        suggested = sum(1 for entry in self.items if entry['person'])
        self.summary.setText(f'{len(self.items)} unlinked rows · {suggested} suggestions · {len(self.items) - suggested} require manual review. Suggestions start unchecked.')
        self._filter()

    def _filter(self, *_):
        query = self.search.text().casefold().strip()
        mode = self.match_filter.currentData()
        for i in range(self.table.rowCount()):
            text = ' '.join(self.table.item(i, j).text() for j in range(1, 6) if self.table.item(i, j)).casefold()
            has_suggestion = bool(self.items[i]['person'])
            visible = query in text and (mode == 'all' or (mode == 'suggested' and has_suggestion) or (mode == 'review' and not has_suggestion))
            self.table.setRowHidden(i, not visible)

    def _select_all(self, checked):
        for i, entry in enumerate(self.items):
            if entry['person'] and (not checked or not self.table.isRowHidden(i)):
                self.table.item(i, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _save(self):
        selected = [entry for i, entry in enumerate(self.items)
                    if entry['person'] and self.table.item(i, 0).checkState() == Qt.CheckState.Checked]
        if not selected:
            QMessageBox.information(self, 'Cross-match', 'Select the reviewed matches to link first.')
            return
        hidden = sum(1 for i, entry in enumerate(self.items) if entry['person'] and self.table.isRowHidden(i) and self.table.item(i, 0).checkState() == Qt.CheckState.Checked)
        if QMessageBox.question(self, 'Confirm links', f'Link {len(selected)} checked employees to their balance rows ({hidden} currently hidden by search or filter)? Verify their full names and employee numbers before continuing.') != QMessageBox.StandardButton.Yes:
            return
        saved, failures = 0, []
        try:
            current = build_bulk_suggestions(self.rows, self.repository.bis_personnel(), self.links.nhq_lookup(), self.links.all(), self.links.source_links())
            fresh_by_key = {x['source']['key']: x for x in current}
        except Exception as error:
            QMessageBox.warning(self, 'Cross-match', f'Could not recheck the matches: {error}')
            return
        for entry in selected:
            source, person = entry['source'], entry['person']
            try:
                # Assignment checks enforce uniqueness even if links change after this preflight.
                fresh = fresh_by_key.get(source['key'])
                if not fresh or not fresh['person'] or _id(fresh['person']) != _id(person):
                    raise ValueError('Match changed or is no longer unique; review again.')
                if getattr(person, 'nhq', False):
                    self.repository.add_bis_personnel(person.employee_number, person.name, person.rank, '', person.office)
                self.links.assign_new_bis(person.employee_number, source['key'], person.name)
                saved += 1
            except Exception as error:
                failures.append(f"{source.get('name', '')}: {error}")
        self.refresh()
        self._reload()
        text = f'{saved} link(s) saved. Credits remain in the original brought-forward file.'
        if failures:
            text += f'\n\n{len(failures)} could not be linked:\n' + '\n'.join(failures[:15])
            if len(failures) > 15:
                text += f'\n... and {len(failures)-15} more.'
            text += '\nIf an NHQ person was added before a link failed, check the BIS list before retrying.'
        QMessageBox.information(self, 'Cross-match result', text)
