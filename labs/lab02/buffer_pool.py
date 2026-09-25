class BufferPoolManager:
    """Keeps a fixed number of pages in memory (frames) on top of a disk manager.

    Works with any disk manager that has read_page/write_page (plain or encrypted)
    and any replacer from replacers.py.
    """

    def __init__(self, pool_size, disk, replacer):
        self.disk = disk
        self.replacer = replacer
        self.frames = [None] * pool_size
        self.frame_page = [None] * pool_size  # which page lives in each frame
        self.pin_count = [0] * pool_size
        self.dirty = [False] * pool_size
        self.page_table = {}  # page_id -> frame_id
        self.free_frames = list(range(pool_size))
        self.hits = 0
        self.misses = 0

    def fetch_page(self, page_id):
        if page_id in self.page_table:
            self.hits += 1
            fid = self.page_table[page_id]
        else:
            self.misses += 1
            fid = self._get_free_frame()
            self.frames[fid] = bytearray(self.disk.read_page(page_id))
            self.frame_page[fid] = page_id
            self.page_table[page_id] = fid
        self.pin_count[fid] += 1
        self.replacer.record_access(fid)
        self.replacer.set_evictable(fid, False)
        return self.frames[fid]

    def _get_free_frame(self):
        if self.free_frames:
            return self.free_frames.pop()
        fid = self.replacer.evict()
        if fid is None:
            raise RuntimeError("all frames are pinned, nothing can be evicted")
        old_page = self.frame_page[fid]
        if self.dirty[fid]:
            self.disk.write_page(old_page, bytes(self.frames[fid]))
            self.dirty[fid] = False
        del self.page_table[old_page]
        return fid

    def unpin_page(self, page_id, is_dirty=False):
        fid = self.page_table[page_id]
        if is_dirty:
            self.dirty[fid] = True
        self.pin_count[fid] -= 1
        if self.pin_count[fid] == 0:
            self.replacer.set_evictable(fid, True)

    def flush_all(self):
        for page_id, fid in self.page_table.items():
            if self.dirty[fid]:
                self.disk.write_page(page_id, bytes(self.frames[fid]))
                self.dirty[fid] = False

    def hit_ratio(self):
        total = self.hits + self.misses
        return self.hits / total if total else 0.0
