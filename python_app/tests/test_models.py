import unittest
from datetime import date

from leave_calendar.models import DraftEntry, Holiday, LeaveDay, LeaveRecord, SaveResult


class DraftModelTests(unittest.TestCase):
    def test_saved_record_exposes_dates_days_and_total_credit(self) -> None:
        record = LeaveRecord(
            leave_type="Vacation Leave (VL)",
            start=date(2026, 8, 10),
            end=date(2026, 8, 12),
            vl=2.0,
            sl=0.0,
            lwop=1.0,
            record_id="record-1",
            employee_id="EMP-1",
            name="Sample Employee",
        )

        self.assertEqual(record.day_count, 3)
        self.assertEqual(record.total_credits, 3.0)
        self.assertEqual(
            record.calendar_dates,
            (date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)),
        )

    def test_draft_round_trip(self) -> None:
        original = DraftEntry(
            entry_id="entry-1",
            leave_type="Vacation Leave",
            days=(LeaveDay(date(2026, 8, 10), 1), LeaveDay(date(2026, 8, 11), 0.5)),
            remarks="Historical",
        )
        restored = DraftEntry.from_dict(original.to_dict())
        self.assertEqual(restored, original)
        self.assertEqual(restored.total_credits, 1.5)

    def test_save_result_warns_when_existing_dates_are_written_again(self) -> None:
        result = SaveResult(
            rows_written=1,
            dates_added=2,
            existing_dates_written=1,
            zero_credit_dates=0,
        )
        self.assertIn("already recorded", result.message)
        self.assertIn("saved again", result.message)

    def test_holiday_type_aliases_are_classified_for_calendar_colors(self) -> None:
        regular = Holiday(date(2023, 8, 28), "Heroes Day", "Regular Holiday")
        non_working = Holiday(date(2023, 8, 21), "Ninoy Day", "Special Non-Working Day")
        working = Holiday(date(2023, 7, 27), "INC Day", "Special Working Holiday")

        self.assertTrue(regular.is_regular)
        self.assertTrue(non_working.is_special_non_working)
        self.assertTrue(working.is_special_working)


if __name__ == "__main__":
    unittest.main()
