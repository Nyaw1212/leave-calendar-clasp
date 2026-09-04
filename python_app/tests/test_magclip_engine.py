import unittest
from datetime import date
from unittest.mock import patch

from leave_calendar.magclip_engine import (
    DEFAULT_SEQUENCE,
    LeaveEntryEngine,
    Magazine,
    POCES_APPOVE_SEQUENCE,
    SEQUENCE_PRESETS,
    action_consumes_round,
    leave_record_rounds,
)
from leave_calendar.models import LeaveRecord


class RecordingContext:
    def __init__(self) -> None:
        self.actions: list[tuple[str, str]] = []
        self.aborted = False

    def paste_text(self, value: str) -> None:
        self.actions.append(("PASTE", value))

    def type_text(self, value: str) -> None:
        self.actions.append(("TYPE", value))

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
    def test_saved_leave_starts_with_name_and_ends_with_status(self) -> None:
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
                "3.000",
                "0.000",
                "0.000",
                "A",
            ],
        )

    def test_each_history_row_is_a_clip_and_each_cell_is_a_round(self) -> None:
        magazine = Magazine()
        magazine.load(
            [
                ["Sample", "Vacation Leave", "07/14/2026", "07/16/2026", "3.000", "0.000", "0.000", "A"],
                ["Sample", "Sick Leave", "12/07/2026", "12/08/2026", "0.000", "2.000", "0.000", "A"],
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
            "3.000",
            "0.000",
            "0.000",
            "A",
        ]

        result = engine.run_rounds(context, values, 0)

        self.assertTrue(result.completed)
        self.assertEqual(
            [action for action, _value in context.actions].count("PASTE"),
            7,
        )
        self.assertNotIn(("SPACE", ""), context.actions)

    def test_requested_sequence_pastes_name_first_and_finishes_status(self) -> None:
        context = RecordingContext()
        engine = LeaveEntryEngine(delay_ms=0)
        values = [
            "Sample",
            "Vacation Leave",
            "07/14/2026",
            "07/16/2026",
            "3.000",
            "0.000",
            "0.000",
            "A",
        ]

        result, consumed = engine.run_sequence(
            context,
            values,
            0,
            list(DEFAULT_SEQUENCE),
        )

        self.assertTrue(result.completed)
        self.assertEqual(consumed, 8)
        self.assertEqual(len(DEFAULT_SEQUENCE), 25)
        self.assertEqual(
            [action for action, _value in context.actions].count("PASTE"),
            6,
        )
        self.assertEqual(
            next(value for action, value in context.actions if action == "PASTE"),
            "Sample",
        )
        self.assertIn(("TYPE", "A"), context.actions)
        self.assertNotIn(("SPACE", ""), context.actions)

        lwop_context = RecordingContext()
        values[-2] = "1.000"
        result, consumed = engine.run_sequence(
            lwop_context,
            values,
            0,
            list(DEFAULT_SEQUENCE),
        )
        self.assertTrue(result.completed)
        self.assertEqual(consumed, 8)
        self.assertEqual(
            [action for action, _value in lwop_context.actions].count("SPACE"),
            1,
        )

    def test_poces_appove_preset_types_literal_p_without_consuming_round(self) -> None:
        context = RecordingContext()
        engine = LeaveEntryEngine(delay_ms=0)
        values = [
            "Sample",
            "Forced Leave",
            "03/02/2026",
            "03/03/2026",
            "2.000",
            "0.000",
            "0.000",
            "A",
        ]

        with patch("leave_calendar.magclip_engine.time.sleep") as sleep:
            result, consumed = engine.run_sequence(
                context,
                values,
                0,
                list(POCES_APPOVE_SEQUENCE),
            )

        self.assertTrue(result.completed)
        self.assertEqual(consumed, 8)
        self.assertEqual(len(POCES_APPOVE_SEQUENCE), 26)
        self.assertEqual(SEQUENCE_PRESETS["POCES APPOVE"], POCES_APPOVE_SEQUENCE)
        self.assertEqual(POCES_APPOVE_SEQUENCE[:2], ("ENTER 400MS", "PASTE 400MS"))
        self.assertEqual(sleep.call_args_list[0].args[0], 0.4)
        self.assertEqual(sleep.call_args_list[1].args[0], 0.4)
        self.assertIn(("TYPE", "P"), context.actions)
        self.assertIn(("TYPE", "A"), context.actions)
        self.assertFalse(action_consumes_round("TYPE P"))
        self.assertFalse(action_consumes_round("TYPE A"))
        self.assertTrue(action_consumes_round("PASTE 400MS"))
        self.assertEqual(
            next(value for action, value in context.actions if action == "PASTE"),
            "Sample",
        )


if __name__ == "__main__":
    unittest.main()
