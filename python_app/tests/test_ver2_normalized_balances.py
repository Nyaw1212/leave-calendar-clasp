import unittest
from types import SimpleNamespace
from leave_calendar.ver2_balances import balance_rows, resolve_balance_matches

class NormalizedBalancesTests(unittest.TestCase):
    def test_high_score_is_provisional_and_original_name_preserved(self):
        rows, issues = balance_rows('credits.xlsx', 'Sheet1', [
            ['NAME','VL','SL','NORMAL MATCH (5-PASS 1:1)','MATCH / TIE SCORE','MATCH PASS'],
            ['ORIGINAL, ONE', 10, 20, 'PERSONNEL, NAME', 95, 'PASS 1'],
        ])
        person = SimpleNamespace(name='PERSONNEL, NAME', employee_number='1')
        result = resolve_balance_matches(rows, [person], {})
        self.assertEqual(rows[0]['name'], 'ORIGINAL, ONE')
        self.assertEqual(result[rows[0]['key']], (person, 'Possible name match · review'))
        self.assertFalse(issues)

    def test_low_score_and_surname_only_stay_unlinked(self):
        header = ['NAME','VL','SL','NORMAL MATCH (5-PASS 1:1)','MATCH / TIE SCORE','MATCH PASS']
        people = [SimpleNamespace(name='PERSONNEL, NAME', employee_number='1')]
        for score, method in [(89, 'PASS 2'), (100, 'PASS 5: SURNAME ONLY')]:
            rows, _ = balance_rows('credits.xlsx', 'Sheet1', [header,['ORIGINAL, ONE',1,2,'PERSONNEL, NAME',score,method]])
            self.assertEqual(resolve_balance_matches(rows, people, {}), {})

    def test_duplicate_proposals_do_not_assign_one_person_twice(self):
        header = ['NAME','VL','SL','NORMAL MATCH (5-PASS 1:1)','MATCH / TIE SCORE']
        rows, _ = balance_rows('credits.xlsx', 'Sheet1', [header,['ONE, X',1,2,'PERSON, A',100],['TWO, Y',3,4,'PERSON, A',70]])
        self.assertEqual(resolve_balance_matches(rows, [SimpleNamespace(name='PERSON, A',employee_number='1')], {}), {})

if __name__ == '__main__': unittest.main()
