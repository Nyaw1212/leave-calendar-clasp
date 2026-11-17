from __future__ import annotations

import hashlib
import sqlite3
import calendar
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from collections import Counter, defaultdict

from .ver2_credit import allocate_unique_estimates
from .ver2_database import normalized_name


BALANCE_DATE = date(2026, 8, 31)


class BalanceLinks:
    def __init__(self, path: Path):
        self.path = path
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS ver2_balance_links (employee_id TEXT PRIMARY KEY, source_key TEXT NOT NULL UNIQUE)")
            connection.execute("CREATE TABLE IF NOT EXISTS ver2_name_balance_links (name_key TEXT PRIMARY KEY, source_key TEXT NOT NULL UNIQUE)")
            connection.execute("CREATE TABLE IF NOT EXISTS ver2_nhq_lookup (name TEXT NOT NULL, employee_id TEXT NOT NULL, rank TEXT NOT NULL, office TEXT NOT NULL)")
            connection.execute("""CREATE TABLE IF NOT EXISTS ver2_link_export_queue (
                employee_id TEXT PRIMARY KEY, source_key TEXT NOT NULL,
                linked_at TEXT NOT NULL, exported_at TEXT)""")

    def replace_nhq_lookup(self, rows):
        if not rows:
            raise ValueError('No usable NHQ rows with a name and employee number were found.')
        with sqlite3.connect(self.path) as connection:
            connection.execute('DELETE FROM ver2_nhq_lookup')
            connection.executemany('INSERT INTO ver2_nhq_lookup (name, employee_id, rank, office) VALUES (?, ?, ?, ?)', rows)

    def add_nhq_lookup(self, rows):
        """Add distinct fallback identities without replacing existing lookup rows."""
        if not rows:
            raise ValueError('No usable rows with a name and employee number were found.')
        def identity(row):
            name, employee_id = str(row[0]), str(row[1])
            return (normalized_name(name), ''.join(employee_id.casefold().split()).replace('-', ''))
        with sqlite3.connect(self.path) as connection:
            existing = connection.execute('SELECT name, employee_id, rank, office FROM ver2_nhq_lookup').fetchall()
            keys = {identity(row) for row in existing}
            additions = []
            for row in rows:
                if len(row) != 4 or not str(row[0]).strip() or not str(row[1]).strip():
                    continue
                key = identity(row)
                if key not in keys:
                    additions.append(tuple(row))
                    keys.add(key)
            connection.executemany('INSERT INTO ver2_nhq_lookup (name, employee_id, rank, office) VALUES (?, ?, ?, ?)', additions)
            return len(additions), len(rows) - len(additions)

    def nhq_lookup(self):
        with sqlite3.connect(self.path) as connection:
            return connection.execute('SELECT name, employee_id, rank, office FROM ver2_nhq_lookup ORDER BY name COLLATE NOCASE').fetchall()

    @staticmethod
    def _track_link(connection, employee_id, source_key):
        connection.execute("""INSERT INTO ver2_link_export_queue
            (employee_id, source_key, linked_at, exported_at)
            VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ','now'), NULL)
            ON CONFLICT(employee_id) DO UPDATE SET source_key=excluded.source_key,
            linked_at=excluded.linked_at, exported_at=NULL""", (employee_id, source_key))

    def pending_exports(self):
        """Only currently valid manual links created after tracking was enabled."""
        with sqlite3.connect(self.path) as connection:
            return connection.execute("""SELECT q.employee_id, q.source_key, q.linked_at
                FROM ver2_link_export_queue q
                JOIN ver2_balance_links l ON l.employee_id=q.employee_id AND l.source_key=q.source_key
                WHERE q.exported_at IS NULL ORDER BY q.linked_at, q.employee_id""").fetchall()

    def mark_exported(self, entries):
        # Update only the same link revision that was included in the CSV.
        with sqlite3.connect(self.path) as connection:
            connection.executemany("""UPDATE ver2_link_export_queue SET exported_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE employee_id=? AND source_key=? AND linked_at=? AND exported_at IS NULL
                AND EXISTS (SELECT 1 FROM ver2_balance_links l
                    WHERE l.employee_id=ver2_link_export_queue.employee_id AND l.source_key=ver2_link_export_queue.source_key)""", entries)

    def all(self) -> dict[str, str]:
        with sqlite3.connect(self.path) as connection:
            return dict(connection.execute("SELECT employee_id, source_key FROM ver2_balance_links"))

    def assign(self, employee_id: str, source_key: str) -> None:
        if not employee_id or not source_key:
            raise ValueError("Select a BIS employee and a balance row.")
        with sqlite3.connect(self.path) as connection:
            if connection.execute('SELECT 1 FROM ver2_name_balance_links WHERE source_key = ?', (source_key,)).fetchone():
                raise ValueError('That balance is already linked to an imported leave name.')
            previous = connection.execute('SELECT source_key FROM ver2_balance_links WHERE employee_id = ?', (employee_id,)).fetchone()
            try:
                connection.execute("INSERT INTO ver2_balance_links VALUES (?, ?) ON CONFLICT(employee_id) DO UPDATE SET source_key=excluded.source_key", (employee_id, source_key))
                if not previous or previous[0] != source_key:
                    self._track_link(connection, employee_id, source_key)
            except sqlite3.IntegrityError as error:
                raise ValueError("That balance row is already linked to another employee.") from error

    def source_links(self) -> dict[str, str]:
        with sqlite3.connect(self.path) as connection:
            return dict(connection.execute('SELECT name_key, source_key FROM ver2_name_balance_links'))

    def assign_new_bis(self, employee_id: str, source_key: str, name: str) -> None:
        """Link a newly added BIS ID, transferring only a matching manual name link."""
        if not employee_id or not source_key or not normalized_name(name):
            raise ValueError('Employee number, name and balance row are required.')
        with sqlite3.connect(self.path) as connection:
            current = connection.execute('SELECT source_key FROM ver2_balance_links WHERE employee_id = ?', (employee_id,)).fetchone()
            owner = connection.execute('SELECT employee_id FROM ver2_balance_links WHERE source_key = ?', (source_key,)).fetchone()
            name_owner = connection.execute('SELECT name_key FROM ver2_name_balance_links WHERE source_key = ?', (source_key,)).fetchone()
            if current and current[0] != source_key:
                raise ValueError('This employee is already linked to a different balance.')
            if owner and owner[0] != employee_id:
                raise ValueError('This balance is already linked to another BIS employee.')
            if name_owner and name_owner[0] != normalized_name(name):
                raise ValueError('This balance has a manual link to a different imported name. Review it first.')
            if name_owner:
                connection.execute('DELETE FROM ver2_name_balance_links WHERE source_key = ?', (source_key,))
            connection.execute('INSERT OR IGNORE INTO ver2_balance_links VALUES (?, ?)', (employee_id, source_key))
            if not current:
                self._track_link(connection, employee_id, source_key)

    def assign_source(self, name: str, source_key: str) -> None:
        name_key = normalized_name(name)
        if not name_key or not source_key:
            raise ValueError('Select an imported leave name and a balance row.')
        with sqlite3.connect(self.path) as connection:
            if connection.execute('SELECT 1 FROM ver2_balance_links WHERE source_key = ?', (source_key,)).fetchone():
                raise ValueError('That balance is already linked to a BIS employee.')
            try:
                connection.execute('INSERT INTO ver2_name_balance_links VALUES (?, ?) ON CONFLICT(name_key) DO UPDATE SET source_key=excluded.source_key', (name_key, source_key))
            except sqlite3.IntegrityError as error:
                raise ValueError('That balance is already linked to another imported name.') from error

    def assign_source_unclaimed(self, name: str, source_key: str) -> None:
        """Create a name-only leave link without moving an existing link."""
        name_key = normalized_name(name)
        if not name_key or not source_key:
            raise ValueError('A leave name and balance row are required.')
        with sqlite3.connect(self.path) as connection:
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute('SELECT 1 FROM ver2_balance_links WHERE source_key = ?', (source_key,)).fetchone():
                raise ValueError('The balance is linked to an employee.')
            existing = connection.execute('SELECT source_key FROM ver2_name_balance_links WHERE name_key = ?', (name_key,)).fetchone()
            if existing and existing[0] != source_key:
                raise ValueError('This leave name is linked to a different balance.')
            owner = connection.execute('SELECT name_key FROM ver2_name_balance_links WHERE source_key = ?', (source_key,)).fetchone()
            if owner and owner[0] != name_key:
                raise ValueError('This balance is linked to a different leave name.')
            connection.execute('INSERT OR IGNORE INTO ver2_name_balance_links VALUES (?, ?)', (name_key, source_key))

    def remove_source(self, name: str) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute('DELETE FROM ver2_name_balance_links WHERE name_key = ?', (normalized_name(name),))


