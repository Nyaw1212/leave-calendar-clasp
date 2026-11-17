from collections import Counter, defaultdict
from difflib import SequenceMatcher
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


def _ratio(left, right):
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def _review_similarity_parts(source_surname, source_given, other_surname, other_given):
    if not source_surname or not source_given or not other_surname or not other_given:
        return None
    surname_matcher = SequenceMatcher(None, source_surname, other_surname, autojunk=False)
    # Skip comparisons which cannot reach 70%, even with identical given names.
    if 0.55 * surname_matcher.quick_ratio() + 0.45 < 0.695:
        return None
    return round(100 * (0.55 * surname_matcher.ratio() +
                        0.45 * _ratio(' '.join(sorted(source_given.split())),
                                      ' '.join(sorted(other_given.split())))))


def _alternative_match(source_name, person_name):
    """Return a review-only matching pass and similarity, or None."""
    surname, given = _name_parts(source_name)
    other_surname, other_given = _name_parts(person_name)
    if not surname or not other_surname or not given or not other_given:
        return None
    words = [x.rstrip('.') for x in given.split() if len(x.rstrip('.')) >= 3]
    other_words = [x.rstrip('.') for x in other_given.split() if len(x.rstrip('.')) >= 3]
    if not words or not other_words:
        return None
    if surname == other_surname and set(words) & set(other_words):
        return (2, round(100 * _ratio(given, other_given)))
    if surname == other_surname:
        score = _ratio(words[0], other_words[0])
        if score >= 0.80:
            return (3, round(score * 100))
    if words[0] == other_words[0] and len(surname) >= 4 and len(other_surname) >= 4:
        score = _ratio(surname, other_surname)
        if score >= 0.85:
            return (4, round(score * 100))
    return None


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
        if (current and not str(current[1]).startswith('Possible name match')) or key in name_owner:
            continue
        raw_name = row.get('name', '')
        surname, _ = _name_parts(raw_name)
        primary = [p for p in primary_by_surname.get(surname, []) if _compatible(raw_name, p.name)]
        # Check strict matches in both sources before considering less certain passes.
        pool = primary if primary else [p for p in nhq_by_surname.get(surname, []) if _compatible(raw_name, p.name)]
        match_pass, match_scores = 1, {}
        if not pool:
            for pass_number in (2, 3, 4):
                def candidates(source, by_surname):
                    search = source if pass_number == 4 else by_surname.get(surname, [])
                    found = []
                    for person in search:
                        result = _alternative_match(raw_name, person.name)
                        if result and result[0] == pass_number:
                            found.append(person)
                            match_scores[id(person)] = result[1]
                    return found
                primary = candidates(people, primary_by_surname)
                pool = primary if primary else candidates(nhq, nhq_by_surname)
                if pool:
                    match_pass = pass_number
                    break
        if not pool:
            # Weaker scores are review suggestions only, never automatic links.
            # Compare both sources; collapse the same identity in BIS and NHQ.
            surname, given = _name_parts(raw_name)
            ranked = {}
            for person in people + nhq:
                other_surname, other_given = _name_parts(person.name)
                score = _review_similarity_parts(surname, given, other_surname, other_given)
                if score is None or score < 70:
                    continue
                identity = (_id(person), normalized_name(person.name))
                if identity not in ranked:
                    ranked[identity] = (person, score)
            if ranked:
                best = max(score for _, score in ranked.values())
                pool = [person for person, score in ranked.values() if score == best]
                for person in pool:
                    match_scores[id(person)] = best
                match_pass = 5
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
                if match_pass == 1:
                    reason = 'Pass 1: exact name' if normalized_name(raw_name) == name else 'Pass 1: short name · verify full name'
                elif match_pass == 2:
                    reason = f'Pass 2: shared given name ({match_scores[id(p)]}% given-name similarity) · verify full name'
                elif match_pass == 3:
                    reason = f'Pass 3: similar given name ({match_scores[id(p)]}%) · verify full name'
                elif match_pass == 4:
                    reason = f'Pass 4: similar surname ({match_scores[id(p)]}%) · verify full name'
                else:
                    reason = f'Pass 5: possible match ({match_scores[id(p)]}%) · verify full name and employee number'
        output.append({'source': row, 'person': candidate, 'reason': reason})
    # The same person suggested for multiple rows is not unique.
    demand = Counter(_id(x['person']) for x in output if x['person'])
    for item in output:
        if item['person'] and demand[_id(item['person'])] > 1:
            item['person'] = None
            item['reason'] = 'Suggested for multiple balance rows · review manually'
    return output


