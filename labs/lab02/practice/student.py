"""Lab 2 coding task. Replace TODOs; preserve public signatures."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FIFOReplacer:
    """Same interface as lab02 replacers; queue order is first admission order."""
    def __init__(self, num_frames):
        # TODO: create your queue and evictability tracking.
        raise NotImplementedError

    def record_access(self, fid):
        # TODO: admit unseen frames; hits must not change FIFO order.
        raise NotImplementedError

    def set_evictable(self, fid, ok):
        # TODO: change eligibility, preserving queue order.
        raise NotImplementedError

    def evict(self):
        # TODO: remove oldest eligible frame, or return None.
        raise NotImplementedError


class StudentBufferPool:
    def __init__(self, pool_size, disk, replacer):
        if pool_size <= 0:
            raise ValueError("pool_size must be positive")
        self.disk = disk
        self.replacer = replacer
        self.frames = [None] * pool_size
        self.frame_page = [None] * pool_size
        self.pin_count = [0] * pool_size
        self.dirty = [False] * pool_size
        self.page_table = {}
        self.free_frames = list(range(pool_size))
        self.hits = self.misses = 0

    def fetch_page(self, page_id):
        """Return mutable page bytes and acquire one pin; count hit or miss."""
        # TODO: hit path, miss path, disk load, pin and replacer updates.
        raise NotImplementedError

    def _get_free_frame(self):
        """Use a free frame, or evict an unpinned frame with dirty write-back."""
        # TODO: update the old mapping and reset frame state before reuse.
        raise NotImplementedError

    def unpin_page(self, page_id, is_dirty=False):
        """Release one pin. Reject missing pages and repeated unpins."""
        # TODO: KeyError for absent page; ValueError for pin count already zero.
        # Dirty state accumulates until a successful flush/write-back.
        raise NotImplementedError

    def flush_all(self):
        """Write dirty resident pages and clear their dirty flags."""
        # TODO: do not evict pages or change pins; skip clean pages.
        raise NotImplementedError

    def hit_ratio(self):
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


def average_gpa_row(store, minimum):
    """AVG(gpa) WHERE gpa >= minimum; return None when no values qualify."""
    # TODO: consume RowStore.scan(); use constant extra space.
    raise NotImplementedError


def average_gpa_column(store, minimum):
    """Same query, reading ONLY the GPA column."""
    # TODO: consume ColumnStore.scan_column('gpa'); do not reconstruct rows.
    raise NotImplementedError
