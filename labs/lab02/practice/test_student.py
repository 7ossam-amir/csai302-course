"""Public checks; complete student.py before running."""
import unittest
import tempfile
from pathlib import Path
import student
from disk_manager import DiskManager, PAGE_SIZE
from buffer_pool import BufferPoolManager
from replacers import LRUReplacer, ClockReplacer


class MemoryDisk:
    def __init__(self):
        self.reads = 0
        self.writes = 0
        self.pages = {}

    def read_page(self, page_id):
        self.reads += 1
        return self.pages.get(page_id, bytes(PAGE_SIZE))

    def write_page(self, page_id, data):
        self.writes += 1
        self.pages[page_id] = bytes(data)


class BufferPracticeTests(unittest.TestCase):
    def test_trace_accounting(self):
        for policy in (LRUReplacer, ClockReplacer):
            disk = MemoryDisk()
            trace = [0, 1, 0, 1]  # fit in memory: verifies reuse and unpin
            result = student.run_trace(disk, policy, 2, trace)
            self.assertEqual(set(result), {'hits', 'misses', 'hit_ratio'})
            self.assertEqual(result['hits'] + result['misses'], len(trace))
            self.assertEqual(result['misses'], disk.reads)
            self.assertEqual(disk.reads, len(set(trace)))
            self.assertAlmostEqual(result['hit_ratio'], result['hits'] / len(trace))
            empty = student.run_trace(MemoryDisk(), policy, 2, [])
            self.assertEqual(empty, {'hits': 0, 'misses': 0, 'hit_ratio': 0})

    def test_allows_eviction(self):
        for policy in (LRUReplacer, ClockReplacer):
            disk = MemoryDisk()
            trace = list(range(8))
            result = student.run_trace(disk, policy, 2, trace)
            self.assertEqual(result['misses'], len(trace))
            self.assertEqual(result['hits'], 0)

    def test_message_survives_reopen(self):
        # Keep disposable files beside the tests for restricted environments.
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            path = str(Path(folder) / 'pages.db')
            message = b'Lab 2 practice'
            disk = DiskManager(path)
            try:
                pool = BufferPoolManager(2, disk, ClockReplacer(2))
                student.save_message(pool, 0, message)
                self.assertEqual(pool.pin_count[pool.page_table[0]], 0)
                self.assertFalse(pool.dirty[pool.page_table[0]])
                pool.flush_all()
                self.assertEqual(disk.writes, 1)
            finally:
                disk.close()
            disk = DiskManager(path)
            try:
                pool = BufferPoolManager(2, disk, LRUReplacer(2))
                page = pool.fetch_page(0)
                self.assertEqual(len(page), PAGE_SIZE)
                self.assertEqual(page[:len(message)], message)
                pool.unpin_page(0)
            finally:
                disk.close()


class QueryTests(unittest.TestCase):
    def test_column_access_contract_and_empty(self):
        class RowInput:
            def scan(self):
                yield from [(1, 'A', 2.0), (2, 'B', 3.0), (3, 'C', 4.0)]
        class ColumnInput:
            def scan_column(self, column):
                if column != 'gpa':
                    raise AssertionError('Only GPA may be read')
                yield from [2.0, 3.0, 4.0]
        for query, store in [(student.average_gpa_row, RowInput()),
                             (student.average_gpa_column, ColumnInput())]:
            self.assertEqual(query(store, 3.0), 3.5)
            self.assertIsNone(query(store, 5.0))
        class Empty:
            def scan(self):
                return iter(())
            def scan_column(self, column):
                return iter(())
        self.assertIsNone(student.average_gpa_row(Empty(), 0))
        self.assertIsNone(student.average_gpa_column(Empty(), 0))



if __name__ == '__main__':
    unittest.main()