def build_leave_name_matches(rows, records, people, employee_links, name_links):
    """Only propose one-to-one name matches; never infer an employee number."""
    resolved = resolve_balance_matches(rows, people, employee_links)
    claimed_sources = set(employee_links.values()) | set(name_links.values()) | set(resolved)
    bis_names = {normalized_name(p.name) for p in people}
    candidates = {}
    for key, entries in records.items():
        relevant = [r for r in entries if str(r.get('leave_type', '')).strip().upper() in {'VL', 'SL', 'FL', 'SPL'}]
        if relevant and key not in bis_names and key not in name_links:
            candidates[key] = relevant
    results = []
    for row in rows:
        if row['key'] in claimed_sources:
            continue
        exact = [key for key in candidates if normalized_name(row.get('name', '')) == key]
        possible = exact or [key for key in candidates if _compatible(row.get('name', ''), candidates[key][0].get('name', ''))]
        if len(possible) != 1:
            continue
        key = possible[0]
        entries = candidates[key]
        results.append({'source':row, 'name_key':key, 'name':entries[0].get('name', ''),
                        'types':', '.join(sorted({str(e.get('leave_type','')).strip().upper() for e in entries})),
                        'count':len(entries), 'match':'Exact name' if exact else 'Short name — verify'})
    demand = Counter(item['name_key'] for item in results)
    return [item for item in results if demand[item['name_key']] == 1]


def manual_candidates(row, rows, people, nhq_rows, links, name_links):
    """Rank review candidates, marking anything that cannot safely be linked."""
    people = [p for p in people if _id(p) and normalized_name(p.name)]
    nhq = [SimpleNamespace(name=n, employee_number=e, rank=r, office=o, nhq=True)
           for n, e, r, o in nhq_rows if n and e]
    primary_ids = Counter(_id(p) for p in people)
    primary_names = Counter(normalized_name(p.name) for p in people)
    nhq_ids = Counter(_id(p) for p in nhq)
    nhq_names = Counter(normalized_name(p.name) for p in nhq)
    resolved = resolve_balance_matches(rows, people, links)
    key = row['key']
    claimed = defaultdict(set)
    for source_key, (person, _status) in resolved.items():
        claimed[_id(person)].add(source_key)
    for employee_id, source_key in links.items():
        claimed[str(employee_id).strip().casefold()].add(source_key)
    owner = next((name for name, source_key in name_links.items() if source_key == key), '')
    source_surname, source_given = _name_parts(row.get('name', ''))
    result = []
    for person in people + nhq:
        ident, name = _id(person), normalized_name(person.name)
        surname, given = _name_parts(person.name)
        if not source_surname or not source_given or not surname or not given:
            continue
        # Sorting given-name tokens allows for reordered given names.
        score = round(100 * (0.55 * _ratio(source_surname, surname) +
                             0.45 * _ratio(' '.join(sorted(source_given.split())),
                                           ' '.join(sorted(given.split())))))
        is_nhq = bool(getattr(person, 'nhq', False))
        duplicate = ((nhq_ids[ident] != 1 or nhq_names[name] != 1 or primary_ids[ident] or primary_names[name])
                     if is_nhq else (primary_ids[ident] != 1 or primary_names[name] != 1))
        current = resolved.get(key)
        reason = ''
        if duplicate:
            reason = 'Duplicate name or employee number'
        elif key in links.values():
            reason = 'Balance already has a saved link'
        elif current and not str(current[1]).startswith('Possible name match'):
            reason = 'Balance already matches an employee'
        elif claimed[ident] - {key}:
            reason = 'Employee already matches another balance'
        elif owner and owner != name:
            reason = 'Balance linked to a different imported name'
        result.append({'person': person, 'score': score, 'blocked': reason})
    result.sort(key=lambda item: (-item['score'], bool(item['blocked']),
                                  bool(getattr(item['person'], 'nhq', False)),
                                  normalized_name(item['person'].name), _id(item['person'])))
    return result


