from __future__ import annotations

from datetime import date


def ver2_print_fields(source, person, estimate, as_of, assumption_date=None):
    """Map one selected VER2 balance to the existing leave-card template.

    Unknown values stay blank; SPL/WL are the 2026 brought-forward amounts.
    """
    name = str(person.name if person else source['name']).strip().upper()
    within_year = as_of.year == 2026 and as_of >= date(2026, 8, 31)
    def formatted(value, whole=False):
        if value is None:
            return ''
        return f'{value:.0f}' if whole else f'{value:.3f}'
    return {
        'header_name': name,
        'name': name,
        'entrance_of_duty': assumption_date.strftime('%m/%d/%Y') if assumption_date else '',
        'bf_period': as_of.strftime('%b %Y').upper(),
        'bf_vl_balance': formatted(estimate.get('vl')) if estimate else '',
        'bf_sl_balance': formatted(estimate.get('sl')) if estimate else '',
        'bf_fl_value': formatted(estimate.get('fl'), whole=True) if estimate else '',
        'bf_spl_value': formatted(source.get('spl'), whole=True) if person and within_year else '',
        'bf_wl_value': formatted(source.get('wl'), whole=True) if person and within_year else '',
    }
