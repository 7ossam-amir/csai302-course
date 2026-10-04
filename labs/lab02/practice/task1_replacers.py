"""Task 1 - two more replacement policies: FIFO and LFU.

Both classes must offer the same three methods as the replacers in ../replacers.py,
so the buffer pool can use them without any change:

record_access(fid)       a frame was just used
set_evictable(fid, ok)   the frame may (ok=True) or may not be evicted (pinned)
evict() -> fid | None    choose a victim frame, or None if every frame is pinned

Check: python check.py 1
"""
import common  # noqa: F401  (makes the lab code importable)


class FIFOReplacer:
    """Evict the frame that ENTERED the buffer pool first.

    Using a frame again does not move it: only the arrival order matters.
    After a frame is evicted it is forgotten, so its next access is a new arrival.
    """

    def __init__(self, num_frames):
        # TODO: choose a data structure that remembers the arrival order
        # and whether each frame is evictable.
        raise NotImplementedError("Task 1: FIFOReplacer.__init__")

    def record_access(self, fid):
        # TODO: a frame seen for the first time joins the end of the queue (not evictable yet).
        # A frame that is already in the queue stays where it is.
        raise NotImplementedError("Task 1: FIFOReplacer.record_access")

    def set_evictable(self, fid, ok):
        # TODO
        raise NotImplementedError("Task 1: FIFOReplacer.set_evictable")

    def evict(self):
        # TODO: return the oldest evictable frame and forget it; None if there is none.
        raise NotImplementedError("Task 1: FIFOReplacer.evict")


class LFUReplacer:
    """Evict the frame that was used the FEWEST times.

    Tie (same number of uses): evict the one whose last use is the oldest.
    After a frame is evicted its counter is forgotten (the next page in it starts from 0).
    """

    def __init__(self, num_frames):
        # TODO: per frame you need a use counter, the time of the last use,
        # and whether it is evictable.
        raise NotImplementedError("Task 1: LFUReplacer.__init__")

    def record_access(self, fid):
        # TODO
        raise NotImplementedError("Task 1: LFUReplacer.record_access")

    def set_evictable(self, fid, ok):
        # TODO
        raise NotImplementedError("Task 1: LFUReplacer.set_evictable")

    def evict(self):
        # TODO: smallest counter wins; on a tie the oldest last use wins.
        raise NotImplementedError("Task 1: LFUReplacer.evict")
