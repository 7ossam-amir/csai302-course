"""Row store vs column store: build a row store, convert it, then compare queries.

Run: python bench_storage.py
"""
import os
import random
import time

from buffer_pool import BufferPoolManager
from column_store import ColumnStore, convert_row_to_column
from disk_manager import DiskManager
from replacers import LRUReplacer
from row_store import RowStore

N_ROWS = 200_000


def new_disk(path):
    if os.path.exists(path):
        os.remove(path)
    return DiskManager(path)


def cold_pool(disk, size=64):
    """A fresh (empty) buffer pool, so every query starts from the same state."""
    return BufferPoolManager(size, disk, LRUReplacer(size))


def measure(name, disk, fn):
    disk.reads = 0
    t = time.perf_counter()
    result = fn()
    print(f"{name:<28}{time.perf_counter() - t:8.3f}s {disk.reads:8} page reads")
    return result


def main():
    random.seed(7)
    rdisk = new_disk("row.db")
    rows = RowStore(cold_pool(rdisk))
    t = time.perf_counter()
    for i in range(N_ROWS):
        rows.insert((i, f"student{i}", round(random.uniform(2.0, 4.0), 2)))
    rows.bpm.flush_all()
    print(f"load {N_ROWS} rows into row store: {time.perf_counter() - t:.2f}s")

    cdisk = new_disk("col.db")
    cols = ColumnStore(cold_pool(cdisk))
    t = time.perf_counter()
    convert_row_to_column(rows, cols)
    cols.bpm.flush_all()
    print(f"convert row -> column:            {time.perf_counter() - t:.2f}s\n")

    ids = [random.randrange(N_ROWS) for _ in range(1000)]
    assert rows.get_row(ids[0])[:2] == cols.get_row(ids[0])[:2]  # same data after conversion

    print(f"{'query':<28}{'time':>9} {'reads':>8}")
    rows.bpm, cols.bpm = cold_pool(rdisk), cold_pool(cdisk)
    a = measure("ROW    AVG(gpa)", rdisk, lambda: sum(r[2] for r in rows.scan()) / N_ROWS)
    b = measure("COLUMN AVG(gpa)", cdisk, lambda: sum(cols.scan_column("gpa")) / N_ROWS)
    assert abs(a - b) < 1e-6

    rows.bpm, cols.bpm = cold_pool(rdisk), cold_pool(cdisk)
    measure("ROW    1000 point lookups", rdisk, lambda: [rows.get_row(i) for i in ids])
    measure("COLUMN 1000 point lookups", cdisk, lambda: [cols.get_row(i) for i in ids])

    print(f"\npages: row={rows.num_pages}  column={cols.next_page} "
          f"(id={len(cols.pages['id'])}, name={len(cols.pages['name'])}, gpa={len(cols.pages['gpa'])})")
    rdisk.close()
    cdisk.close()
    print(f"file size: row.db={os.path.getsize('row.db') // 1024} KB  "
          f"col.db={os.path.getsize('col.db') // 1024} KB")


if __name__ == "__main__":
    main()
