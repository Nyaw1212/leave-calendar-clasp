import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from leave_calendar.ver2_balance_list import include_personnel_and_mone, august_mone_baseline

class BalanceListTests(unittest.TestCase):
    def test_personnel_mone_used_as_august_opening_with_earnings_and_leave(self):
        a=SimpleNamespace(name='A',employee_number='1')
        b=SimpleNamespace(name='B',employee_number='2')
        c=SimpleNamespace(name='C',employee_number='3')
        opening=({'key':'file-a','name':'A'},a,'Exact name match',{'vl':Decimal('0'),'sl':Decimal('0')})
        unmatched=({'key':'file-x','name':'X'},None,'Needs linking',None)
        records={'b':[{'record_key':'a','start_date':'2026-10-01','end_date':'2026-10-01','status':'A','leave_type':'VL'}]}
        rows,count=include_personnel_and_mone([opening,unmatched],[a,b,c],{'1':{'vl':100,'sl':100},'2':{'vl':10,'sl':15},'3':{'vl':0,'sl':0}},records,set(),date(2026,10,31))
        self.assertEqual(len(rows),4)
        self.assertEqual(count,2)
        by_name={row[1].name:row for row in rows if row[1]}
        self.assertEqual(by_name['A'][3]['vl'],Decimal('0'))
        self.assertEqual(by_name['B'][3]['vl'],Decimal('11.500'))
        self.assertEqual(by_name['B'][3]['sl'],Decimal('17.500'))
        self.assertEqual(by_name['B'][3]['earned_vl'],Decimal('2.500'))
        self.assertEqual(by_name['B'][3]['used_vl'],Decimal('1'))
        self.assertIsNone(by_name['B'][3]['fl'])

    def test_duplicate_employee_ids_never_get_mone_automatically(self):
        people=[SimpleNamespace(name='A',employee_number='1'),SimpleNamespace(name='B',employee_number='1')]
        rows,count=include_personnel_and_mone([],people,{'1':{'vl':5,'sl':5}}, {},set(),date(2026,10,31))
        self.assertEqual(count,0)
        self.assertTrue(all(row[3] is None and 'Duplicate' in row[2] for row in rows))

    def test_dated_catchup_reconstructed_to_august_without_double_earning(self):
        snapshot={'vl':20,'sl':30}
        catchup={'base_vl':10,'base_sl':15,'last_credit_month':6,'last_credit_year':2026}
        baseline=august_mone_baseline(snapshot,catchup)
        self.assertEqual((baseline['vl'],baseline['sl']),(Decimal('12.500'),Decimal('17.500')))
        rows,_=include_personnel_and_mone([], [SimpleNamespace(name='A',employee_number='1')], {'1':baseline}, {},set(),date(2026,10,31))
        self.assertEqual((rows[0][3]['vl'],rows[0][3]['sl']),(Decimal('15'),Decimal('20')))

    def test_catchup_after_august_reverses_earnings_and_flags_leave_review(self):
        baseline=august_mone_baseline({'vl':20,'sl':30},{'base_vl':10,'base_sl':15,'last_credit_month':9,'last_credit_year':2026})
        self.assertTrue(baseline['august_usable'])
        self.assertEqual((baseline['vl'],baseline['sl']),(Decimal('8.750'),Decimal('13.750')))
        rows,count=include_personnel_and_mone([], [SimpleNamespace(name='A',employee_number='1')], {'1':baseline}, {},set(),date(2026,10,31))
        self.assertEqual((rows[0][3]['vl'],rows[0][3]['sl']),(Decimal('11.250'),Decimal('16.250')))
        self.assertEqual(count,1)
        self.assertIn('review whether later leave deductions were already included', rows[0][2])

    def test_october_balance_reverses_two_months(self):
        baseline=august_mone_baseline({'vl':20,'sl':30},{'base_vl':10,'base_sl':15,'last_credit_month':10,'last_credit_year':2026})
        self.assertEqual((baseline['vl'],baseline['sl']),(Decimal('7.500'),Decimal('12.500')))

    def test_duplicate_names_do_not_use_ambiguous_leave(self):
        people=[SimpleNamespace(name='A',employee_number='1'),SimpleNamespace(name='A',employee_number='2')]
        records={'a':[{'record_key':'r','start_date':'2026-09-01','end_date':'2026-09-01','status':'A','leave_type':'VL'}]}
        rows,_=include_personnel_and_mone([],people,{'1':{'vl':10,'sl':10}},records,set(),date(2026,9,30))
        self.assertEqual(rows[0][3]['vl'],Decimal('11.250'))
        self.assertIn('Duplicate personnel name',rows[0][2])

if __name__=='__main__': unittest.main()
