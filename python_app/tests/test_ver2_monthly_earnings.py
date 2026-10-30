import unittest
from datetime import date
from decimal import Decimal
from leave_calendar.ver2_balances import project_balance

class MonthlyEarningsTests(unittest.TestCase):
    def test_completed_month_boundaries(self):
        balance = {'vl':Decimal('10'),'sl':Decimal('15')}
        for end, earned in [(date(2026,8,31),'0'), (date(2026,9,1),'0'),
                            (date(2026,9,29),'0'), (date(2026,9,30),'1.250'),
                            (date(2026,10,30),'1.250'), (date(2026,10,31),'2.500'),
                            (date(2027,1,31),'6.250')]:
            result = project_balance(balance, [], set(), 2026, 2027, end)
            with self.subTest(end=end):
                self.assertEqual(result['earned_vl'], Decimal(earned))
                self.assertEqual(result['earned_sl'], Decimal(earned))
                self.assertEqual(result['vl'], Decimal('10') + Decimal(earned))
                self.assertEqual(result['sl'], Decimal('15') + Decimal(earned))

    def test_deductions_and_missing_opening_values(self):
        balance = {'vl':None,'sl':Decimal('15')}
        records = [{'record_key':'a','start_date':'2026-09-01','end_date':'2026-09-01','status':'A','leave_type':'SL'}]
        result = project_balance(balance, records, set(), 2026, 2027, date(2026,10,31))
        self.assertIsNone(result['vl'])
        self.assertEqual(result['sl'], Decimal('16.500'))
        self.assertEqual(result['used_sl'], Decimal('1'))

if __name__ == '__main__': unittest.main()
