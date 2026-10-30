from collections import Counter
from datetime import date
from decimal import Decimal

from .philippine_holidays import HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR
from .ver2_balances import BALANCE_DATE, project_balance
from .ver2_database import normalized_name


def august_mone_baseline(snapshot, catchup=None):
    """Use manual MONE values as August B/F, reconstructing dated catch-ups."""
    result = dict(snapshot, kind='manual', august_usable=True)
    if catchup:
        month_index = int(catchup['last_credit_year']) * 12 + int(catchup['last_credit_month'])
        august_index = BALANCE_DATE.year * 12 + BALANCE_DATE.month
        if month_index > august_index:
            result['august_usable'] = False
            return result
        earned = Decimal(august_index - month_index) * Decimal('1.250')
        result['vl'] = Decimal(str(catchup['base_vl'])) + earned
        result['sl'] = Decimal(str(catchup['base_sl'])) + earned
        result['kind'] = 'catchup'
    return result


def include_personnel_and_mone(rows, people, overrides, records, holidays, as_of):
    """Use VER1 as the August B/F for personnel without a matched source row."""
    result = list(rows)
    linked_ids = {person.employee_number for _, person, _, _ in rows if person}
    id_counts = Counter(p.employee_number for p in people if p.employee_number)
    name_counts = Counter(normalized_name(p.name) for p in people)
    for index, person in enumerate(people):
        employee_id = person.employee_number
        if employee_id and id_counts[employee_id] == 1 and employee_id in linked_ids:
            continue
        snapshot = overrides.get(employee_id) if employee_id and id_counts[employee_id] == 1 else None
        usable = bool(snapshot and snapshot.get('august_usable', True))
        source = {'key': f'personnel:{index}:{employee_id}', 'name': person.name,
                  'spl': None, 'wl': None, 'fallback_kind': 'mone' if snapshot else 'missing',
                  'mone_kind': snapshot.get('kind', 'manual') if snapshot else '',
                  'august_usable': usable,
                  'mone_zero': bool(snapshot and Decimal(str(snapshot['vl'])) == 0 and Decimal(str(snapshot['sl'])) == 0),
                  'updated_at': snapshot.get('updated_at', '') if snapshot else ''}
        estimate = None
        if snapshot and usable and as_of >= BALANCE_DATE:
            balance = {'vl': Decimal(str(snapshot['vl'])), 'sl': Decimal(str(snapshot['sl'])), 'fl': None}
            name = normalized_name(person.name)
            history = records.get(name, []) if name_counts[name] == 1 else []
            estimate = project_balance(balance, history, holidays, HOLIDAY_MIN_YEAR, HOLIDAY_MAX_YEAR, as_of)
            status = 'VER1 August opening · applied monthly earnings and imported leave'
            if not history:
                status += ' · No matched VER2 leave; review'
            if name_counts[name] > 1:
                status += ' · Duplicate personnel name; review'
            if estimate['review']:
                status += ' · Review conflicts or holiday data'
            if snapshot.get('august_review'):
                status += f" · {snapshot['august_review']}"
        elif snapshot and not usable:
            status = 'MONE starting month is after August 2026 · August balance unavailable'
        elif snapshot:
            status = 'Balance unavailable before August 2026'
        else:
            status = 'No brought-forward or MONE balance'
        if employee_id and id_counts[employee_id] > 1:
            status = 'Duplicate employee ID · needs review'
        result.append((source, person, status, estimate))
    result.sort(key=lambda row: ((row[1].name if row[1] else row[0]['name']).casefold(), row[0]['key']))
    covered = 0
    for source, person, _status, estimate in result:
        if not person or not estimate or estimate.get('vl') is None or estimate.get('sl') is None:
            continue
        if source.get('fallback_kind') == 'mone' and source.get('mone_zero'):
            continue
        covered += 1
    return result, covered
