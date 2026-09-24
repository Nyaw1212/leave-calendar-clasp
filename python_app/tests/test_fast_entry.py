import unittest
from datetime import date

from leave_calendar.fast_entry import (
    FastDateError,
    parse_fast_end,
    parse_fast_mandatory_vl,
    parse_fast_range,
    parse_fast_start,
    parse_fast_ut_entry,
    split_fast_leave_code,
)


class FastEntryTests(unittest.TestCase):
    def test_space_separated_start_uses_working_year(self) -> None:
        self.assertEqual(parse_fast_start("9 1", 2019), date(2019, 9, 1))

    def test_earlier_month_rolls_into_next_year(self) -> None:
        self.assertEqual(
            parse_fast_start("1 4", 2019, date(2019, 9, 1)),
            date(2020, 1, 4),
        )

    def test_later_month_stays_in_working_year(self) -> None:
        self.assertEqual(
            parse_fast_start("11 2", 2019, date(2019, 9, 1)),
            date(2019, 11, 2),
        )

    def test_day_only_end_reuses_start_month_and_year(self) -> None:
        start = date(2019, 9, 1)
        self.assertEqual(parse_fast_end("3", start), date(2019, 9, 3))

    def test_month_day_end_can_cross_new_year(self) -> None:
        start = date(2019, 12, 30)
        self.assertEqual(parse_fast_end("1 2", start), date(2020, 1, 2))

    def test_end_before_start_is_rejected(self) -> None:
        with self.assertRaises(FastDateError):
            parse_fast_end("1", date(2019, 9, 2))

    def test_one_box_range_uses_month_start_and_end_days(self) -> None:
        self.assertEqual(
            parse_fast_range("9 1 3", 2019),
            (date(2019, 9, 1), date(2019, 9, 3)),
        )

    def test_one_box_range_rolls_to_next_year(self) -> None:
        self.assertEqual(
            parse_fast_range("1 2 5", 2019, date(2019, 9, 1)),
            (date(2020, 1, 2), date(2020, 1, 5)),
        )

    def test_ss_suffix_selects_special_privilege_leave(self) -> None:
        self.assertEqual(
            split_fast_leave_code("9/1/3ss"),
            ("9/1/3", "SPL"),
        )

    def test_vs_and_sv_suffixes_switch_credit_source(self) -> None:
        self.assertEqual(split_fast_leave_code("9/1/3vs"), ("9/1/3", "VS"))
        self.assertEqual(split_fast_leave_code("9/1/3sv"), ("9/1/3", "SV"))

    def test_w_suffix_selects_wellness_leave(self) -> None:
        self.assertEqual(split_fast_leave_code("9/1/3w"), ("9/1/3", "WL"))

    def test_lone_number_is_mandatory_leave_amount(self) -> None:
        self.assertEqual(parse_fast_mandatory_vl("5"), 5.0)
        self.assertIsNone(parse_fast_mandatory_vl("m5"))

    def test_slash_range_uses_optional_end_day(self) -> None:
        self.assertEqual(
            parse_fast_range("9/1/3", 2019),
            (date(2019, 9, 1), date(2019, 9, 3)),
        )

    def test_ut_uses_month_working_year_and_two_deductions(self) -> None:
        self.assertEqual(parse_fast_ut_entry("1 u .004 0", 2026), (1, 2026, 0.004, 0.0))
        self.assertEqual(
            parse_fast_range("9/1", 2019),
            (date(2019, 9, 1), date(2019, 9, 1)),
        )

    def test_cross_month_range_uses_end_month_and_day(self) -> None:
        self.assertEqual(
            parse_fast_range("2 19 3 4", 2026),
            (date(2026, 2, 19), date(2026, 3, 4)),
        )

    def test_cross_month_range_rolls_to_next_year(self) -> None:
        self.assertEqual(
            parse_fast_range("12 29 1 4", 2026),
            (date(2026, 12, 29), date(2027, 1, 4)),
        )


if __name__ == "__main__":
    unittest.main()
