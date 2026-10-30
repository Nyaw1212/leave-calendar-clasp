import unittest
from decimal import Decimal
from types import SimpleNamespace
from leave_calendar.ver2_balance_list import include_personnel_and_mone

class BalanceListTests(unittest.TestCase):
    def test_personnel_mone_fallback_and_no_double_count(self):
        a=SimpleNamespace(name='A',employee_number='1')
        b=SimpleNamespace(name='B',employee_number='2')
        c=SimpleNamespace(name='C',employee_number='3')
        opening=({'key':'file-a','name':'A'},a,'Exact name match',{'vl':Decimal('0'),'sl':Decimal('0')})
        unmatched=({'key':'file-x','name':'X'},None,'Needs linking',None)
        rows, count = include_personnel_and_mone([opening, unmatched], [a,b,c], {
            '1': {'vl':100,'sl':100}, '2': {'vl':10,'sl':15,'updated_at':'2026-10-30'},
            '3': {'vl':0,'sl':0}})
        self.assertEqual(len(rows),4)
        self.assertEqual(count,2)  # B/F zero counts, MONE zero/zero does not.
        by_name={row[1].name:row for row in rows if row[1]}
        self.assertEqual(by_name['A'][3]['vl'], Decimal('0'))
        self.assertEqual(by_name['B'][0]['fallback_kind'], 'mone')
        self.assertEqual(by_name['B'][3]['vl'], Decimal('10'))
        self.assertEqual(by_name['B'][3]['sl'], Decimal('15'))
        self.assertIn('date not recorded', by_name['B'][2])

    def test_duplicate_employee_ids_never_get_mone_automatically(self):
        people=[SimpleNamespace(name='A',employee_number='1'),SimpleNamespace(name='B',employee_number='1')]
        rows,count=include_personnel_and_mone([],people,{'1':{'vl':5,'sl':5}})
        self.assertEqual(count,0)
        self.assertTrue(all(row[3] is None and 'Duplicate' in row[2] for row in rows))

if __name__=='__main__': unittest.main()