class CandidateDialog(QDialog):
    def __init__(self, parent, row, candidates):
        super().__init__(parent)
        self.setWindowTitle('Find possible matches')
        self.resize(950, 600)
        self.candidates = candidates
        layout = QVBoxLayout(self)
        workbook = row.get('proposed_name') or 'None'
        heading = QLabel(f"Brought-forward: {row.get('name', '')}\nWorkbook match: {workbook}\n"
                         'Similarity ranks names; it does not verify identity. Select a row and review the full name and employee number.')
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search candidate name, employee number or source')
        self.search.textChanged.connect(self._populate)
        layout.addWidget(self.search)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Similarity', 'Full name', 'Employee number', 'Source', 'Link status'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.info = QLabel('')
        layout.addWidget(self.info)
        controls = QHBoxLayout()
        choose = QPushButton('Review selected candidate')
        choose.clicked.connect(self._choose)
        close = QPushButton('Cancel')
        close.clicked.connect(self.reject)
        controls.addWidget(choose)
        controls.addWidget(close)
        controls.addStretch(1)
        layout.addLayout(controls)
        self._populate()

    def _populate(self, *_):
        query = self.search.text().strip().casefold()
        filtered = [c for c in self.candidates if query in ' '.join([
            str(c['person'].name), str(c['person'].employee_number),
            'Fallback' if getattr(c['person'], 'nhq', False) else 'BIS']).casefold()]
        self.shown = filtered[:50]
        self.table.setRowCount(len(self.shown))
        for i, candidate in enumerate(self.shown):
            person = candidate['person']
            values = [f"{candidate['score']}%", person.name, str(person.employee_number),
                      'Fallback' if getattr(person, 'nhq', False) else 'BIS', candidate['blocked'] or 'Available for review']
            for j, value in enumerate(values):
                self.table.setItem(i, j, QTableWidgetItem(value))
        self.info.setText(f'Showing {len(self.shown)} of {len(filtered)} candidates. Search to narrow the list.')

    def _choose(self):
        index = self.table.currentRow()
        if index < 0 or index >= len(self.shown):
            QMessageBox.information(self, 'Choose a candidate', 'Select one candidate first.')
            return
        candidate = self.shown[index]
        if candidate['blocked']:
            QMessageBox.warning(self, 'Cannot link', candidate['blocked'] + '. Review the existing records first.')
            return
        self.chosen = candidate
        self.accept()


