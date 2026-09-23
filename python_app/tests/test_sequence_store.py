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

    def test_full_flow_stage_presets_are_saved_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SequenceStore(Path(directory) / "sequences.json")
            store.save_stage_preset("credits", "CREDITS")
            store.save_stage_preset("mone", "good mone")
            store.save_stage_preset("mandatory", "good man")
            store.save_stage_preset("leave", "V4")

            self.assertEqual(
                store.load_stage_presets(),
                {
                    "credits": "CREDITS",
                    "mone": "good mone",
                    "mandatory": "good man",
                    "leave": "V4",
                },
            )

    def test_old_leave_default_migrates_to_full_flow_leave_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SequenceStore(Path(directory) / "sequences.json")
            store.save_default("V4")

            self.assertEqual(store.load_stage_presets(), {"leave": "V4"})


if __name__ == "__main__":
    unittest.main()
