import tempfile
import unittest
from pathlib import Path

from leave_calendar.card_attachment_store import CardAttachmentStore


class CardAttachmentStoreTests(unittest.TestCase):
    def test_attachment_uses_employee_folder_and_stable_id_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "NBP Leave Records"
            source = Path(temporary_directory) / "source-card.pdf"
            source.write_bytes(b"leave card")
            store = CardAttachmentStore(root)

            attached = store.attach("2550-1018", "ROBISO", source)

            self.assertEqual(attached.name, "Leave Card.pdf")
            self.assertEqual(attached.parent.name, "2550-1018 - ROBISO")
            self.assertEqual(store.path_for("2550-1018", "Changed Name"), attached)


if __name__ == "__main__":
    unittest.main()
