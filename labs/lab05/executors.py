"""Educational row-at-a-time and column-at-a-time query operators."""
from collections import defaultdict
import numpy as np


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
        while (row := self.child.next()) is not None:
            if self.predicate(row):
                return row
        return None

    def close(self):
        self.child.close()


class Project:
    def __init__(self, child, columns):
        self.child, self.columns = child, columns

    def open(self):
        self.child.open()

    def next(self):
        row = self.child.next()
        return None if row is None else {key: row[key] for key in self.columns}

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
        while (batch := self.child.next_batch()) is not None:
            mask = np.asarray(self.predicate(batch))
            length = len(next(iter(batch.values())))
            if mask.dtype != np.bool_ or mask.shape != (length,):
                raise ValueError("predicate must return one Boolean per row")
            if mask.any():
                return {k: v[mask] for k, v in batch.items()}
        return None

    def close(self):
        self.child.close()


class VectorProject:
    def __init__(self, child, columns):
        self.child, self.columns = child, columns

    def open(self):
        self.child.open()

    def next_batch(self):
        batch = self.child.next_batch()
        return None if batch is None else {k: batch[k] for k in self.columns}

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


def scalar_hash_join(left, right):
    """Inner equijoin of integer keys; returns all (left_index, right_index) pairs."""
    table = defaultdict(list)
    for i, key in enumerate(left):
        table[int(key)].append(i)
    return [(i, j) for j, key in enumerate(right) for i in table.get(int(key), ())]


def simd_hash_join(left, right, bucket_count=256):
    """Hash partition + NumPy vector equality on contiguous int64 bucket keys.

    NumPy can dispatch equality to SIMD kernels on supported builds/CPUs.
    Hashing and output materialization are still Python; SIMD is not guaranteed.
    Duplicates produce a Cartesian product within each matching key.
    """
    if bucket_count <= 0:
        raise ValueError("bucket_count must be positive")
    left, right = np.asarray(left, dtype=np.int64), np.asarray(right, dtype=np.int64)
    if left.ndim != 1 or right.ndim != 1:
        raise ValueError("keys must be one-dimensional integer arrays")
    table = defaultdict(list)
    for i, key in enumerate(left):
        table[int(key) % bucket_count].append(i)
    buckets = {}
    for bucket, positions in table.items():
        indices = np.asarray(positions, dtype=np.int64)
        buckets[bucket] = (np.ascontiguousarray(left[indices]), indices)
    result = []
    for j, key in enumerate(right):
        bucket = buckets.get(int(key) % bucket_count)
        if bucket is not None:
            keys, indices = bucket
            result.extend((int(i), j) for i in indices[keys == key])
    return result
