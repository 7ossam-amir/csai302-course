"""Replacement policies. Every replacer exposes the same three methods:

record_access(fid)       a frame was just used
set_evictable(fid, ok)   the frame may (ok=True) or may not be evicted (pinned)
evict() -> fid | None    choose a victim frame, or None if every frame is pinned
"""
from collections import OrderedDict, deque


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
    """Evict the frame with the largest backward K-distance.

    Frames with fewer than K accesses have infinite distance and go first
    (ties broken by the oldest access).
    """

    def __init__(self, num_frames, k=2):
        self.k = k
        self.time = 0
        self.history = {}  # frame_id -> timestamps of the last K accesses
        self.evictable = {}

    def record_access(self, fid):
        self.time += 1
        self.history.setdefault(fid, deque(maxlen=self.k)).append(self.time)
        self.evictable.setdefault(fid, False)

    def set_evictable(self, fid, ok):
        if fid in self.evictable:
            self.evictable[fid] = ok

    def evict(self):
        victim, best = None, None
        for fid, h in self.history.items():
            if not self.evictable[fid]:
                continue
            # (0, t): fewer than K accesses -> infinite distance, evicted first
            # (1, t): h[0] is the K-th most recent access; older = larger distance
            key = (0, h[0]) if len(h) < self.k else (1, h[0])
            if best is None or key < best:
                victim, best = fid, key
        if victim is not None:
            del self.history[victim]
            del self.evictable[victim]
        return victim


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
