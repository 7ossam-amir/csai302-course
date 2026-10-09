"""Lab 2 Practice: use the existing LRU/Clock policies and buffer pool."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from buffer_pool import BufferPoolManager


def run_trace(disk, replacer_cls, pool_size, trace):
    """Return {'hits': ..., 'misses': ..., 'hit_ratio': ...}.
    The caller provides a fresh disk and is responsible for closing it.
    """
    pool = BufferPoolManager(pool_size, disk, replacer_cls(pool_size))
    # TODO: fetch and unpin each page in trace.
    # TODO: return the statistics dictionary.
    raise NotImplementedError


def save_message(pool, page_id, message):
    """Write message bytes at the start of a page, unpin as dirty, then flush.
    The caller provides a bytes message no longer than one page.
    """
    # TODO: fetch the page, modify its prefix, unpin as dirty, flush.
    raise NotImplementedError


def average_gpa_row(store, minimum):
    """Average qualifying GPA values from row tuples; None if none qualify."""
    total = 0.0
    count = 0
    # TODO: loop over store.scan(), check GPA, update total and count.
    # TODO: return the average, or None when count is zero.
    raise NotImplementedError


def average_gpa_column(store, minimum):
    """Average qualifying values from the GPA column only."""
    total = 0.0
    count = 0
    # TODO: loop over store.scan_column('gpa') and apply the same condition.
    # TODO: return the average, or None when count is zero.
    raise NotImplementedError
