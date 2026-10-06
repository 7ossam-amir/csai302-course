"""LSM tree: in-memory memtable, immutable SSTable files on disk, size-tiered compaction.

Keys are integers, values are bytes. A delete writes a tombstone (value None).
"""
import bisect
import heapq
import os
import struct
import threading

REC = struct.Struct("<qi")   # key, value length (-1 = tombstone), followed by the value bytes
INDEX_EVERY = 32             # one sparse-index entry per this many records (one "block")


class BloomFilter:
    """Says 'definitely not here' or 'maybe here' without touching the file."""

    def __init__(self, n, bits_per_key=10, hashes=4):
        self.m = max(64, n * bits_per_key)
        self.k = hashes
        self.bits = bytearray((self.m + 7) // 8)

    def _positions(self, key):
        h1, h2 = hash((key, 1)), hash((key, 2)) | 1
        return ((h1 + i * h2) % self.m for i in range(self.k))

    def add(self, key):
        for p in self._positions(key):
            self.bits[p >> 3] |= 1 << (p & 7)

    def __contains__(self, key):
        return all(self.bits[p >> 3] & (1 << (p & 7)) for p in self._positions(key))


class SSTable:
    """Immutable file of records sorted by key. Sparse index and Bloom filter stay in memory."""

    def __init__(self, path, items, expected):
        self.path = path
        self.bloom = BloomFilter(expected)
        self.index_keys, self.index_offs = [], []
        self.count = 0
        self.max_key = None
        self.block_reads = 0
        offset = 0
        with open(path, "wb") as f:
            for key, value in items:
                if self.count % INDEX_EVERY == 0:
                    self.index_keys.append(key)
                    self.index_offs.append(offset)
                rec = REC.pack(key, -1 if value is None else len(value)) + (value or b"")
                f.write(rec)
                offset += len(rec)
                self.bloom.add(key)
                self.count += 1
                self.max_key = key
        self.size = offset
        self.f = open(path, "rb")

    def _block(self, i):
        start = self.index_offs[i]
        end = self.index_offs[i + 1] if i + 1 < len(self.index_offs) else self.size
        self.f.seek(start)
        buf = self.f.read(end - start)
        self.block_reads += 1
        pos = 0
        while pos < len(buf):
            key, n = REC.unpack_from(buf, pos)
            pos += REC.size
            if n < 0:
                yield key, None
            else:
                yield key, buf[pos:pos + n]
                pos += n

    def get(self, key):
        """Return (found, value). found is True for a tombstone too (value None)."""
        if not self.count or key < self.index_keys[0] or key > self.max_key or key not in self.bloom:
            return False, None
        for k, v in self._block(bisect.bisect_right(self.index_keys, key) - 1):
            if k == key:
                return True, v
            if k > key:
                break
        return False, None

    def scan(self, lo=None, hi=None):
        first = 0 if lo is None else max(0, bisect.bisect_right(self.index_keys, lo) - 1)
        for b in range(first, len(self.index_offs)):
            for k, v in self._block(b):
                if hi is not None and k > hi:
                    return
                if lo is None or k >= lo:
                    yield k, v

    def close(self):
        self.f.close()

    def remove(self):
        self.f.close()
        os.remove(self.path)


def _tag(source, age):
    for k, v in source:
        yield k, age, v


def merge(sources, drop_tombstones):
    """K-way merge of sorted (key, value) streams, given newest first. Newest version wins."""
    last = None
    for k, _, v in heapq.merge(*[_tag(src, age) for age, src in enumerate(sources)]):
        if k == last:
            continue                    # an older version of a key we already emitted
        last = k
        if v is None and drop_tombstones:
            continue
        yield k, v


class LSMTree:
    def __init__(self, directory, memtable_limit=4096, fanout=4):
        os.makedirs(directory, exist_ok=True)
        self.dir = directory
        self.memtable = {}
        self.memtable_limit = memtable_limit    # entries before a flush
        self.fanout = fanout                    # tables in a level before they merge into the next
        self.levels = [[]]                      # levels[i] = SSTables, newest first; level 0 is newest
        self._seq = 0
        self._lock = threading.Lock()           # one big lock: correct, not scalable
        self.flushes = self.compactions = 0
        self.user_bytes = self.disk_bytes = 0   # disk_bytes / user_bytes = write amplification

    def _new_table(self, items, expected):
        self._seq += 1
        table = SSTable(os.path.join(self.dir, f"sst_{self._seq:06d}.dat"), items, expected)
        self.disk_bytes += table.size
        return table

    # ---- writes ----

    def put(self, key, value):
        with self._lock:
            self.memtable[key] = value
            self.user_bytes += REC.size + len(value or b"")
            if len(self.memtable) >= self.memtable_limit:
                self._flush()

    def delete(self, key):
        self.put(key, None)

    def flush(self):
        with self._lock:
            self._flush()

    def _flush(self):
        if not self.memtable:
            return
        table = self._new_table(sorted(self.memtable.items()), len(self.memtable))
        self.levels[0].insert(0, table)
        self.memtable = {}
        self.flushes += 1
        self._compact()

    def _compact(self):
        """Size-tiered: when a level holds `fanout` tables, merge them into one table a level down."""
        i = 0
        while i < len(self.levels):
            tables = self.levels[i]
            if len(tables) >= self.fanout:
                if i + 1 == len(self.levels):
                    self.levels.append([])
                # tombstones can only be dropped when nothing older could still hold the key
                bottom = not any(self.levels[i + 1:])
                merged = self._new_table(merge([t.scan() for t in tables], drop_tombstones=bottom),
                                         sum(t.count for t in tables))
                self.levels[i] = []
                if merged.count:
                    self.levels[i + 1].insert(0, merged)
                else:
                    merged.remove()
                for t in tables:
                    t.remove()
                self.compactions += 1
            i += 1

    # ---- reads ----

    def get(self, key):
        with self._lock:
            if key in self.memtable:
                return self.memtable[key]
            for level in self.levels:           # newest data first; stop at the first version found
                for table in level:
                    found, value = table.get(key)
                    if found:
                        return value
            return None

    def scan(self, lo, hi):
        with self._lock:
            sources = [sorted((k, v) for k, v in self.memtable.items() if lo <= k <= hi)]
            sources += [t.scan(lo, hi) for level in self.levels for t in level]
            return list(merge(sources, drop_tombstones=True))

    # ---- stats ----

    def table_count(self):
        return sum(len(level) for level in self.levels)

    def block_reads(self):
        return sum(t.block_reads for level in self.levels for t in level)

    def close(self):
        for level in self.levels:
            for t in level:
                t.close()
