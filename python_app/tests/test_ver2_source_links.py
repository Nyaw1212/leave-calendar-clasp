import tempfile
import unittest
from pathlib import Path

from leave_calendar.ver2_balances import BalanceLinks


class SourceNameLinksTests(unittest.TestCase):
    def test_manual_name_link_is_persistent_and_removable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'balances.sqlite3'
            links = BalanceLinks(path)
            links.assign_source('  EXAMPLE,  PERSON ', 'source-a')
            self.assertEqual(BalanceLinks(path).source_links(), {'example, person': 'source-a'})
            links.remove_source('Example, Person')
            self.assertEqual(links.source_links(), {})

    def test_prevent_duplicate_claims_by_name_or_employee(self):
        with tempfile.TemporaryDirectory() as directory:
            links = BalanceLinks(Path(directory) / 'balances.sqlite3')
            links.assign_source('Person A', 'source-a')
            with self.assertRaises(ValueError):
                links.assign_source('Person B', 'source-a')
            with self.assertRaises(ValueError):
                links.assign('BIS-1', 'source-a')
            links.assign('BIS-2', 'source-b')
            with self.assertRaises(ValueError):
                links.assign_source('Person C', 'source-b')

    def test_transfer_matching_name_link_to_new_bis_id(self):
        with tempfile.TemporaryDirectory() as directory:
            links = BalanceLinks(Path(directory) / 'balances.sqlite3')
            links.assign_source('PERSON, JANE', 'source-a')
            with self.assertRaises(ValueError):
                links.assign_new_bis('ID-1', 'source-a', 'PERSON, DIFFERENT')
            self.assertEqual(links.source_links(), {'person, jane': 'source-a'})
            links.assign_new_bis('ID-1', 'source-a', 'PERSON, JANE')
            self.assertEqual(links.all(), {'ID-1': 'source-a'})
            self.assertEqual(links.source_links(), {})
            with self.assertRaises(ValueError):
                links.assign_new_bis('ID-2', 'source-a', 'PERSON, JANE')


if __name__ == '__main__':
    unittest.main()