def balance_rows(path: str, sheet: str, rows: list) -> tuple[list[dict], list[str]]:
    """Read brought-forward values without changing the workbook."""
    first = next((i for i, row in enumerate(rows) if any(str(v or "").strip() for v in row)), None)
    if first is None:
        return [], [f"{Path(path).name}: sheet is empty"]
    headings = {" ".join(str(value or "").casefold().split()): i for i, value in enumerate(rows[first])}
    if not all(name in headings for name in ("name", "vl", "sl")):
        return [], [f"{Path(path).name}: NAME, VL and SL columns are required"]
    result, issues = [], []
    for index, row in enumerate(rows[first + 1:], start=first + 2):
        def get(name):
            col = headings[name]
            return row[col] if col < len(row) else None
        name = " ".join(str(get("name") or "").split())
        if not name:
            if any(value is not None and str(value).strip() for value in row):
                issues.append(f"{Path(path).name} row {index}: name missing")
            continue
        def credit(column):
            if column not in headings:
                return None
            value = get(column)
            if value is None or str(value).strip() == "":
                return None
            try:
                number = Decimal(str(value).strip())
                if not number.is_finite():
                    raise ValueError("not finite")
                return number
            except (InvalidOperation, ValueError):
                issues.append(f"{Path(path).name} row {index}: invalid {column.upper()} balance")
                return None
        match_column = next((key for key in headings if key.startswith('normal match')), None)
        proposed_name = ' '.join(str(get(match_column) or '').split()) if match_column else ''
        score = get('match / tie score') if 'match / tie score' in headings else None
        try:
            score = Decimal(str(score)) if score is not None else None
            if score is not None and not score.is_finite():
                score = None
        except (InvalidOperation, ValueError):
            score = None
        match_pass = str(get('match pass') or '').strip() if 'match pass' in headings else ''
        identity = f"{str(Path(path).resolve()).casefold()}\0{sheet}\0{index}\0{normalized_name(name)}"
        source_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        result.append({"key": source_key, "name": name, "name_key": normalized_name(name),
                       "vl": credit("vl"), "sl": credit("sl"), "spl": credit("spl"),
                       "wl": credit("wellness") if "wellness" in headings else credit("wl"),
                       "fl": credit("fl"), "path": path, "sheet": sheet, "row": index,
                       "proposed_name": proposed_name, "match_score": score, "match_pass": match_pass,
                       "has_normal_match_column": match_column is not None})
    return result, issues


