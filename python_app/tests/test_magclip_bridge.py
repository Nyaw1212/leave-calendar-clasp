import json
import tempfile
import unittest
from pathlib import Path

from leave_calendar.magclip_bridge import rows_to_tsv, send_to_magclip


class MagclipBridgeTests(unittest.TestCase):
    def test_writes_atomic_magazine_payload(self) -> None:
        rows = [
            [
                "Vacation Leave",
                "08/10/2026",
                "08/11/2026",
                "A",
                "2.000",
                "0.000",
                "0.000",
            ]
        ]
        with tempfile.TemporaryDirectory() as folder:
            destination = send_to_magclip(
                rows,
                employee_id="EMP-001",
                employee_name="Juan Dela Cruz",
                inbox=Path(folder),
            )
            payload = json.loads(destination.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema"], "magclip.magazine/v1")
        self.assertEqual(payload["workflow"], "leave_entry")
        self.assertEqual(payload["rows"], rows)
        self.assertEqual(payload["employee"]["name"], "Juan Dela Cruz")

    def test_tsv_fallback_preserves_seven_fields(self) -> None:
        rows = [["VL", "A", "B", "A", "1", "0", "0"]]
        self.assertEqual(rows_to_tsv(rows), "VL\tA\tB\tA\t1\t0\t0")


if __name__ == "__main__":
    unittest.main()
