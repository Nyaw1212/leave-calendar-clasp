import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from leave_calendar.ver2_print_fields import ver2_print_fields

class Ver2PrintFieldsTests(unittest.TestCase):
    def test_selected_month_uses_ver2_results(self):
        person = SimpleNamespace(name='SMITH, JANE')
        values = ver2_print_fields({'name':'SMITH, JANE', 'spl':Decimal('2'), 'wl':Decimal('4')}, person,
            {'vl':Decimal('10.125'), 'sl':Decimal('15'), 'fl':Decimal('3')}, date(2026,10,31), date(2020,1,2))
        self.assertEqual((values['name'], values['bf_period'], values['entrance_of_duty']), ('SMITH, JANE','OCT 2026','01/02/2020'))
        self.assertEqual([values[k] for k in ('bf_vl_balance','bf_sl_balance','bf_fl_value','bf_spl_value','bf_wl_value')], ['10.125','15.000','3','2','4'])

    def test_unlinked_and_unknown_values_are_blank(self):
        values = ver2_print_fields({'name':'Unlinked', 'spl':Decimal('2'), 'wl':Decimal('5')}, None, None, date(2026,10,31))
        self.assertEqual(values['name'], 'UNLINKED')
        self.assertTrue(all(values[k] == '' for k in ('entrance_of_duty','bf_vl_balance','bf_sl_balance','bf_spl_value','bf_fl_value','bf_wl_value')))

    def test_annual_values_are_not_carried_into_next_year(self):
        values = ver2_print_fields({'name':'Name', 'spl':Decimal('2'), 'wl':Decimal('5')}, SimpleNamespace(name='Name'), {'vl':None, 'sl':Decimal('0'), 'fl':None}, date(2027,1,31))
        self.assertEqual((values['bf_period'], values['bf_vl_balance'], values['bf_sl_balance'], values['bf_spl_value'], values['bf_fl_value'], values['bf_wl_value']), ('JAN 2027','','0.000','','',''))

    def test_mone_fallback_prints_values_without_inventing_period(self):
        person = SimpleNamespace(name='EXAMPLE, PERSON')
        values = ver2_print_fields({'name':'EXAMPLE, PERSON','fallback_kind':'mone','spl':None,'wl':None},
            person, {'vl':Decimal('8.250'),'sl':Decimal('2'),'fl':None}, date(2026,10,31))
        self.assertEqual((values['bf_period'], values['bf_vl_balance'], values['bf_sl_balance']), ('','8.250','2.000'))
        self.assertEqual((values['bf_spl_value'], values['bf_fl_value'], values['bf_wl_value']), ('','',''))

    def test_missing_fallback_prints_name_without_balance_or_period(self):
        values = ver2_print_fields({'name':'EXAMPLE','fallback_kind':'missing','spl':None,'wl':None},
            SimpleNamespace(name='EXAMPLE'), None, date(2026,10,31))
        self.assertEqual((values['name'],values['bf_period'],values['bf_vl_balance'],values['bf_sl_balance']), ('EXAMPLE','','',''))

    def test_august_fallback_prints_selected_month_and_calculated_values(self):
        source = {'name':'EXAMPLE','fallback_kind':'mone','august_usable':True,'spl':None,'wl':None}
        result = {'vl':Decimal('12.500'),'sl':Decimal('17.500'),'fl':None}
        values = ver2_print_fields(source, SimpleNamespace(name='EXAMPLE'), result, date(2026,10,31))
        self.assertEqual((values['bf_period'], values['bf_vl_balance'], values['bf_sl_balance']), ('OCT 2026','12.500','17.500'))

if __name__ == '__main__':
    unittest.main()