def suggested_balance_candidates(name: str, rows: list[dict]) -> list[dict]:
    """Suggest same surname and given-name prefix; suggestions are not links."""
    parts = normalized_name(name).split(",", 1)
    if len(parts) != 2:
        return []
    surname, given = parts[0].strip(), parts[1].strip()
    result = []
    for row in rows:
        candidate = row["name_key"].split(",", 1)
        if len(candidate) != 2 or candidate[0].strip() != surname:
            continue
        c_given = candidate[1].strip()
        if c_given and (given == c_given or given.startswith(c_given + " ") or c_given.startswith(given + " ")):
            result.append(row)
    return result


def resolve_balance_matches(rows: list[dict], people: list, links: dict[str, str]) -> dict:
    """Resolve explicit links and workbook-normalized names, then legacy matches.

    Suggested matches are provisional and must be visibly reviewed. Nothing is
    persisted until a user confirms it. A source and employee can be paired
    only once; ambiguous names and duplicate employee IDs are left unlinked.
    """
    by_name, by_id, by_surname = defaultdict(list), defaultdict(list), defaultdict(list)
    for person in people:
        by_name[normalized_name(person.name)].append(person)
        by_id[person.employee_number].append(person)
    valid = [p for p in people if p.employee_number and len(by_id[p.employee_number]) == 1
             and len(by_name[normalized_name(p.name)]) == 1]
    source_by_key = {row['key']: row for row in rows}
    legacy_rows = [row for row in rows if not row.get('has_normal_match_column')]
    source_name_count = Counter(row['name_key'] for row in legacy_rows)
    result, used_employees, used_sources = {}, set(), set()
    for person in valid:
        key = links.get(person.employee_number)
        if key and key in source_by_key:
            result[key] = (person, 'Manually linked')
            used_employees.add(person.employee_number)
            used_sources.add(key)
    # An unavailable manual link must not silently fall back to a different row.
    for person in valid:
        if person.employee_number in links:
            used_employees.add(person.employee_number)
    # The normalized column is the workbook's selected employee name. Require
    # an exact, unique employee and source row; never guess when it is blank.
    proposals = defaultdict(list)
    proposal_counts = Counter(normalized_name(row.get('proposed_name', '')) for row in rows
                              if row.get('has_normal_match_column') and row.get('proposed_name'))
    for row in rows:
        proposed = normalized_name(row.get('proposed_name', ''))
        if row.get('has_normal_match_column') and row['key'] not in used_sources and proposed:
            proposals[proposed].append(row)
    for person in valid:
        if person.employee_number in used_employees:
            continue
        candidates = proposals.get(normalized_name(person.name), [])
        if len(candidates) == 1 and proposal_counts[normalized_name(person.name)] == 1:
            row = candidates[0]
            result[row['key']] = (person, 'Normalized name match')
            used_employees.add(person.employee_number)
            used_sources.add(row['key'])
    for person in valid:
        name = normalized_name(person.name)
        if person.employee_number in used_employees or source_name_count[name] != 1:
            continue
        row = next(row for row in legacy_rows if row['name_key'] == name)
        if row['key'] not in used_sources:
            result[row['key']] = (person, 'Exact name match')
            used_employees.add(person.employee_number)
            used_sources.add(row['key'])
    for row in legacy_rows:
        if row['key'] not in used_sources:
            by_surname[row['name_key'].split(',', 1)[0].strip()].append(row)
    choices, demand = {}, Counter()
    for person in valid:
        if person.employee_number in used_employees:
            continue
        candidates = suggested_balance_candidates(person.name, by_surname[normalized_name(person.name).split(',', 1)[0].strip()])
        choices[person.employee_number] = candidates
        for row in candidates:
            demand[row['key']] += 1
    for person in valid:
        candidates = choices.get(person.employee_number, [])
        if len(candidates) == 1 and demand[candidates[0]['key']] == 1:
            result[candidates[0]['key']] = (person, 'Possible name match · review')
    return result


