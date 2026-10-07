"""Public acceptance tests: failures are expected until TODOs are implemented."""
import tempfile
import unittest
from pathlib import Path
import student
from disk_manager import DiskManager, PAGE_SIZE
from replacers import LRUReplacer
from buffer_pool import BufferPoolManager
from row_store import RowStore
from column_store import ColumnStore


class FIFOTests(unittest.TestCase):
    def test_hits_do_not_reorder(self):
        r = student.FIFOReplacer(3)
        for fid in [0, 1, 2, 0]:
            r.record_access(fid)
            r.set_evictable(fid, True)
        self.assertEqual([r.evict(), r.evict(), r.evict(), r.evict()], [0, 1, 2, None])

    def test_pins_and_reuse(self):
        r = student.FIFOReplacer(2)
        r.record_access(0)
        r.record_access(1)
        self.assertIsNone(r.evict())
        r.set_evictable(1, True)
        self.assertEqual(r.evict(), 1)
        r.record_access(1)
        r.set_evictable(1, True)
        r.set_evictable(0, True)
        self.assertEqual(r.evict(), 0)
        self.assertEqual(r.evict(), 1)


class BufferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.disk = DiskManager(str(Path(self.temp.name) / 'pages.db'))

    def tearDown(self):
        self.disk.close()
        self.temp.cleanup()

    def pool(self, size):
        return student.StudentBufferPool(size, self.disk, LRUReplacer(size))

    def test_trace(self):
        pool = self.pool(3)
        for page_id in [0, 1, 2, 0, 3, 1]:
            pool.fetch_page(page_id)
            pool.unpin_page(page_id)
        self.assertEqual((pool.hits, pool.misses, self.disk.reads), (1, 5, 5))
        self.assertAlmostEqual(pool.hit_ratio(), 1 / 6)
        self.assertEqual(set(pool.page_table), {0, 1, 3})

    def test_multiple_pins(self):
        pool = self.pool(1)
        first = pool.fetch_page(0)
        self.assertIs(first, pool.fetch_page(0))
        pool.unpin_page(0)
        with self.assertRaises(RuntimeError):
            pool.fetch_page(1)
        self.assertIn(0, pool.page_table)
        pool.unpin_page(0)
        self.assertEqual(pool.fetch_page(1), bytearray(PAGE_SIZE))
        self.assertNotIn(0, pool.page_table)

    def test_dirty_eviction_and_reload(self):
        pool = self.pool(1)
        pool.fetch_page(7)[:5] = b'hello'
        pool.unpin_page(7, True)
        pool.fetch_page(7)
        pool.unpin_page(7, False)  # must not erase an existing dirty flag
        pool.fetch_page(8)
        pool.unpin_page(8)
        self.assertEqual(self.disk.writes, 1)
        self.assertEqual(pool.fetch_page(7)[:5], b'hello')
        self.assertEqual(pool.frame_page[pool.page_table[7]], 7)

    def test_flush_is_idempotent_and_preserves_pins(self):
        pool = self.pool(2)
        self.assertEqual(pool.hit_ratio(), 0)
        pool.fetch_page(0)[0] = 42
        pool.unpin_page(0, True)
        pool.fetch_page(1)
        pool.flush_all()
        pool.flush_all()
        self.assertEqual(self.disk.writes, 1)
        self.assertEqual(pool.pin_count[pool.page_table[1]], 1)
        self.assertEqual(len(pool.page_table), 2)
        self.assertFalse(any(pool.dirty))

    def test_invalid_unpin(self):
        pool = self.pool(1)
        with self.assertRaises(KeyError):
            pool.unpin_page(9)
        pool.fetch_page(0)
        pool.unpin_page(0)
        with self.assertRaises(ValueError):
            pool.unpin_page(0)
        self.assertEqual(pool.pin_count[pool.page_table[0]], 0)


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

    def test_real_stores_and_cold_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            disks = [DiskManager(str(Path(folder) / name)) for name in ['row.db', 'col.db']]
            try:
                pools = [BufferPoolManager(8, d, LRUReplacer(8)) for d in disks]
                row, col = RowStore(pools[0]), ColumnStore(pools[1])
                for i in range(1500):
                    value = (i, f'S{i}', float(i % 5))
                    row.insert(value)
                    col.insert(value)
                for pool in pools:
                    pool.flush_all()
                # New pools, same files and in-memory store metadata: cold DB buffers.
                row.bpm, col.bpm = [BufferPoolManager(8, d, LRUReplacer(8)) for d in disks]
                before = [d.reads for d in disks]
                self.assertEqual(student.average_gpa_row(row, 3), 3.5)
                self.assertEqual(student.average_gpa_column(col, 3), 3.5)
                reads = [d.reads - n for d, n in zip(disks, before)]
                self.assertEqual(reads, [11, 2])
            finally:
                for disk in disks:
                    disk.close()


if __name__ == '__main__':
    unittest.main()
