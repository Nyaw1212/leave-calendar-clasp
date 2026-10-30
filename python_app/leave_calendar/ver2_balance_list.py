from collections import Counter
from decimal import Decimal


def include_personnel_and_mone(rows, people, overrides):
    """Add all personnel; a MONE snapshot fills only an absent B/F match.

    A snapshot is shown as entered, without applying imported leave. Its save
    timestamp is not evidence of the date through which the balance is valid.
    """
    result = list(rows)
    linked_ids = {person.employee_number for _, person, _, _ in rows if person}
    id_counts = Counter(p.employee_number for p in people if p.employee_number)
    for index, person in enumerate(people):
        employee_id = person.employee_number
        if employee_id and id_counts[employee_id] == 1 and employee_id in linked_ids:
            continue
        snapshot = overrides.get(employee_id) if employee_id and id_counts[employee_id] == 1 else None
        source = {'key': f'personnel:{index}:{employee_id}', 'name': person.name,
                  'spl': None, 'wl': None, 'fallback_kind': 'mone' if snapshot else 'missing',
                  'mone_kind': snapshot.get('kind', 'manual') if snapshot else '',
                  'updated_at': snapshot.get('updated_at', '') if snapshot else ''}
        estimate = (dict(vl=Decimal(str(snapshot['vl'])), sl=Decimal(str(snapshot['sl'])), fl=None)
                    if snapshot else None)
        status = ('VER1 leave-history balance · calculated today' if snapshot and source['mone_kind'] == 'history'
                  else 'Saved MONE balance · balance date not recorded' if snapshot
                  else 'No brought-forward or MONE balance')
        if employee_id and id_counts[employee_id] > 1:
            status = 'Duplicate employee ID · needs review'
        result.append((source, person, status, estimate))
    result.sort(key=lambda row: ((row[1].name if row[1] else row[0]['name']).casefold(), row[0]['key']))
    covered = 0
    for source, person, _status, estimate in result:
        if not person or not estimate or estimate.get('vl') is None or estimate.get('sl') is None:
            continue
        if source.get('fallback_kind') == 'mone' and estimate['vl'] == 0 and estimate['sl'] == 0:
            continue  # MONE 0/0 is not marked as encoded.
        covered += 1
    return result, covered