def wellness_priority_records(days):
    """Represent verified VER1 wellness dates alongside imported VER2 leave."""
    return [{'record_key': '__ver1_wl__' + day.isoformat(), 'leave_type': 'WL',
             'start_date': day.isoformat(), 'end_date': day.isoformat(), 'status': 'A',
             'source_path': 'VER1 wellness history', 'source_sheet': '', 'source_row': '',
             'wellness_source': True}
            for day in sorted(days or ())]


def project_balance(balance: dict, records: list[dict], holidays: set[date] | frozenset[date],
                    holiday_min_year: int, holiday_max_year: int, as_of: date, wellness_days=None) -> dict:
    """Add completed monthly credits and subtract unique eligible leave.

    Empty imported status is treated as approved; cancelled, disapproved and
    other explicit non-approved statuses never affect a balance.
    """
    if as_of < BALANCE_DATE:
        raise ValueError("Calculation date cannot precede the brought-forward date.")
    months = ((as_of.year - BALANCE_DATE.year) * 12 + as_of.month - BALANCE_DATE.month
              - (as_of.day < calendar.monthrange(as_of.year, as_of.month)[1]))
    earned = Decimal(max(0, months)) * Decimal('1.250')
    included = []
    for record in list(records) + wellness_priority_records(wellness_days):
        status = str(record.get("status") or "").strip().upper()
        if status not in {"", "A", "APPROVED"}:
            continue
        start = max(date.fromisoformat(record["start_date"]), date(2026, 9, 1))
        end = min(date.fromisoformat(record["end_date"]), as_of)
        if start <= end:
            clipped = dict(record)
            clipped["start_date"], clipped["end_date"] = start.isoformat(), end.isoformat()
            # A missing status was explicitly confirmed approved for this source.
            if not status:
                clipped["status"] = "A"
            included.append(clipped)
    allocation = allocate_unique_estimates(included, holidays, holiday_min_year, holiday_max_year,
                                           opening_sl=balance.get('sl'), accrual_start=BALANCE_DATE,
                                           auto_priority=True)
    automatic = sorted({item for entry in allocation.values() for item in entry['auto_resolved']})
    if any(item["conflicts"] or item["unavailable"] for item in allocation.values()):
        return {"vl": None, "sl": None, "fl": None, "spl": None, "used_vl": None, "used_sl": None,
                "earned_vl": earned, "earned_sl": earned, "review": True, "auto_resolutions": automatic}
    used_vl = sum(Decimal(str(item["vl"])) for item in allocation.values())
    used_sl = sum(Decimal(str(item["sl"])) for item in allocation.values())
    used_fl = sum(Decimal(str(allocation[item['record_key']]['chargeable'])) for item in included
                  if str(item['leave_type']).strip().upper() == 'FL')
    used_spl = sum(Decimal(str(allocation[item['record_key']]['chargeable'])) for item in included
                   if str(item['leave_type']).strip().upper() == 'SPL')
    used_wl = sum(Decimal(str(allocation[item['record_key']]['chargeable'])) for item in included
                  if str(item['leave_type']).strip().upper() == 'WL')
    opening_fl = balance.get('fl')
    opening_spl = balance.get('spl')
    return {"vl": None if balance["vl"] is None else balance["vl"] + earned - used_vl,
            "sl": None if balance["sl"] is None else balance["sl"] + earned - used_sl,
            "fl": None if opening_fl is None or as_of.year != BALANCE_DATE.year else opening_fl - used_fl,
            "spl": None if opening_spl is None or as_of.year != BALANCE_DATE.year else opening_spl - used_spl,
            "used_vl": used_vl, "used_sl": used_sl, "used_wl": used_wl,
            "earned_vl": earned, "earned_sl": earned, "review": False, "auto_resolutions": automatic}



