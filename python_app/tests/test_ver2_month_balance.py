import unittest
from datetime import date
from decimal import Decimal
from leave_calendar.ver2_balances import balance_rows, project_balance

class MonthBalanceTests(unittest.TestCase):
    def test_opening_columns_and_missing_values(self):
        rows, issues = balance_rows('credits.xlsx', 'Sheet1', [['NAME', 'VL', 'SL', 'SPL', 'WELLNESS', 'FL'], ['A', 10, 15, 2, 5, 5], ['B', 0, 0, None, None, None]])
        self.assertEqual([rows[0][c] for c in ('vl','sl','spl','wl','fl')], [Decimal('10'),Decimal('15'),Decimal('2'),Decimal('5'),Decimal('5')])
        self.assertIsNone(rows[1]['spl'])
        self.assertFalse(issues)

    def test_fl_deducted_from_vl_and_fl_through_month_end_once(self):
        balance = dict(vl=Decimal('10'), sl=Decimal('10'), fl=Decimal('5'))
        records = [dict(record_key='a', start_date='2026-10-29', end_date='2026-10-30', leave_type='FL', status=''),
                   dict(record_key='b', start_date='2026-10-29', end_date='2026-10-30', leave_type='FL', status='A'),
                   dict(record_key='c', start_date='2026-11-02', end_date='2026-11-02', leave_type='FL', status='A')]
        result = project_balance(balance, records, {date(2026,10,30)}, 2026, 2026, date(2026,10,31))
        self.assertEqual((result['vl'], result['sl'], result['fl']), (Decimal('11.500'), Decimal('12.500'), Decimal('4')))

    def test_year_end_and_conflicts_do_not_fabricate_fl(self):
        balance = dict(vl=Decimal('10'), sl=Decimal('10'), fl=Decimal('5'))
        self.assertIsNone(project_balance(balance, [], set(), 2026, 2027, date(2027,1,31))['fl'])
        records = [dict(record_key='a', start_date='2026-10-29', end_date='2026-10-29', leave_type='FL', status='A'), dict(record_key='b', start_date='2026-10-29', end_date='2026-10-29', leave_type='SL', status='A')]
        result = project_balance(balance, records, set(), 2026, 2027, date(2026,10,31))
        self.assertTrue(result['review'])
        self.assertIsNone(result['fl'])

if __name__ == '__main__':
    unittest.main()
