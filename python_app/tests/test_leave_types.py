import unittest

from leave_calendar.leave_types import (
    default_leave_type_options,
    normalize_shortcut,
    parse_leave_type_rows,
)


class LeaveTypeTests(unittest.TestCase):
    def test_reads_named_columns_in_any_order(self) -> None:
        options = parse_leave_type_rows(
            [
                ["Shortcut Key", "LEAVE_TYPE", "Code"],
                ["V", "Vacation Leave", "VL"],
                ["Ctrl+S", "Sick Leave", "SL"],
            ]
        )

        self.assertEqual(
            [(item.name, item.code, item.shortcut) for item in options],
            [
                ("Vacation Leave", "VL", "V"),
                ("Sick Leave", "SL", "Ctrl+S"),
            ],
        )

    def test_normalizes_leave_codes_and_shortcut_spacing(self) -> None:
        options = parse_leave_type_rows(
            [
                ["LEAVE_TYPE", "SHORTCUT"],
                ["VL", "control + v"],
                ["SL", "alt + s"],
            ]
        )

        self.assertEqual(options[0].name, "Vacation Leave")
        self.assertEqual(options[0].code, "VL")
        self.assertEqual(options[0].shortcut, "Ctrl+V")
        self.assertEqual(options[1].shortcut, "Alt+S")

    def test_preserves_sheet_labels_and_extracts_parenthetical_codes(self) -> None:
        options = parse_leave_type_rows(
            [
                ["LEAVE_TYPE", "SHORTCUT KEY"],
                ["Vacation Leave (VL)", "1"],
                ["Mandatory / Forced Leave (FL)", "2"],
                ["Solo Parent Leave", "7"],
            ]
        )

        self.assertEqual(options[0].display_name, "Vacation Leave (VL)")
        self.assertEqual((options[0].name, options[0].code), ("Vacation Leave", "VL"))
        self.assertEqual((options[1].name, options[1].code), ("Forced Leave", "FL"))
        self.assertEqual(options[2].name, "Solo Parent Leave")
        self.assertEqual(options[2].display_name, "Solo Parent Leave")

    def test_empty_tab_uses_current_leave_types_without_guessing_shortcuts(self) -> None:
        options = parse_leave_type_rows([])

        self.assertEqual(options, default_leave_type_options())
        self.assertTrue(all(not item.shortcut for item in options))

    def test_shortcut_aliases_are_portable(self) -> None:
        self.assertEqual(normalize_shortcut(" win + 1 "), "Meta+1")
        self.assertEqual(normalize_shortcut("shift + f2"), "Shift+F2")


if __name__ == "__main__":
    unittest.main()