class PossibleMatchesCombo(QComboBox):
    """Load ranked candidates on demand so opening the list stays responsive."""
    def __init__(self, parent, source_row):
        super().__init__(parent.table)
        self.dialog = parent
        self.source_row = source_row
        self.addItem('Show possible matches')
        self.setToolTip('Open to load the closest matches, ranked by similarity.')
        self.setMinimumWidth(260)
        self.activated.connect(self._selected)

    def showPopup(self):
        try:
            choices = self.dialog._candidate_list(self.source_row)
        except Exception as error:
            QMessageBox.warning(self.dialog, 'Possible matches', f'Could not load candidates: {error}')
            return
        self.blockSignals(True)
        self.clear()
        self.addItem('Select a possible match')
        for candidate in choices[:20]:
            person = candidate['person']
            source = 'Fallback' if getattr(person, 'nhq', False) else 'BIS'
            status = ' · unavailable: ' + candidate['blocked'] if candidate['blocked'] else ''
            self.addItem(f"{candidate['score']}% · {person.name} · {person.employee_number} · {source}{status}", candidate)
        if not choices:
            self.setItemText(0, 'No candidates available')
        self.blockSignals(False)
        super().showPopup()

    def _selected(self, index):
        candidate = self.itemData(index)
        self.setCurrentIndex(0)
        if candidate:
            if candidate['blocked']:
                QMessageBox.warning(self.dialog, 'Cannot link', candidate['blocked'] + '. Review the existing records first.')
                return
            self.dialog._confirm_manual_candidate(self.source_row, candidate)


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
        note = QLabel('Review every suggested match. Exact/short names are checked first, then name-order and spelling variations. BIS is preferred within each pass. Pass 5 suggests the highest score at 70% or more; check all matches carefully. Similarity is not proof of identity. Shift-click checks a range; Ctrl-click selects individual rows; press Space to check or uncheck selected rows. Checked suggestions are saved with Link selected; dropdown choices require individual confirmation.')
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
        self.table = MatchTable(0, 7)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setHorizontalHeaderLabels(['Select', 'Brought-forward name', 'Suggested full name', 'Employee number', 'Source', 'Match / review', 'Possible matches'])
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
        leave_match = QPushButton('Match VL / SL / FL / SPL')
        leave_match.clicked.connect(self._match_leave_names)
        find = QPushButton('Find possible matches')
        find.clicked.connect(self._find_possible_matches)
        close = QPushButton('Close')
        close.clicked.connect(self.close)
        for button in (select, clear, save, leave_match, find, close):
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self._reload()

    def _match_leave_names(self):
        records = getattr(getattr(self.parent(), 'personnel', None), '_records', {})
        if not records:
            QMessageBox.information(self, 'Match imported leave', 'Load the VL, SL, FL or SPL records first.')
            return
        try:
            items = build_leave_name_matches(self.rows, records, self.repository.bis_personnel(),
                                            self.links.all(), self.links.source_links())
        except Exception as error:
            QMessageBox.warning(self, 'Match imported leave', f'Could not find leave matches: {error}')
            return
        if not items:
            QMessageBox.information(self, 'Match imported leave', 'No unique unlinked name matches were found. Ambiguous names need individual review.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Review imported leave matches')
        dialog.resize(950, 600)
        layout = QVBoxLayout(dialog)
        note = QLabel('Check each name before linking. These are name-only links without an employee number; they are not verified employee identities. VL, SL, FL and SPL history can then be used in the balance calculation.')
        note.setWordWrap(True)
        layout.addWidget(note)
        table = MatchTable(len(items), 5)
        table.setHorizontalHeaderLabels(['Select', 'Brought-forward name', 'Imported leave name', 'Leave types', 'Match'])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        for index, item in enumerate(items):
            check = QTableWidgetItem('')
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Unchecked)
            table.setItem(index, 0, check)
            for column, value in enumerate((item['source']['name'], item['name'], item['types'], item['match']), 1):
                table.setItem(index, column, QTableWidgetItem(str(value)))
        layout.addWidget(table)
        controls = QHBoxLayout()
        select = QPushButton('Select all')
        select.clicked.connect(lambda: [table.item(i, 0).setCheckState(Qt.CheckState.Checked) for i in range(table.rowCount())])
        clear = QPushButton('Clear')
        clear.clicked.connect(lambda: [table.item(i, 0).setCheckState(Qt.CheckState.Unchecked) for i in range(table.rowCount())])
        save = QPushButton('Link selected names')
        cancel = QPushButton('Close')
        cancel.clicked.connect(dialog.reject)
        for button in (select, clear, save, cancel):
            controls.addWidget(button)
        layout.addLayout(controls)
        def commit():
            selected = [item for i, item in enumerate(items) if table.item(i, 0).checkState() == Qt.CheckState.Checked]
            if not selected:
                QMessageBox.information(dialog, 'Match imported leave', 'Select the matches you have reviewed.')
                return
            if QMessageBox.question(dialog, 'Confirm name links', f"Link {len(selected)} reviewed names to their brought-forward rows? These links do not verify an employee number.") != QMessageBox.StandardButton.Yes:
                return
            try:
                fresh = build_leave_name_matches(self.rows, records, self.repository.bis_personnel(),
                                                 self.links.all(), self.links.source_links())
                available = {(item['source']['key'], item['name_key']) for item in fresh}
            except Exception as error:
                QMessageBox.warning(dialog, 'Match imported leave', f'Could not recheck matches: {error}')
                return
            saved, failures = 0, []
            for item in selected:
                try:
                    if (item['source']['key'], item['name_key']) not in available:
                        raise ValueError('Match changed; review again.')
                    self.links.assign_source_unclaimed(item['name'], item['source']['key'])
                    saved += 1
                except Exception as error:
                    failures.append(item['source'].get('name', '') + ': ' + str(error))
            self.refresh()
            self._reload()
            message = f'{saved} name-only links saved. Employee numbers are still unverified.'
            if failures:
                message += f'\\n{len(failures)} could not be linked:\\n' + '\\n'.join(failures[:15])
            QMessageBox.information(dialog, 'Match imported leave', message)
            dialog.accept()
        save.clicked.connect(commit)
        dialog.exec()

    def _find_possible_matches(self):
        index = self.table.currentRow()
        if index < 0 or index >= len(self.items) or self.table.isRowHidden(index):
            QMessageBox.information(self, 'Find possible matches', 'Select a balance row first.')
            return
        row = self.items[index]['source']
        try:
            candidates = self._candidate_list(row)
        except Exception as error:
            QMessageBox.warning(self, 'Find possible matches', f'Could not load candidates: {error}')
            return
        dialog = CandidateDialog(self, row, candidates)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._confirm_manual_candidate(row, dialog.chosen)

    def _candidate_list(self, row):
        return manual_candidates(row, self.rows, self.repository.bis_personnel(),
            self.links.nhq_lookup(), self.links.all(), self.links.source_links())

    def _confirm_manual_candidate(self, row, candidate):
        person = candidate['person']
        source = 'Fallback' if getattr(person, 'nhq', False) else 'BIS'
        workbook = row.get('proposed_name') or 'None'
        message = (f"Link this balance to the selected employee?\n\nBalance: {row.get('name', '')}\n"
                   f"Workbook match: {workbook}\nSelected: {person.name}\n"
                   f"Employee number: {person.employee_number}\nSource: {source}\n\n"
                   'Confirm the employee identity before linking.')
        if QMessageBox.question(self, 'Confirm employee link', message) != QMessageBox.StandardButton.Yes:
            return
        try:
            fresh = manual_candidates(row, self.rows, self.repository.bis_personnel(),
                self.links.nhq_lookup(), self.links.all(), self.links.source_links())
            matches = [c for c in fresh if _id(c['person']) == _id(person)
                and normalized_name(c['person'].name) == normalized_name(person.name)
                and bool(getattr(c['person'], 'nhq', False)) == bool(getattr(person, 'nhq', False))]
            if len(matches) != 1 or matches[0]['blocked']:
                raise ValueError(matches[0]['blocked'] if len(matches) == 1 else 'Candidate changed or is no longer unique.')
            person = matches[0]['person']
            if getattr(person, 'nhq', False):
                self.repository.add_bis_personnel(person.employee_number, person.name, person.rank, '', person.office)
            self.links.assign_new_bis(person.employee_number, row['key'], person.name)
        except Exception as error:
            QMessageBox.warning(self, 'Link not completed', f'{error}\nIf a fallback employee was added before the failure, check BIS before retrying.')
            return
        self.refresh()
        self._reload()
        QMessageBox.information(self, 'Link saved', 'The employee was linked. Credits remain in the brought-forward file.')

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
                      ('Fallback' if getattr(person, 'nhq', False) else 'BIS') if person else '—', entry['reason']]
            for j, value in enumerate(values, 1):
                self.table.setItem(i, j, QTableWidgetItem(value))
            self.table.setCellWidget(i, 6, PossibleMatchesCombo(self, entry['source']))
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
            text += '\nIf a fallback person was added before a link failed, check the BIS list before retrying.'
        QMessageBox.information(self, 'Cross-match result', text)
