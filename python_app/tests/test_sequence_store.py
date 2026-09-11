from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from leave_calendar.sequence_store import SequenceStore


class SequenceStoreTests(unittest.TestCase):
    def test_saved_sequences_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SequenceStore(Path(directory) / "sequences.json")
            name = store.save("My Leave Flow", ["PASTE", "TAB", "ENTER 700MS"])

            self.assertEqual(name, "My Leave Flow")
            self.assertEqual(
                store.load()[name],
                ("PASTE", "TAB", "ENTER 700MS"),
            )

    def test_saved_sequence_can_be_replaced_and_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SequenceStore(Path(directory) / "sequences.json")
            store.save("Flow", ["PASTE"])
            store.save("Flow", ["TYPE", "TAB"])
            self.assertEqual(store.load()["Flow"], ("TYPE", "TAB"))
            self.assertTrue(store.delete("Flow"))
            self.assertEqual(store.load(), {})

    def test_invalid_file_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sequences.json"
            path.write_text(json.dumps({"Bad": [], "Good": ["paste", "tab"]}))

            self.assertEqual(
                SequenceStore(path).load(),
                {"Good": ("PASTE", "TAB")},
            )


if __name__ == "__main__":
    unittest.main()
