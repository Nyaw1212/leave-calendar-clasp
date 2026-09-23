import unittest
from datetime import date

from leave_calendar.mone import MONE_PRESETS


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
            ("MC# 14-99", date(2014, 3, 20), date(2014, 3, 30)),
            keys,
        )


if __name__ == "__main__":
    unittest.main()
