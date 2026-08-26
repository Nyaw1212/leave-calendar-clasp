import unittest
from datetime import date

from leave_calendar.repository import parse_sheet_date, safe_sheet_text


class RepositoryHelperTests(unittest.TestCase):
    def test_parses_sheet_date_formats(self) -> None:
        expected = date(2026, 8, 10)
        self.assertEqual(parse_sheet_date("2026-08-10"), expected)
        self.assertEqual(parse_sheet_date("08/10/2026"), expected)

    def test_prevents_formula_interpretation_for_manual_text(self) -> None:
        self.assertEqual(safe_sheet_text("=IMPORTXML(...)"), "'=IMPORTXML(...)")
        self.assertEqual(safe_sheet_text("Juan Dela Cruz"), "Juan Dela Cruz")


if __name__ == "__main__":
    unittest.main()
