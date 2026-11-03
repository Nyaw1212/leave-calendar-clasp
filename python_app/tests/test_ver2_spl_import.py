import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from leave_calendar.ver2_database import Ver2Database
from leave_calendar.ver2_credit import estimate_leave_charge
from leave_calendar.ver2_balances import project_balance


class SplImportTests(unittest.TestCase):
    def test_import_sample_columns_and_deduct_unique_spl_and_fl(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Ver2Database(Path(directory) / 'data.sqlite3')
            header = ['NO', 'Emp_Name', 'EMP_RANK', 'oppf', 'office', 'start_at', 'end_at']
            spl = [1, 'EXAMPLE, PERSON', 'CO1', 'Station', 'Office', '2026-09-05', '2026-09-07']
            fl = [2, 'EXAMPLE, PERSON', 'CO1', 'Station', 'Office', '2026-09-09', '2026-09-10']
            self.assertEqual(db.import_sheet('SPL', 'spl.xls', 'Sheet1', [header, spl, spl])[0], 2)
            self.assertEqual(db.import_sheet('FL', 'fl.xls', 'Sheet1', [header, fl, fl])[0], 2)
            self.assertEqual(db.import_sheet('SPL', 'spl.xls', 'Sheet1', [header, spl, spl])[0], 0)
            balance = {'vl': Decimal('10'), 'sl': Decimal('10'), 'fl': Decimal('5'), 'spl': Decimal('3')}
            result = project_balance(balance, db.records(), {date(2026, 9, 7)}, 2026, 2026, date(2026, 9, 30))
            self.assertEqual((result['spl'], result['fl'], result['vl'], result['sl']),
                             (Decimal('0'), Decimal('3'), Decimal('9.250'), Decimal('11.250')))
            self.assertFalse(result['review'])

    def test_spl_includes_weekends_and_regular_holidays(self):
        self.assertEqual(estimate_leave_charge(date(2026, 9, 5), date(2026, 9, 7), 'SPL',
                                              {date(2026, 9, 7)}, 2026, 2026), (3, 3, 0.0, 0.0))

    def test_spl_same_day_as_fl_is_flagged_not_double_charged(self):
        balance = {'vl': Decimal('10'), 'sl': Decimal('10'), 'fl': Decimal('5'), 'spl': Decimal('3')}
        records = [dict(record_key=t, start_date='2026-09-07', end_date='2026-09-07',
                        leave_type=t, status='A') for t in ('SPL', 'FL')]
        result = project_balance(balance, records, set(), 2026, 2026, date(2026, 9, 30))
        self.assertTrue(result['review'])
        self.assertIsNone(result['spl'])
        self.assertIsNone(result['fl'])

    def test_no_opening_spl_or_new_year_stays_unknown(self):
        base = {'vl': Decimal('10'), 'sl': Decimal('10'), 'fl': Decimal('5')}
        self.assertIsNone(project_balance(base, [], set(), 2026, 2027, date(2026, 9, 30))['spl'])
        base['spl'] = Decimal('3')
        self.assertIsNone(project_balance(base, [], set(), 2026, 2027, date(2027, 1, 31))['spl'])


if __name__ == '__main__':
    unittest.main()
