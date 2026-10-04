"""Shared helpers for the practice tasks (nothing to edit here).

Import this module first in every task file: it makes the lab code one folder up
(buffer_pool.py, replacers.py, row_store.py, ...) importable.
"""
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from buffer_pool import BufferPoolManager  # noqa: E402
from column_store import ColumnStore, convert_row_to_column  # noqa: E402
from disk_manager import DiskManager  # noqa: E402
from replacers import LRUReplacer  # noqa: E402
from row_store import RowStore  # noqa: E402


def db_path(name):
    return str(HERE / name)


def fresh_disk(name):
    """A new, empty page file in this folder."""
    if os.path.exists(db_path(name)):
        os.remove(db_path(name))
    return DiskManager(db_path(name))


def cold_pool(disk, size=64):
    """A fresh (empty) buffer pool, so every measurement starts from the same state."""
    return BufferPoolManager(size, disk, LRUReplacer(size))


def run_trace(replacer_cls, size, trace):
    """Request every page of the trace once and return the buffer pool (for hits/misses)."""
    disk = fresh_disk("trace.db")
    bpm = BufferPoolManager(size, disk, replacer_cls(size))
    for page_id in trace:
        bpm.fetch_page(page_id)
        bpm.unpin_page(page_id)
    disk.close()
    os.remove(db_path("trace.db"))
    return bpm


def build_stores(n_rows=20_000):
    """The lab's students table (id, name, gpa) as a row store and as a column store."""
    random.seed(7)
    rows = RowStore(cold_pool(fresh_disk("p_row.db")))
    for i in range(n_rows):
        rows.insert((i, f"student{i}", round(random.uniform(2.0, 4.0), 2)))
    rows.bpm.flush_all()
    cols = ColumnStore(cold_pool(fresh_disk("p_col.db")))
    convert_row_to_column(rows, cols)
    cols.bpm.flush_all()
    return rows, cols


def page_reads(store, fn):
    """Run fn() with a cold buffer pool; return (result, pages read from disk)."""
    disk = store.bpm.disk
    store.bpm = cold_pool(disk)
    disk.reads = 0
    result = fn()
    return result, disk.reads


def close_stores(*stores):
    for store in stores:
        path = store.bpm.disk.f.name
        store.bpm.disk.close()
        os.remove(path)
