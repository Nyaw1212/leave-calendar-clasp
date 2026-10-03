import unittest
from datetime import date

from leave_calendar.mone import MONE_PRESETS, suggest_mone_credits


class MonePresetTests(unittest.TestCase):
    def test_register_contains_recent_fixed_order_periods(self) -> None:
        keys = {preset.key for preset in MONE_PRESETS}

        self.assertIn(
            ("MC# 41-98", date(2023, 11, 1), date(2023, 11, 30)),
            keys,
        )
        self.assertIn(
            ("MC# 41-98", date(2025, 11, 16), date(2025, 11, 30)),
            keys,
        )
        self.assertIn(
            ("MC# 16", date(2020, 8, 1), date(2020, 8, 30)),
            keys,
        )
        self.assertIn(
            ("MC# 16", date(2021, 6, 1), date(2021, 7, 20)),
            keys,
        )
        self.assertIn(
            ("MC# 14-99", date(2014, 3, 20), date(2014, 3, 30)),
            keys,
        )

    def test_suggested_mone_uses_sl_first_with_whole_five_day_blocks(self) -> None:
        suggestion = suggest_mone_credits(22, 18)

        self.assertEqual(suggestion.target, 25)
        self.assertEqual(suggestion.msl, 10)
        self.assertEqual(suggestion.mvl, 15)

    def test_automatic_mone_uses_the_next_lower_approved_level(self) -> None:
        suggestion = suggest_mone_credits(15, 13)

        self.assertEqual(suggestion.target, 15)
        self.assertEqual(suggestion.msl, 5)
        self.assertEqual(suggestion.mvl, 10)

    def test_requested_mone_overrides_the_auto_ladder_but_stays_safe(self) -> None:
        suggestion = suggest_mone_credits(20, 20, requested=31)

        self.assertEqual(suggestion.target, 30)
        self.assertEqual(suggestion.msl, 15)
        self.assertEqual(suggestion.mvl, 15)
        self.assertTrue(suggestion.is_requested_limited)

    def test_requested_mone_is_rounded_down_to_a_whole_five_day_block(self) -> None:
        suggestion = suggest_mone_credits(30, 30, requested=27)

        self.assertEqual(suggestion.target, 25)
        self.assertEqual(suggestion.msl, 25)
        self.assertEqual(suggestion.mvl, 0)


if __name__ == "__main__":
    unittest.main()
