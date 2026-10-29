import unittest
from types import SimpleNamespace

from leave_calendar.ver2_balances import resolve_balance_matches


def person(name, employee_id):
    return SimpleNamespace(name=name, employee_number=employee_id)


def row(key, name):
    return {'key': key, 'name_key': name.casefold()}


class BalanceMatchingTests(unittest.TestCase):
    def test_unique_short_name_is_provisional(self):
        match = resolve_balance_matches([row('a', 'AABLING, JOYCE')],
                                        [person('AABLING, JOYCE JUAREZ', '1')], {})
        self.assertEqual(match['a'][1], 'Possible name match · review')

    def test_ambiguous_name_is_not_linked(self):
        people = [person('ABAD, DON JAMES', '1'), person('ABAD, DON PAUL', '2')]
        self.assertEqual(resolve_balance_matches([row('a', 'ABAD, DON')], people, {}), {})

    def test_manual_link_precedes_other_possible_and_exact_matches(self):
        people = [person('ABAD, DON', '1'), person('ABAD, DON PAUL', '2')]
        result = resolve_balance_matches([row('a', 'ABAD, DON')], people, {'2': 'a'})
        self.assertEqual(result['a'][0].employee_number, '2')
        self.assertEqual(result['a'][1], 'Manually linked')

    def test_duplicate_source_names_and_employee_ids_are_not_guessed(self):
        self.assertEqual(resolve_balance_matches([row('a', 'ABAD, DON'), row('b', 'ABAD, DON')],
                                                 [person('ABAD, DON', '1')], {}), {})
        self.assertEqual(resolve_balance_matches([row('a', 'ABAD, DON')],
                                                 [person('ABAD, DON', '1'), person('OTHER, NAME', '1')], {}), {})

    def test_missing_manual_source_is_not_replaced_automatically(self):
        self.assertEqual(resolve_balance_matches([row('new', 'ABAD, DON')],
                                                 [person('ABAD, DON', '1')], {'1': 'old'}), {})


if __name__ == '__main__':
    unittest.main()
