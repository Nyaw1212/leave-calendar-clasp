import unittest
from leave_calendar.print_queue_order import preview_queue_slots

class PrintQueueOrderTests(unittest.TestCase):
    def test_three_consecutive_entries(self):
        self.assertEqual(preview_queue_slots(['A','B','C','D'],0),[(0,'A'),(1,'B'),(2,'C')])
        self.assertEqual(preview_queue_slots(['A','B','C','D'],1),[(1,'B'),(2,'C'),(3,'D')])
    def test_end_and_empty(self):
        self.assertEqual(preview_queue_slots(['A','B','C'],2),[(2,'C')])
        self.assertEqual(preview_queue_slots([],0),[])
        self.assertEqual(preview_queue_slots(['A'],999),[(0,'A')])

if __name__=='__main__': unittest.main()
