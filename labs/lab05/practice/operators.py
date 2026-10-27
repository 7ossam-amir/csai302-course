"""Lab 5 Practice: the lab's query operators, rebuilt on a grade sheet.

Read executors.py first. Scan, VectorScan, collect and collect_batches are given;
complete the parts marked TODO.
"""
from collections import defaultdict
import numpy as np


# ---------- Part 2: Volcano (one row per next() call) ----------

class Scan:
    def __init__(self, rows):
        self.rows = rows

    def open(self):
        self.iterator = iter(self.rows)

    def next(self):
        return next(self.iterator, None)

    def close(self):
        self.iterator = iter(())


class Filter:
    def __init__(self, child, predicate):
        self.child, self.predicate = child, predicate

    def open(self):
        self.child.open()

    def next(self):
        """Return the next child row for which predicate(row) is true, or None at the end."""
        # TODO: keep asking self.child.next() until a row matches or None comes back.
        raise NotImplementedError

    def close(self):
        self.child.close()


class Project:
    def __init__(self, child, columns):
        self.child, self.columns = child, columns

    def open(self):
        self.child.open()

    def next(self):
        """Return the next child row keeping only self.columns, or None at the end."""
        # TODO: one child row in, one smaller dict out.
        raise NotImplementedError

    def close(self):
        self.child.close()


class Limit:
    """SQL LIMIT n: return at most n rows, then stop asking the child for more."""
    def __init__(self, child, n):
        if n < 0:
            raise ValueError("n must be nonnegative")
        self.child, self.n = child, n

    def open(self):
        """Open the child and reset the number of rows returned so far."""
        # TODO
        raise NotImplementedError

    def next(self):
        """Return None once n rows were returned, without calling the child again."""
        # TODO
        raise NotImplementedError

    def close(self):
        self.child.close()


def collect(operator):
    """Always release the operator tree, including when a predicate fails."""
    operator.open()
    try:
        result = []
        while (row := operator.next()) is not None:
            result.append(row)
        return result
    finally:
        operator.close()


# ---------- Part 3: vectorized (one batch of columns per next_batch() call) ----------

class VectorScan:
    def __init__(self, columns, batch_size=1024):
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.columns = {k: np.asarray(v) for k, v in columns.items()}
        lengths = {len(v) for v in self.columns.values()}
        if len(lengths) > 1:
            raise ValueError("column lengths must agree")
        self.length = next(iter(lengths), 0)
        self.batch_size = batch_size

    def open(self):
        self.offset = 0

    def next_batch(self):
        if self.offset >= self.length:
            return None
        start = self.offset
        self.offset = min(start + self.batch_size, self.length)
        return {k: v[start:self.offset] for k, v in self.columns.items()}

    def close(self):
        self.offset = self.length


class VectorFilter:
    def __init__(self, child, predicate):
        self.child, self.predicate = child, predicate

    def open(self):
        self.child.open()

    def next_batch(self):
        """Return the next non-empty filtered batch, or None at the end.
        predicate(batch) must give one Boolean per row, otherwise raise ValueError.
        """
        # TODO: compute one mask per batch, check it, skip batches with no match,
        # and apply the same mask to every column.
        raise NotImplementedError

    def close(self):
        self.child.close()


class VectorProject:
    def __init__(self, child, columns):
        self.child, self.columns = child, columns

    def open(self):
        self.child.open()

    def next_batch(self):
        """Return the next child batch keeping only self.columns, or None at the end."""
        # TODO
        raise NotImplementedError

    def close(self):
        self.child.close()


def collect_batches(operator):
    operator.open()
    try:
        result = []
        while (batch := operator.next_batch()) is not None:
            result.extend(dict(zip(batch, values)) for values in zip(*batch.values()))
        return result
    finally:
        operator.close()


# ---------- Part 4: hash join ----------

def hash_join(left, right, bucket_count=16):
    """Inner equijoin of integer keys; return every (left_index, right_index) pair.

    Build: put each left position in bucket key % bucket_count, and keep each bucket's
    keys in one NumPy array. Probe: for each right key, compare it with the whole
    bucket at once (keys == key) and emit every match.
    """
    if bucket_count <= 0:
        raise ValueError("bucket_count must be positive")
    left, right = np.asarray(left, dtype=np.int64), np.asarray(right, dtype=np.int64)
    # TODO: build the buckets from left (see simd_hash_join in executors.py).
    # TODO: probe with each right key; return Python ints, not NumPy integers.
    raise NotImplementedError
