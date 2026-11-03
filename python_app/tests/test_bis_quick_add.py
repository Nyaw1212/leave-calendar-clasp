import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook
from leave_calendar.local_repository import LocalRepository, LocalRepositoryError


class BisQuickAddTests(unittest.TestCase):
    def test_add_and_reimport_preserves_manual_employee_and_blocks_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = LocalRepository(Path(directory) / 'local.db')
            repository.connect()
            try:
                repository.add_bis_personnel('001-1', 'EXAMPLE, PERSON', 'CO1', '', 'Office')
                with self.assertRaises(LocalRepositoryError):
                    repository.add_bis_personnel('001-1', 'OTHER, NAME')
                with self.assertRaises(LocalRepositoryError):
                    repository.add_bis_personnel('002', 'example, person')
                workbook = Workbook()
                sheet = workbook.active
                sheet.append(['Employee', 'employee_number'])
                sheet.append(['ANOTHER, PERSON', '002'])
                path = Path(directory) / 'bis.xlsx'
                workbook.save(path)
                self.assertEqual(repository.import_bis_personnel(path), 2)
                self.assertEqual({p.employee_number for p in repository.bis_personnel()}, {'001-1', '002'})
                sheet.append(['DIFFERENT, PERSON', '001-1'])
                workbook.save(path)
                with self.assertRaises(LocalRepositoryError):
                    repository.import_bis_personnel(path)
                self.assertEqual({p.employee_number for p in repository.bis_personnel()}, {'001-1', '002'})
            finally:
                repository._db().close()


if __name__ == '__main__':
    unittest.main()
