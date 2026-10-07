"""Replacement policies. Every replacer exposes the same three methods:

record_access(fid)       a frame was just used
set_evictable(fid, ok)   the frame may (ok=True) or may not be evicted (pinned)
evict() -> fid | None    choose a victim frame, or None if every frame is pinned
"""
from collections import OrderedDict


class LRUReplacer:
    """Evict the frame that was used least recently."""

    def __init__(self, num_frames):
        self.order = OrderedDict()  # frame_id -> evictable, oldest first

    def record_access(self, fid):
        if fid in self.order:
            self.order.move_to_end(fid)
        else:
            self.order[fid] = False

    def set_evictable(self, fid, ok):
        if fid in self.order:
            self.order[fid] = ok

    def evict(self):
        for fid, ok in self.order.items():
            if ok:
                del self.order[fid]
                return fid
        return None


class ClockReplacer:
    """Second chance: the hand clears ref bits that are 1 and evicts the first 0."""

    def __init__(self, num_frames):
        self.n = num_frames
        self.ref = [0] * num_frames
        self.evictable = [False] * num_frames
        self.present = [False] * num_frames
        self.hand = 0

    def record_access(self, fid):
        self.present[fid] = True
        self.ref[fid] = 1

    def set_evictable(self, fid, ok):
        self.evictable[fid] = ok

    def evict(self):
        if not any(p and e for p, e in zip(self.present, self.evictable)):
            return None
        while True:
            fid = self.hand
            self.hand = (self.hand + 1) % self.n
            if self.present[fid] and self.evictable[fid]:
                if self.ref[fid]:
                    self.ref[fid] = 0
                else:
                    self.present[fid] = False
                    return fid


class LRUKReplacer:
    """Approximate LRU-K with probationary Old and protected Young lists.

    A frame enters Old on its first access. Its Kth access promotes it to
    Young. Young is kept at roughly 62.5% of the pool; when it grows beyond
    that target, its least-recent frame is demoted to the newest end of Old.
    Eviction scans the oldest evictable Old frame first, then Young.

    OrderedDicts run oldest -> newest, the reverse of the lecture diagram's
    left-to-right newest -> oldest presentation. The class name stays
    LRUKReplacer so it remains compatible with the lab's buffer manager.
    """

    def __init__(self, num_frames, k=2, old_list_fraction=0.375):
        if num_frames < 1:
            raise ValueError("num_frames must be positive")
        if k < 1:
            raise ValueError("k must be positive")
        if not 0 < old_list_fraction < 1:
            raise ValueError("old_list_fraction must be between 0 and 1")

        self.k = k
        self.old_target = min(
            num_frames, max(1, int(num_frames * old_list_fraction + 0.5))
        )
        self.young_target = num_frames - self.old_target
        self.old = OrderedDict()    # frame_id -> evictable, oldest first
        self.young = OrderedDict()  # frame_id -> evictable, oldest first
        self.old_accesses = {}      # accesses while a frame is in Old

    def _demote_oldest_young(self):
        while len(self.young) > self.young_target:
            fid, evictable = self.young.popitem(last=False)
            self.old[fid] = evictable
            # A demoted frame starts a fresh probationary period in Old.
            self.old_accesses[fid] = 1

    def record_access(self, fid):
        if fid in self.young:
            self.young.move_to_end(fid)
            return

        if fid in self.old:
            self.old_accesses[fid] += 1
            if self.old_accesses[fid] >= self.k and self.young_target > 0:
                evictable = self.old.pop(fid)
                del self.old_accesses[fid]
                self.young[fid] = evictable
                self._demote_oldest_young()
            else:
                self.old.move_to_end(fid)
            return

        # A new frame gets one probationary access in Old. For K=1 it can
        # enter Young immediately, provided Young has a nonzero target.
        if self.k == 1 and self.young_target > 0:
            self.young[fid] = False
            self._demote_oldest_young()
        else:
            self.old[fid] = False
            self.old_accesses[fid] = 1

    def set_evictable(self, fid, ok):
        for queue in (self.old, self.young):
            if fid in queue:
                queue[fid] = ok
                return

    def evict(self):
        for queue in (self.old, self.young):
            for fid, evictable in queue.items():
                if evictable:
                    del queue[fid]
                    self.old_accesses.pop(fid, None)
                    return fid
        return None


class TwoQReplacer:
    """Simplified 2Q: new frames enter A1 (FIFO); a second access promotes to Am (LRU).

    Victims are taken from A1 first, so one-time pages (scans) cannot push out
    frequently used pages that live in Am.
    """

    def __init__(self, num_frames):
        self.a1 = OrderedDict()
        self.am = OrderedDict()

    def record_access(self, fid):
        if fid in self.am:
            self.am.move_to_end(fid)
        elif fid in self.a1:
            self.am[fid] = self.a1.pop(fid)
        else:
            self.a1[fid] = False

    def set_evictable(self, fid, ok):
        for q in (self.a1, self.am):
            if fid in q:
                q[fid] = ok

    def evict(self):
        for q in (self.a1, self.am):
            for fid, ok in q.items():
                if ok:
                    del q[fid]
                    return fid
        return None
