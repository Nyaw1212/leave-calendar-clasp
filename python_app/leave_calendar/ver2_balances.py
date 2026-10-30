from __future__ import annotations

import hashlib
import sqlite3
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

    def all(self) -> dict[str, str]:
        with sqlite3.connect(self.path) as connection:
            return dict(connection.execute("SELECT employee_id, source_key FROM ver2_balance_links"))

    def assign(self, employee_id: str, source_key: str) -> None:
        if not employee_id or not source_key:
            raise ValueError("Select a BIS employee and a balance row.")
        with sqlite3.connect(self.path) as connection:
            try:
                connection.execute("INSERT INTO ver2_balance_links VALUES (?, ?) ON CONFLICT(employee_id) DO UPDATE SET source_key=excluded.source_key", (employee_id, source_key))
            except sqlite3.IntegrityError as error:
                raise ValueError("That balance row is already linked to another employee.") from error


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


def project_balance(balance: dict, records: list[dict], holidays: set[date] | frozenset[date],
                    holiday_min_year: int, holiday_max_year: int, as_of: date) -> dict:
    """Subtract unique eligible leave after the opening date through as_of.

    Empty imported status is treated as approved; cancelled, disapproved and
    other explicit non-approved statuses never affect a balance.
    """
    if as_of < BALANCE_DATE:
        raise ValueError("Calculation date cannot precede the brought-forward date.")
    included = []
    for record in records:
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
    allocation = allocate_unique_estimates(included, holidays, holiday_min_year, holiday_max_year)
    if any(item["conflicts"] or item["unavailable"] for item in allocation.values()):
        return {"vl": None, "sl": None, "fl": None, "used_vl": None, "used_sl": None, "review": True}
    used_vl = sum(Decimal(str(item["vl"])) for item in allocation.values())
    used_sl = sum(Decimal(str(item["sl"])) for item in allocation.values())
    used_fl = sum(Decimal(str(allocation[item['record_key']]['chargeable'])) for item in included
                  if str(item['leave_type']).strip().upper() == 'FL')
    opening_fl = balance.get('fl')
    return {"vl": None if balance["vl"] is None else balance["vl"] - used_vl,
            "sl": None if balance["sl"] is None else balance["sl"] - used_sl,
            "fl": None if opening_fl is None or as_of.year != BALANCE_DATE.year else opening_fl - used_fl,
            "used_vl": used_vl, "used_sl": used_sl, "review": False}

