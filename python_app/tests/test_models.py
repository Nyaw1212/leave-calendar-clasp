import unittest
from datetime import date

from leave_calendar.models import DraftEntry, LeaveDay


class DraftModelTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
