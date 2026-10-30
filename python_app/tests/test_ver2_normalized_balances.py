import unittest
from types import SimpleNamespace
from leave_calendar.ver2_balances import balance_rows, resolve_balance_matches

class NormalizedBalancesTests(unittest.TestCase):
    def test_normalized_column_matches_employee_even_if_score_below_90(self):
        header = ['NAME','VL','SL','NORMAL MATCH (5-PASS 1:1)','MATCH / TIE SCORE','MATCH PASS']
        person = SimpleNamespace(name='PERSONNEL, NAME', employee_number='1')
        for score, method in [(95,'PASS 1'), (73.7,'PASS 3'), (10,'PASS 5: SURNAME ONLY')]:
            rows, issues = balance_rows('credits.xlsx', 'Sheet1', [header,['ORIGINAL, ONE', 10, 20, 'PERSONNEL, NAME', score, method]])
            result = resolve_balance_matches(rows, [person], {})
            self.assertEqual(rows[0]['name'], 'ORIGINAL, ONE')
            self.assertEqual(result[rows[0]['key']], (person, 'Normalized name match'))
            self.assertFalse(issues)

    def test_blank_normalized_name_never_guesses_original(self):
        header = ['NAME','VL','SL','NORMAL MATCH (5-PASS 1:1)']
        rows, _ = balance_rows('credits.xlsx','Sheet1',[header,['PERSONNEL, NAME',1,2,None]])
        self.assertEqual(resolve_balance_matches(rows,[SimpleNamespace(name='PERSONNEL, NAME',employee_number='1')],{}),{})

    def test_duplicate_and_nonexistent_names_are_unlinked(self):
        header = ['NAME','VL','SL','NORMAL MATCH (5-PASS 1:1)']
        rows, _ = balance_rows('credits.xlsx', 'Sheet1', [header,['ONE, X',1,2,'PERSON, A'],['TWO, Y',3,4,'PERSON, A']])
        self.assertEqual(resolve_balance_matches(rows, [SimpleNamespace(name='PERSON, A',employee_number='1')], {}), {})
        rows, _ = balance_rows('credits.xlsx', 'Sheet1', [header,['ONE, X',1,2,'MISSING, PERSON']])
        self.assertEqual(resolve_balance_matches(rows, [SimpleNamespace(name='PERSON, A',employee_number='1')], {}), {})

    def test_normalized_name_takes_precedence_over_original(self):
        header = ['NAME','VL','SL','NORMAL MATCH (5-PASS 1:1)']
        rows, _ = balance_rows('credits.xlsx','Sheet1',[header,['OLD, PERSON',1,2,'NEW, PERSON']])
        people = [SimpleNamespace(name='OLD, PERSON',employee_number='1'),SimpleNamespace(name='NEW, PERSON',employee_number='2')]
        self.assertEqual(resolve_balance_matches(rows,people,{})[rows[0]['key']][0].employee_number, '2')

if __name__ == '__main__': unittest.main()
