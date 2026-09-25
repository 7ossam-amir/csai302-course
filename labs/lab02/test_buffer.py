"""Sanity checks for the buffer pool and every replacer. Run: python test_buffer.py"""
import os

from buffer_pool import BufferPoolManager
from disk_manager import PAGE_SIZE, DiskManager
from replacers import ClockReplacer, LRUKReplacer, LRUReplacer, TwoQReplacer


def fresh_disk(path="test.db"):
    if os.path.exists(path):
        os.remove(path)
    return DiskManager(path)


def run_trace(replacer_cls, size, trace):
    bpm = BufferPoolManager(size, fresh_disk(), replacer_cls(size))
    for p in trace:
        bpm.fetch_page(p)
        bpm.unpin_page(p)
    bpm.disk.close()
    return bpm


# LRU example from the explanation: A B C A D B -> 1 hit, 5 misses
bpm = run_trace(LRUReplacer, 3, [0, 1, 2, 0, 3, 1])
assert (bpm.hits, bpm.misses) == (1, 5), (bpm.hits, bpm.misses)
print("LRU trace ok")

# LRU-2 example: A B A C B then D -> evicts C (seen once), keeps A
r = LRUKReplacer(3, k=2)
for fid in [0, 1, 0, 2, 1]:  # A=0, B=1, C=2
    r.record_access(fid)
    r.set_evictable(fid, True)
assert r.evict() == 2
print("LRU-K picks the one-time page ok")

# Clock example: A(1) B(0) C(1), hand at A -> evicts B
c = ClockReplacer(3)
for fid in range(3):
    c.record_access(fid)
    c.set_evictable(fid, True)
c.ref[1] = 0
assert c.evict() == 1
print("Clock second chance ok")

# Sequential flooding: hot pages 0,1 then a scan of 10..12 with 3 frames
flood = [0, 1, 0, 1, 10, 11, 12, 0, 1]
for cls in (LRUReplacer, ClockReplacer, LRUKReplacer, TwoQReplacer):
    bpm = run_trace(cls, 3, flood)
    print(f"  flooding {cls.__name__:<14} hits={bpm.hits}")

# Pinned pages are never evicted
bpm = BufferPoolManager(2, fresh_disk(), LRUReplacer(2))
bpm.fetch_page(0)
bpm.fetch_page(1)
try:
    bpm.fetch_page(2)
    raise AssertionError("should fail: all frames pinned")
except RuntimeError:
    print("pinned pages protected ok")
bpm.disk.close()

# Dirty pages are written back
bpm = BufferPoolManager(2, fresh_disk(), LRUReplacer(2))
page = bpm.fetch_page(7)
page[0:5] = b"hello"
bpm.unpin_page(7, is_dirty=True)
for p in (8, 9):  # force page 7 out
    bpm.fetch_page(p)
    bpm.unpin_page(p)
assert bpm.disk.read_page(7)[:5] == b"hello"
assert len(bpm.disk.read_page(7)) == PAGE_SIZE
bpm.disk.close()
print("dirty write-back ok")

os.remove("test.db")
print("\nall tests passed")
