import unittest
from datetime import date

from leave_calendar.magclip_engine import (
    LeaveEntryEngine,
    Magazine,
    leave_record_rounds,
)
from leave_calendar.models import LeaveRecord


class RecordingContext:
    def __init__(self) -> None:
        self.actions: list[tuple[str, str]] = []
        self.aborted = False

    def paste_text(self, value: str) -> None:
        self.actions.append(("PASTE", value))

    def press_tab(self) -> None:
        self.actions.append(("TAB", ""))

    def press_enter(self) -> None:
        self.actions.append(("ENTER", ""))

    def press_space(self) -> None:
        self.actions.append(("SPACE", ""))

    def press_escape(self) -> None:
        self.actions.append(("ESC", ""))

    def should_abort(self) -> bool:
        return self.aborted


class IntegratedMagclipTests(unittest.TestCase):
    def test_saved_leave_becomes_name_plus_seven_leave_rounds(self) -> None:
        record = LeaveRecord(
            leave_type="Vacation Leave",
            start=date(2026, 7, 14),
            end=date(2026, 7, 16),
            status="A",
            vl=3,
            sl=0,
            lwop=0,
            record_id="record-1",
            employee_id="EMP-1",
            name="Sample",
        )

        self.assertEqual(
            leave_record_rounds(record),
            [
                "Sample",
                "Vacation Leave",
                "07/14/2026",
                "07/16/2026",
                "A",
                "3.000",
                "0.000",
                "0.000",
            ],
        )

    def test_each_history_row_is_a_clip_and_each_cell_is_a_round(self) -> None:
        magazine = Magazine()
        magazine.load(
            [
                ["Sample", "Vacation Leave", "07/14/2026", "07/16/2026", "A", "3.000", "0.000", "0.000"],
                ["Sample", "Sick Leave", "12/07/2026", "12/08/2026", "A", "0.000", "2.000", "0.000"],
            ]
        )

        self.assertEqual(len(magazine.clips), 2)
        self.assertEqual(len(magazine.clips[0].rounds), 8)
        self.assertEqual(magazine.current_field(), "NAME")
        for _ in range(8):
            magazine.advance_round()
        self.assertEqual(magazine.clip_index, 1)
        self.assertEqual(magazine.current_round().value, "Sample")
        self.assertTrue(magazine.reload_last_clip())
        self.assertEqual(magazine.clip_index, 0)

    def test_zero_lwop_does_not_paste_or_press_space(self) -> None:
        context = RecordingContext()
        engine = LeaveEntryEngine(delay_ms=0)
        values = [
            "Sample",
            "Vacation Leave",
            "07/14/2026",
            "07/16/2026",
            "A",
            "3.000",
            "0.000",
            "0.000",
        ]

        result = engine.run_rounds(context, values, 0)

        self.assertTrue(result.completed)
        self.assertEqual(
            [action for action, _value in context.actions].count("PASTE"),
            7,
        )
        self.assertNotIn(("SPACE", ""), context.actions)


if __name__ == "__main__":
    unittest.main()
